# RET-C2-267 — Integration Tests: full outer graph compile + invoke
#
# Covers the Cat 2 outer/inner composition end-to-end:
#   low-value/volume order -> single invoke() -> ORDER_ROUTED, no HITL
#   high-value order       -> invoke() suspends (AWAITING_HUMAN) -> resume() -> approved/rejected
#   unfulfillable order    -> invoke() -> FAILED (no channel has sufficient stock)

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

LOW_VALUE_INPUT = json.dumps(
    {
        "order_id": "ORD-LOW-001",
        "channel": "EC",
        "items": [{"sku": "SKU-1", "qty": 2, "unit_price": 1000}],
        "quantity": 2,
        "delivery_address": {"region": "Tokyo", "street": "1-2-3 Shibuya"},
    }
)

HIGH_VALUE_INPUT = json.dumps(
    {
        "order_id": "ORD-HIGH-001",
        "channel": "EC",
        "items": [{"sku": "SKU-2", "qty": 5, "unit_price": 600000}],
        "quantity": 5,
        "delivery_address": {"region": "Osaka", "street": "4-5-6 Namba"},
    }
)

UNFULFILLABLE_INPUT = json.dumps(
    {
        "order_id": "ORD-FAIL-001",
        "channel": "EC",
        "items": [{"sku": "SKU-3", "qty": 60, "unit_price": 10}],
        "quantity": 60,
        "delivery_address": {"region": "Fukuoka", "street": "7-8-9 Hakata"},
    }
)


def _ctx() -> InvocationContext:
    return InvocationContext(caller_trust_level=TrustLevel.VERIFIED_EXTERNAL)


class TestFulfillmentOrchestrationGraph:
    def setup_method(self):
        self.agent = Graph(
            config={"memory_enabled": True, "hitl": {"enabled": True, "max_hitl": 8}, "policy": POLICY_CONFIG}
        )
        self.agent.compile(checkpointer=InMemorySaver())

    def test_low_value_order_routes_without_hitl(self):
        # NOTE: AgentBaseGraph.get_output() (framework default, not overridden by
        # this template) surfaces only output/status/trace_id/correlation_id/
        # node_history from the public invoke() envelope — domain fields live in
        # `formatted_output` (set by NotifyLogisticsNode), not as top-level keys
        # (verified against (internal reference removed) precedent: same envelope shape).
        result = self.agent.invoke(LOW_VALUE_INPUT, ctx=_ctx())
        assert result["status"] == AgentStatus.SUCCESS.value
        assert result["fulfillment_status"] == "ORDER_ROUTED"
        assert "fulfillment location was selected" in result["output"]
        assert "NotifyLogisticsNode" in result["node_history"]

    def test_high_value_order_suspends_then_resumes_approved(self):
        suspended = self.agent.invoke(HIGH_VALUE_INPUT, ctx=_ctx())
        assert suspended["status"] == AgentStatus.AWAITING_HUMAN.value
        assert suspended.get("thread_id")

        resumed = self.agent.resume(thread_id=suspended["thread_id"], feedback={"decision": "approved"})
        assert resumed["status"] == AgentStatus.SUCCESS.value
        assert resumed["fulfillment_status"] == "ORDER_ROUTED"
        assert "fulfillment location was selected" in resumed["output"]

    def test_high_value_order_resumes_rejected_escalates(self):
        suspended = self.agent.invoke(HIGH_VALUE_INPUT, ctx=_ctx())
        assert suspended["status"] == AgentStatus.AWAITING_HUMAN.value

        resumed = self.agent.resume(thread_id=suspended["thread_id"], feedback={"decision": "rejected"})
        assert resumed["status"] == AgentStatus.SUCCESS.value
        assert resumed["fulfillment_status"] == "HITL_ESCALATION"
        assert "human decision" in resumed["output"]

    def test_unfulfillable_order_fails(self):
        result = self.agent.invoke(UNFULFILLABLE_INPUT, ctx=_ctx())
        assert result["status"] == AgentStatus.SUCCESS.value
        assert result["fulfillment_status"] == "FAILED"
        assert "No fulfillment location" in result["output"]

    def test_empty_input_is_answered_with_the_order_shape(self):
        """SUCCESS with the guidance as the body: an ERROR here reaches the sender as
        "agent failed" and the shape they need to send is discarded with it."""
        result = self.agent.invoke("", ctx=_ctx(), input_context={"conversation_history": []})
        assert result["status"] == AgentStatus.SUCCESS.value
        assert "order_id" in result["output"]
