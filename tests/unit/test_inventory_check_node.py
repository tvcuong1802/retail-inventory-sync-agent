# RET-C2-267 — Unit Tests: InventoryCheckNode

import json

from framework.schemas.agent_status import AgentStatus
from src.nodes.inventory_check_node import InventoryCheckNode


class TestInventoryCheckNode:
    def setup_method(self):
        self.node = InventoryCheckNode()

    def test_success_path(self):
        state = {
            "user_input": json.dumps(
                {"order_id": "ORD-001", "channel": "EC", "items": [{"sku": "SKU-1", "qty": 2}], "quantity": 2}
            ),
            "node_history": [],
            "error_log": [],
        }
        result = self.node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS
        assert "SKU-1" in result["inventory_snapshot"]
        assert result["inventory_snapshot"]["SKU-1"]["channel_stock"]["WMS"] == 50

    def test_no_items_error(self):
        state = {
            "user_input": json.dumps({"order_id": "ORD-001", "channel": "EC", "items": []}),
            "node_history": [],
            "error_log": [],
        }
        result = self.node.execute(state)
        assert result["status"] == AgentStatus.ERROR

    def test_malformed_input_error(self):
        state = {"user_input": "not json", "node_history": [], "error_log": []}
        result = self.node.execute(state)
        assert result["status"] == AgentStatus.ERROR
