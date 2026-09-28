"""AgentCore Platform v1.0"""

# Inner subgraph node — Step 6 (FulfillmentInstructNode) of the Engineer
# Review workflow. Emits the fulfillment instruction consumed by logistics
# (outer post_process / NotifyLogisticsNode).

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.services.fulfillment_service import build_fulfillment_instruction


class FulfillmentInstructNode(FunctionNode):
    """Build the fulfillment instruction for logistics."""

    # S-1: inner subgraph node — trust already authenticated at the outer backbone.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        validated_order = state.get("validated_order", {})
        selected_route = state.get("selected_route", {})
        hitl_review_outcome = state.get("hitl_review_outcome", "auto_approved")

        if not validated_order:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["FulfillmentInstructNode: no validated_order in state"],
            }

        fulfillment_instruction = build_fulfillment_instruction(validated_order, selected_route, hitl_review_outcome)

        emit_trace_event(
            "fulfillment_instruction_built",
            {"action": fulfillment_instruction["action"]},
            state,
        )

        return {
            "fulfillment_instruction": fulfillment_instruction,
            "status": AgentStatus.SUCCESS.value,
        }
