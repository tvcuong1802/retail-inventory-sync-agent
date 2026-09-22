# PB-7: HITL Interrupt Propagation — required by exact filename for every
# template that enables HITL, independently of which stage the CI listing places
# it in. The test below is the real propagation test, not the auto-skip stub.
#
# RET-C2-267 has hitl.enabled: true (config/agent.yaml), so this is a REAL
# GraphInterrupt-propagation test (not the auto-skip stub used by
# non-HITL templates): interrupt() inside the inner subgraph's HITLGateNode
# raises GraphInterrupt, the signal propagates through BaseNode.__call__()
# (which explicitly re-raises GraphBubbleUp — see framework/nodes/base_node.py),
# is NOT caught by the application error boundary, and status is NOT set to
# "error" — it surfaces as AWAITING_HUMAN through the Cat 2 outer/inner
# GraphNode boundary (propagate_hitl=True, see src/graph/graph.py).

import json

from langgraph.checkpoint.memory import InMemorySaver

from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from src.graph.graph import Graph

POLICY_CONFIG = {
    "routing": {"channel_priority": ["WMS", "POS", "EC"]},
    "hitl": {"amount_threshold_jpy": 500000, "volume_threshold_units": 100},
}

HIGH_VALUE_INPUT = json.dumps(
    {
        "order_id": "ORD-HIGH-PB7",
        "channel": "EC",
        "items": [{"sku": "SKU-PB7", "qty": 5, "unit_price": 600000}],
        "quantity": 5,
        "delivery_address": {"region": "Nagoya", "street": "1-1-1 Sakae"},
    }
)


class TestPB7HitlInterruptPropagation:
    """PB-7: interrupt() propagates as AWAITING_HUMAN, never as status=error."""

    def test_high_value_interrupt_surfaces_as_awaiting_human_not_error(self):
        agent = Graph(
            config={"memory_enabled": True, "hitl": {"enabled": True, "max_hitl": 8}, "policy": POLICY_CONFIG}
        )
        agent.compile(checkpointer=InMemorySaver())
        ctx = InvocationContext(caller_trust_level=TrustLevel.VERIFIED_EXTERNAL)

        result = agent.invoke(HIGH_VALUE_INPUT, ctx=ctx)

        assert result["status"] == AgentStatus.AWAITING_HUMAN.value
        assert result["status"] != AgentStatus.ERROR.value
        assert result.get("thread_id")

    def test_resume_after_interrupt_completes_successfully(self):
        agent = Graph(
            config={"memory_enabled": True, "hitl": {"enabled": True, "max_hitl": 8}, "policy": POLICY_CONFIG}
        )
        agent.compile(checkpointer=InMemorySaver())
        ctx = InvocationContext(caller_trust_level=TrustLevel.VERIFIED_EXTERNAL)

        suspended = agent.invoke(HIGH_VALUE_INPUT, ctx=ctx)
        resumed = agent.resume(thread_id=suspended["thread_id"], feedback={"decision": "approved"})

        assert resumed["status"] == AgentStatus.SUCCESS.value
        # Domain fields live in `formatted_output` (AgentBaseGraph.get_output()
        # only surfaces output/status/trace_id/correlation_id/node_history).
        assert "fulfillment location was selected" in resumed["output"]
