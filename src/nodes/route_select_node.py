"""AgentCore Platform v1.0"""

# Inner subgraph node — Step 4 (RouteSelectNode) of the Engineer Review workflow.
# Selects the optimal fulfillment source location per the policy's channel priority.

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.services.fulfillment_service import select_route


class RouteSelectNode(FunctionNode):
    """Select the optimal fulfillment source location."""

    # S-1: inner subgraph node — trust already authenticated at the outer backbone.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        inventory_snapshot = state.get("inventory_snapshot", {})
        policy_decision = state.get("policy_decision", {})

        if not policy_decision:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["RouteSelectNode: no policy_decision in state"],
            }

        selected_route = select_route(inventory_snapshot, policy_decision)

        emit_trace_event(
            "route_selected",
            {"source_channel": selected_route.get("source_channel"), "fulfillable": selected_route["fulfillable"]},
            state,
        )

        return {
            "selected_route": selected_route,
            "status": AgentStatus.SUCCESS.value,
        }
