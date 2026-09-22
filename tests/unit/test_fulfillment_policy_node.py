# RET-C2-267 — Unit Tests: FulfillmentPolicyNode

from framework.schemas.agent_status import AgentStatus
from src.nodes.fulfillment_policy_node import FulfillmentPolicyNode

POLICY_CONFIG = {
    "routing": {"channel_priority": ["WMS", "POS", "EC"]},
    "hitl": {"amount_threshold_jpy": 500000, "volume_threshold_units": 100},
}


class TestFulfillmentPolicyNode:
    def setup_method(self):
        self.node = FulfillmentPolicyNode(policy_config=POLICY_CONFIG)

    def test_below_threshold_no_hitl(self):
        state = {
            "validated_order": {
                "order_id": "ORD-001",
                "items": [{"sku": "SKU-1", "qty": 2, "unit_price": 1000}],
                "quantity": 2,
            },
            "inventory_snapshot": {},
            "node_history": [],
            "error_log": [],
        }
        result = self.node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS
        assert result["policy_decision"]["requires_hitl"] is False

    def test_above_amount_threshold_requires_hitl(self):
        state = {
            "validated_order": {
                "order_id": "ORD-002",
                "items": [{"sku": "SKU-2", "qty": 5, "unit_price": 600000}],
                "quantity": 5,
            },
            "inventory_snapshot": {},
            "node_history": [],
            "error_log": [],
        }
        result = self.node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS
        assert result["policy_decision"]["requires_hitl"] is True

    def test_no_validated_order_error(self):
        state = {"node_history": [], "error_log": []}
        result = self.node.execute(state)
        assert result["status"] == AgentStatus.ERROR

    def test_default_no_args_construction(self):
        """PB-6 instantiates every node class with no constructor args."""
        node = FulfillmentPolicyNode()
        state = {"validated_order": {"items": [], "quantity": 0}, "inventory_snapshot": {}, "node_history": [], "error_log": []}
        result = node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS
