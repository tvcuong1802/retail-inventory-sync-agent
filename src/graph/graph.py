"""AgentCore Platform v1.0"""

# RET-C2-267 — Retail Omnichannel Inventory Sync & Fulfillment Orchestration Agent
#
# Cat 2 pattern (CoE 2026-06-17 mandate): outer AgentBaseGraph backbone +
# GraphNode in the `main` slot wrapping an inner BaseGraph subgraph.
#
# Outer backbone (fixed, do NOT override add_edges()):
#   START → initialize → pre_process(OrderIngest) → main(GraphNode)
#         → post_process(NotifyLogistics) → finalize → END
#
# Inside `main`: FulfillmentOrchestrationGraphNode wraps
# src/graph/fulfillment_workflow_graph.py (inventory check → policy → route
# select → HITL gate → fulfillment instruct).
#
# HITL note (the framework contract + the Cat-2 composition pattern "Cat 2 + HITL"):
# the interrupt() lives in the INNER subgraph's HITLGateNode. The inner
# subgraph is compiled with its own checkpointer (InMemorySaver) and forwards
# memory_enabled/hitl/policy config via _parent_config(); propagate_hitl=True
# on this GraphNode, together with _handle_call_error re-raising the nested
# GraphBubbleUp, surfaces the inner AWAITING_HUMAN status to the outer caller.
#
# PB-6 scope note: PB-6 (tests/proof_of_boundary/test_pb_invoke_order.py) only
# discovers concrete BaseNode subclasses under src/nodes/, so this outer
# GraphNode's S-1 gate / extract_input / merge_output boundary is probed
# separately by tests/proof_of_boundary/test_pb_graphnode_boundary.py.

from typing import Any, ClassVar

from langgraph.checkpoint.memory import InMemorySaver

from framework.graph.agent_base_graph import AgentBaseGraph
from framework.nodes.graph_node import GraphNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.agent_state import AgentState
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.nodes.order_ingest_node import OrderIngestNode
from src.nodes.notify_logistics_node import NotifyLogisticsNode
from src.schemas.state import State


class FulfillmentOrchestrationGraphNode(GraphNode):
    """Wraps the inner fulfillment-orchestration workflow graph (`main` slot)."""

    # S-1: outer main-slot wrapper — first node in the outer backbone to
    # receive caller input after pre_process. Must match agent.yaml
    # required_trust_level and the sibling outer nodes (order_ingest /
    # notify_logistics), NOT the inner subgraph's ANONYMOUS (see 3b).
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    # "propagate": re-raise inner SubgraphError as-is (fail fast) — default.
    error_strategy: ClassVar[str] = "propagate"

    # True: surface the inner HITL interrupt (threshold review) to the outer
    # caller. Requires hitl.enabled: true on the outer agent.yaml config too.
    propagate_hitl: ClassVar[bool] = True

    def __init__(self, policy_config: dict[str, Any] | None = None) -> None:
        super().__init__()
        self._policy_config = policy_config or {}
        # Cache the compiled subgraph — construction (incl. checkpointer) is
        # not free, and the checkpointer must persist across invoke()/resume()
        # within the same process (a fresh InMemorySaver per call loses the
        # checkpoint between the initial interrupt and the resume).
        # Built once and reused: the HITL checkpointer must survive across resume calls.
        self._subgraph: Any = None

    def _handle_call_error(self, subgraph: Any, e: Exception, state: Any) -> Any:
        # Nested-subgraph HITL (the Cat-2 composition pattern "Cat 2 + HITL"): when
        # the inner subgraph's own compiled invoke() runs INSIDE the outer
        # graph's active LangGraph run (as here — GraphNode.execute() is
        # itself a node function of the outer StateGraph), LangGraph does NOT
        # catch the inner interrupt() and convert it to an "__interrupt__"
        # result the way it does for a standalone top-level invoke() — the
        # GraphInterrupt instead bubbles up as a Python exception. The default
        # _handle_call_error() would wrap it into SubgraphError (status=error),
        # destroying the HITL signal. Re-raise GraphBubbleUp/GraphInterrupt
        # as-is so it reaches the outer graph's own Pregel loop, which (being
        # compiled with a checkpointer) converts it into the outer AWAITING_HUMAN
        # status — matching propagate_hitl=True's intent.
        from langgraph.errors import GraphBubbleUp

        if isinstance(e, GraphBubbleUp) or "interrupt" in type(e).__name__.lower():
            raise e
        return super()._handle_call_error(subgraph, e, state)

    def execute(self, state: AgentState) -> dict[str, Any]:
        """Skip the subgraph when pre_process already answered.

        An unusable message is answered upstream with guidance. Without this the subgraph
        still runs, its first node finds nothing to work on, and the run ends at status
        error -- which the runner raises on, so the guidance written for that reader is
        never seen.
        """
        if state.get("input_unusable"):
            emit_trace_event("subgraph_skipped", {"reason": "input unusable"}, state)
            return {}
        return dict(super().execute(state))

    def get_subgraph(self) -> Any:
        from src.graph.fulfillment_workflow_graph import FulfillmentWorkflowGraph

        if self._subgraph is None:
            sg = FulfillmentWorkflowGraph(config=self._parent_config())
            sg.compile(checkpointer=InMemorySaver())
            self._subgraph = sg
        return self._subgraph

    def extract_input(self, state: AgentState) -> str:
        # S-4: emit the dispatch event inside GraphNode.execute() (this hook
        # runs before subgraph.invoke()) — GraphNode itself is not overridden.
        emit_trace_event("fulfillment_dispatched", {"correlation_id": state.get("correlation_id")}, state)
        return str(state.get("validated_input", state.get("user_input", "")))

    def merge_output(self, state: AgentState, sub_result: dict[str, Any]) -> dict[str, Any]:
        emit_trace_event(
            "fulfillment_completed",
            {"hitl_review_outcome": sub_result.get("hitl_review_outcome")},
            state,
        )
        return {
            "validated_order": sub_result.get("validated_order", {}),
            "inventory_snapshot": sub_result.get("inventory_snapshot", {}),
            "policy_decision": sub_result.get("policy_decision", {}),
            "selected_route": sub_result.get("selected_route", {}),
            "hitl_review_outcome": sub_result.get("hitl_review_outcome"),
            "fulfillment_instruction": sub_result.get("fulfillment_instruction", {}),
            "status": sub_result.get("status"),
        }

    def _parent_config(self) -> dict[str, Any]:
        # Forward memory_enabled + hitl so the inner BaseGraph.invoke() builds
        # a thread config for the checkpointer (required for interrupt()), and
        # forward the deterministic routing/HITL-threshold policy config.
        return {
            "memory_enabled": True,
            "hitl": {"enabled": True, "max_hitl": 8},
            "policy": self._policy_config,
        }


#: Framework security refusals a node cannot intercept, because the gate that raises them
#: runs inside ``BaseNode.__call__()`` around ``execute()``.
_SECURITY_REFUSALS = ("cannot be processed safely", "security gate", "s-2 ", "s-3 ", "credential pattern")


def _is_security_refusal(reason: str) -> bool:
    """True when the framework refused the MESSAGE, not when the agent broke."""
    return any(marker in str(reason).lower() for marker in _SECURITY_REFUSALS)


class FulfillmentOrchestrationGraph(AgentBaseGraph):
    """RET-C2-267 outer graph. Domain logic lives in
    FulfillmentOrchestrationGraphNode (`main` slot) + the inner
    FulfillmentWorkflowGraph."""

    @property
    def name(self) -> str:
        return "ret-c2-267"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        super().register_nodes()  # injects initialize + finalize
        cfg = self.config if hasattr(self, "config") else {}
        # `config["llm"]` is a block of SETTINGS, not a client. Passing it down under the
        # name a node reads as a client makes that node call `.complete()` on a dict.
        llm_settings = cfg.get("llm") if isinstance(cfg.get("llm"), dict) else {}
        # Domain settings live under `domain_config:` in config.yaml. Read at the root they
        # resolve to {} and every declared knob silently falls back to its default.
        domain = cfg.get("domain_config") if isinstance(cfg.get("domain_config"), dict) else {}
        policy_config = domain.get("policy", cfg.get("policy", {}))
        self._nodes["pre_process"] = OrderIngestNode(config={"llm": llm_settings})
        self._nodes["main"] = FulfillmentOrchestrationGraphNode(policy_config=policy_config)
        self._nodes["post_process"] = NotifyLogisticsNode()

    # add_edges() is NOT overridden — backbone wiring belongs to the framework.

    def get_output(self, state: Any) -> dict[str, Any]:
        """Framework envelope, with a payload a person can read.

        `output` must be a str of Markdown: handed the framework dict, the chat surface
        renders quoted keys and literal \n where the answer should be. The structured
        payload stays under `formatted_output` for the HTTP adapter and the boundary tests.
        """
        from src.services.agent_scope import SCOPE_EN, SCOPE_JA
        from src.services.output_envelope import with_disclaimer

        base = dict(super().get_output(state))
        base["error_log"] = state.get("error_log")
        # The terminal state is what a calling SYSTEM branches on -- ORDER_ROUTED /
        # HITL_ESCALATION / FAILED. It is deliberately not in the prose the human reads,
        # and it has to be somewhere the machine can find it.
        base["fulfillment_status"] = state.get("fulfillment_status")
        base["fulfillment_instruction"] = state.get("fulfillment_instruction")
        base["hitl_review_outcome"] = state.get("hitl_review_outcome")
        base["formatted_output"] = state.get("formatted_output")

        body = self._reader_body(state)
        if body:
            base["output"] = body
            return with_disclaimer(base, state, scope_en=SCOPE_EN, scope_ja=SCOPE_JA)

        if str(state.get("status")) == "error" and not base.get("output"):
            from src.services.agent_scope import REFUSAL_EN, REFUSAL_JA
            from src.services.disclaimer import disclaimer

            reasons = [str(e) for e in (state.get("error_log") or [])]

            # S-1 denial is the one refusal that carries NOTHING else. A caller who is not
            # permitted to invoke this agent must not be handed the scope line: it names
            # what the agent is for, which is exactly what the refusal withheld.
            if any("trust gate denied" in r.lower() for r in reasons):
                base["output"] = (
                    "## リクエストを拒否しました\n\nこの呼び出し元には本エージェントの実行"
                    "権限がありません。\n\n---\n\n## Request refused\n\nThis caller is not "
                    "permitted to invoke this agent.\n"
                )
                emit_trace_event("caller_refused", {"reason": "trust_gate"}, state)
                return base

            base["output"] = f"{REFUSAL_JA}\n\n---\n\n{REFUSAL_EN}".rstrip() + disclaimer(
                str(state.get("answer_language") or ""), scope_en=SCOPE_EN, scope_ja=SCOPE_JA
            )
            emit_trace_event("request_refused", {"reason": (reasons[0] if reasons else "")[:120]}, state)
            # A refusal the framework raised BEFORE execute() -- the S-2 injection gate, or
            # the S-3 gate on a node's own result -- cannot be returned by a node:
            # BaseNode.__call__() runs both gates around it. Measured against the wheel:
            # normalize_terminal_output() raises on any status but SUCCESS, so leaving this
            # as an error means the sender reads "agent failed" instead of what to change.
            # error_log and the audit event are untouched; only the SENDER's view changes.
            # The S-1 denial is handled above and deliberately stays an error.
            if any(_is_security_refusal(r) for r in reasons):
                base["status"] = AgentStatus.SUCCESS.value
            return base

        return with_disclaimer(base, state, scope_en=SCOPE_EN, scope_ja=SCOPE_JA)

    #: What each terminal state means to the person reading it. The codes are how the
    #: pipeline reasons; a reader given `ORDER_ROUTED` is reading our internals.
    _STATUS_TEXT = {
        "ja": {
            "ORDER_ROUTED": "出荷元が決まりました",
            "HITL_ESCALATION": "担当者の確認が必要です",
            "FAILED": "出荷元を決められませんでした",
        },
        "en": {
            "ORDER_ROUTED": "A fulfillment location was selected",
            "HITL_ESCALATION": "This order needs a human decision",
            "FAILED": "No fulfillment location could be selected",
        },
    }

    def _routing_as_prose(self, state: Any) -> str:
        """The routing decision as Markdown an operator can read.

        The body used to be `order_id=... status=...`, which never said WHERE the order
        ships from -- the one thing this agent exists to decide.
        """
        ja = not str(state.get("answer_language") or "ja").startswith("en")
        lang = "ja" if ja else "en"
        order = state.get("validated_order") if isinstance(state.get("validated_order"), dict) else {}
        route = state.get("selected_route") if isinstance(state.get("selected_route"), dict) else {}
        status = str(state.get("fulfillment_status") or "")
        lines = [f"## {self._STATUS_TEXT[lang].get(status, status)}", ""]

        rows = [
            ("注文番号" if ja else "Order", order.get("order_id")),
            ("出荷元" if ja else "Ships from", route.get("source_channel")),
            ("お届け地域" if ja else "Delivery region", state.get("delivery_region")),
            ("数量" if ja else "Quantity", order.get("quantity")),
        ]
        lines += [f"- **{name}:** {value}" for name, value in rows if value not in (None, "", [], {})]

        snapshot = state.get("inventory_snapshot")
        if isinstance(snapshot, dict) and snapshot:
            lines += ["", "**照会時点の在庫** " if ja else "**Stock as returned at lookup time**"]
            for sku, detail in snapshot.items():
                stock = detail.get("channel_stock", {}) if isinstance(detail, dict) else {}
                need = detail.get("qty_needed") if isinstance(detail, dict) else None
                per = ", ".join(f"{ch} {qty}" for ch, qty in stock.items())
                lines.append(f"- **{sku}** ({'必要数' if ja else 'needed'} {need}): {per}")

        if str(state.get("hitl_review_outcome") or "") == "referred_for_human_review":
            lines += [
                "",
                (
                    "**このご注文は自動では確定できません。担当者の確認が必要です。**"
                    if ja
                    else "**This order cannot be confirmed automatically and is waiting on a human decision.**"
                ),
            ]
        return "\n".join(lines).strip()

    def _reader_body(self, state: Any) -> str:
        """This agent's answer as Markdown, with the degraded notice above it."""
        if not isinstance(state, dict):
            return ""
        if state.get("input_unusable"):
            return str(state.get("result") or "")

        if state.get("fulfillment_status"):
            return self._routing_as_prose(state)

        formatted = state.get("formatted_output")
        if isinstance(formatted, dict):
            formatted = "\n".join(
                f"- **{key}:** {value}" for key, value in formatted.items() if value not in (None, "", [], {})
            )
        if not isinstance(formatted, str) or not formatted.strip():
            return ""

        from src.services.agent_scope import DEGRADED_NOTICE_EN, DEGRADED_NOTICE_JA

        ja = not str(state.get("answer_language") or "ja").startswith("en")
        parts = []
        if state.get("drafting_degraded"):
            # Above the answer, not below it: a caveat printed under the conclusion it
            # qualifies is a caveat the reader has already acted on.
            parts.append((DEGRADED_NOTICE_JA if ja else DEGRADED_NOTICE_EN) + "\n")
        parts.append(formatted.strip())
        return "\n".join(parts)


Graph = FulfillmentOrchestrationGraph  # alias for config/agent.yaml module:"src.graph"
