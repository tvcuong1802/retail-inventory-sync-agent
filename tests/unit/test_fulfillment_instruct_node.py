# RET-C2-267 — Unit Tests: FulfillmentInstructNode

from framework.schemas.agent_status import AgentStatus
from src.nodes.fulfillment_instruct_node import FulfillmentInstructNode


class TestFulfillmentInstructNode:
    def setup_method(self):
        self.node = FulfillmentInstructNode()

    def test_fulfillable_and_approved_ships(self):
        state = {
            "validated_order": {"order_id": "ORD-001"},
            "selected_route": {"source_channel": "WMS", "fulfillable": True},
            "hitl_review_outcome": "auto_approved",
            "node_history": [],
            "error_log": [],
        }
        result = self.node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS
        assert result["fulfillment_instruction"]["action"] == "ship"

    def test_rejected_holds(self):
        state = {
            "validated_order": {"order_id": "ORD-002"},
            "selected_route": {"source_channel": "WMS", "fulfillable": True},
            "hitl_review_outcome": "rejected",
            "node_history": [],
            "error_log": [],
        }
        result = self.node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS
        assert result["fulfillment_instruction"]["action"] == "hold"

    def test_not_fulfillable_holds(self):
        state = {
            "validated_order": {"order_id": "ORD-003"},
            "selected_route": {"source_channel": None, "fulfillable": False},
            "hitl_review_outcome": "auto_approved",
            "node_history": [],
            "error_log": [],
        }
        result = self.node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS
        assert result["fulfillment_instruction"]["action"] == "hold"

    def test_no_validated_order_error(self):
        state = {"node_history": [], "error_log": []}
        result = self.node.execute(state)
        assert result["status"] == AgentStatus.ERROR
