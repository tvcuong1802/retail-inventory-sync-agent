"""AgentCore Platform v1.0"""

from typing import Any


# Inner graph for the Cat 2 fulfillment-orchestration template (RET-C2-267).
# Instantiated by FulfillmentOrchestrationGraphNode.get_subgraph() in graph.py.
#
# Pipeline (linear, Engineer Review §4 Steps 2-6):
#   START → inventory_check → fulfillment_policy → route_select
#         → hitl_gate (D6 interrupt() at/above threshold) → fulfillment_instruct → END

from langgraph.graph import END, START

from framework.graph.base_graph import BaseGraph
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from src.nodes.fulfillment_instruct_node import FulfillmentInstructNode
from src.nodes.fulfillment_policy_node import FulfillmentPolicyNode
from src.nodes.hitl_gate_node import HITLGateNode
from src.nodes.inventory_check_node import InventoryCheckNode
from src.nodes.route_select_node import RouteSelectNode
from src.schemas.state import State


class FulfillmentWorkflowGraph(BaseGraph):
    """Inner graph: inventory check -> policy -> route select -> HITL gate -> instruct.

    Inherits BaseGraph directly for a fully custom topology (no pre_process/
    main/post_process slots — those are the outer graph's concern).
    """

    @property
    def name(self) -> str:
        return "ret_c2_267_fulfillment_workflow"

    @property
    def state_schema(self) -> type:
        return State

    def _validate_config(self) -> None:
        # No mandatory config beyond the inherited memory_enabled/hitl checks,
        # which BaseGraph itself does not validate (that lives in the outer
        # AgentBaseGraph). Nothing agent-specific is required here.
        pass

    def register_nodes(self) -> None:
        # No super() call — BaseGraph.register_nodes() is abstract.
        # initialize/finalize are outer-graph concerns, not registered here.
        policy_config = self.config.get("policy", {}) if hasattr(self, "config") else {}
        self._nodes["inventory_check"] = InventoryCheckNode()
        self._nodes["fulfillment_policy"] = FulfillmentPolicyNode(policy_config=policy_config)
        self._nodes["route_select"] = RouteSelectNode()
        self._nodes["hitl_gate"] = HITLGateNode()
        self._nodes["fulfillment_instruct"] = FulfillmentInstructNode()

    def add_edges(self) -> None:
        self._sg.add_edge(START, "inventory_check")
        self._sg.add_edge("inventory_check", "fulfillment_policy")
        self._sg.add_edge("fulfillment_policy", "route_select")
        self._sg.add_edge("route_select", "hitl_gate")
        self._sg.add_edge("hitl_gate", "fulfillment_instruct")
        self._sg.add_edge("fulfillment_instruct", END)

    def route(self, state: AgentState) -> str:
        # Required by BaseGraph ABC; this topology is linear (no conditional
        # edges reference route()), so it is never called at runtime.
        return END if state.get("status") == AgentStatus.ERROR.value else "fulfillment_instruct"

    def get_output(self, state: AgentState) -> dict[str, Any]:
        return {
            "validated_order": state.get("validated_order", {}),
            "inventory_snapshot": state.get("inventory_snapshot", {}),
            "policy_decision": state.get("policy_decision", {}),
            "selected_route": state.get("selected_route", {}),
            "hitl_review_outcome": state.get("hitl_review_outcome"),
            "fulfillment_instruction": state.get("fulfillment_instruction", {}),
            "status": state.get("status"),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
        }
