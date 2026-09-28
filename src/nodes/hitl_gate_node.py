"""AgentCore Platform v1.0"""

# Inner subgraph node — Step 5 (HITLGateNode) of the Engineer Review workflow.
# D6 pattern (the framework contract): the framework owns pause/resume; this node only
# owns the trigger condition (policy_decision.requires_hitl). Requires
# hitl.enabled:true + memory_enabled:true on BOTH the inner graph config (this
# subgraph, via GraphNode._parent_config()) and the outer agent config
# (config/agent.yaml) — see src/graph/graph.py.
#
# Never auto-approve: a resume timeout leaves the graph suspended
# (AWAITING_HUMAN) rather than falling through to an approval.

from typing import Any, ClassVar

from langgraph.types import interrupt

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event


class HITLGateNode(FunctionNode):
    """Independent HITL gate: interrupt() for human review above policy threshold."""

    # S-1: inner subgraph node — trust already authenticated at the outer backbone.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        policy_decision = state.get("policy_decision", {})
        requires_hitl = bool(policy_decision.get("requires_hitl", False))

        if not requires_hitl:
            emit_trace_event("hitl_gate_skipped", {"requires_hitl": False}, state)
            return {
                "hitl_review_outcome": "auto_approved",
                "status": AgentStatus.SUCCESS.value,
            }

        draft = {
            "selected_route": state.get("selected_route"),
            "policy_decision": policy_decision,
            "reason": "order at/above the configured amount or volume threshold requires human review",
        }
        if not state.get("hitl_allowed", True):
            # No one is there to answer. A parent GraphNode runs this agent with
            # hitl_allowed=False precisely to say so, and an unconditional interrupt()
            # deadlocks that composition -- the framework contract calls it a blocking defect.
            # The order still needs a human, so say that instead of suspending: the
            # caller gets a decision they can act on rather than a run that never returns.
            emit_trace_event("hitl_gate_deferred", {"reason": "hitl_not_allowed"}, state)
            return {
                "hitl_draft": draft,
                "hitl_review_outcome": "referred_for_human_review",
                "status": AgentStatus.SUCCESS.value,
            }

        # hitl_draft prevents recomputation on resume (the framework contract).
        feedback = interrupt({"draft": draft, "reason": draft["reason"]})

        emit_trace_event("hitl_gate_reviewed", {"requires_hitl": True}, state)

        return {
            "hitl_draft": draft,
            "hitl_feedback": feedback,
            "hitl_review_outcome": feedback.get("decision", "rejected") if isinstance(feedback, dict) else "rejected",
            "status": AgentStatus.SUCCESS.value,
        }
