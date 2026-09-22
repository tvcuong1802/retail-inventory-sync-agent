# RET-C2-267 — Unit Tests: RouteSelectNode

from framework.schemas.agent_status import AgentStatus
from src.nodes.route_select_node import RouteSelectNode


class TestRouteSelectNode:
    def setup_method(self):
        self.node = RouteSelectNode()

    def test_fulfillable_picks_first_priority_channel_with_stock(self):
        state = {
            "inventory_snapshot": {"SKU-1": {"qty_needed": 2, "channel_stock": {"WMS": 50, "POS": 20, "EC": 10}}},
            "policy_decision": {"channel_priority": ["WMS", "POS", "EC"], "requires_hitl": False},
            "node_history": [],
            "error_log": [],
        }
        result = self.node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS
        assert result["selected_route"]["fulfillable"] is True
        assert result["selected_route"]["source_channel"] == "WMS"

    def test_no_channel_sufficient_stock(self):
        state = {
            "inventory_snapshot": {"SKU-3": {"qty_needed": 60, "channel_stock": {"WMS": 50, "POS": 20, "EC": 10}}},
            "policy_decision": {"channel_priority": ["WMS", "POS", "EC"], "requires_hitl": False},
            "node_history": [],
            "error_log": [],
        }
        result = self.node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS
        assert result["selected_route"]["fulfillable"] is False

    def test_no_policy_decision_error(self):
        state = {"inventory_snapshot": {}, "node_history": [], "error_log": []}
        result = self.node.execute(state)
        assert result["status"] == AgentStatus.ERROR
