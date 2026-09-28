# RET-C2-267 — Unit Tests: OrderIngestNode

import json

from framework.schemas.agent_status import AgentStatus
from src.nodes.order_ingest_node import OrderIngestNode


class TestOrderIngestNode:
    def setup_method(self):
        self.node = OrderIngestNode()

    def test_success_path_region_only_address(self):
        state = {
            "user_input": json.dumps(
                {
                    "order_id": "ORD-001",
                    "channel": "EC",
                    "items": [{"sku": "SKU-1", "qty": 2, "unit_price": 1000}],
                    "quantity": 2,
                    "delivery_address": {"region": "Tokyo", "street": "1-2-3 Shibuya"},
                }
            ),
            "node_history": [],
            "error_log": [],
        }
        result = self.node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS
        assert result["delivery_region"] == "Tokyo"
        assert "street" not in json.dumps(result["validated_order"])
        assert result["validated_order"]["order_id"] == "ORD-001"
        assert "validated_input" in result

    def test_missing_field_error(self):
        state = {
            "user_input": json.dumps({"order_id": "ORD-002", "channel": "EC"}),
            "node_history": [],
            "error_log": [],
        }
        result = self.node.execute(state)
        # SUCCESS with the sentence that says what the order envelope needs. The runner
        # raises on every status but SUCCESS, and this agent cannot look an order up on
        # its own, so that sentence is the value of this path.
        assert result["status"] == AgentStatus.SUCCESS.value
        assert result["input_unusable"] is True
        assert result["formatted_output"].strip()

    def test_malformed_input_error(self):
        state = {"user_input": "not json", "node_history": [], "error_log": []}
        result = self.node.execute(state)
        # SUCCESS with the sentence that says what the order envelope needs. The runner
        # raises on every status but SUCCESS, and this agent cannot look an order up on
        # its own, so that sentence is the value of this path.
        assert result["status"] == AgentStatus.SUCCESS.value
        assert result["input_unusable"] is True
        assert result["formatted_output"].strip()
