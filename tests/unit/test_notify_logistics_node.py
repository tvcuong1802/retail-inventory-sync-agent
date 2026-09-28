# RET-C2-267 — Unit Tests: NotifyLogisticsNode

from framework.schemas.agent_status import AgentStatus
from src.nodes.notify_logistics_node import NotifyLogisticsNode


class TestNotifyLogisticsNode:
    def setup_method(self):
        self.node = NotifyLogisticsNode()

    def test_shipped_order_routed(self):
        state = {
            "fulfillment_instruction": {"order_id": "ORD-001", "action": "ship"},
            "hitl_review_outcome": "auto_approved",
            "node_history": [],
            "error_log": [],
        }
        result = self.node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS
        assert result["notification_sent"] is True
        assert result["hitl_escalated"] is False
        assert result["fulfillment_status"] == "ORDER_ROUTED"

    def test_rejected_hitl_escalation(self):
        state = {
            "fulfillment_instruction": {"order_id": "ORD-002", "action": "hold"},
            "hitl_review_outcome": "rejected",
            "node_history": [],
            "error_log": [],
        }
        result = self.node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS
        assert result["hitl_escalated"] is True
        assert result["fulfillment_status"] == "HITL_ESCALATION"

    def test_unfulfillable_hold_failed(self):
        state = {
            "fulfillment_instruction": {"order_id": "ORD-003", "action": "hold"},
            "hitl_review_outcome": "auto_approved",
            "node_history": [],
            "error_log": [],
        }
        result = self.node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS
        assert result["fulfillment_status"] == "FAILED"

    def test_no_instruction_failed(self):
        state = {"node_history": [], "error_log": []}
        result = self.node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS
        assert result["notification_sent"] is False
        assert result["fulfillment_status"] == "FAILED"
