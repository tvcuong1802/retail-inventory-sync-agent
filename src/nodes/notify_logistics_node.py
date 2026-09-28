"""AgentCore Platform v1.0"""

# Outer post_process node — Step 7 (NotifyLogisticsNode) of the Engineer
# Review workflow. Notifies logistics of the fulfillment instruction and
# assembles the final terminal-state output (ORDER_ROUTED / HITL_ESCALATION /
# FAILED — Engineer Review §4).

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.services.fulfillment_service import notify_logistics


class NotifyLogisticsNode(FunctionNode):
    """Notify logistics; assemble the final ORDER_ROUTED/HITL_ESCALATION/FAILED status."""

    # S-1 (the framework contract): outer boundary node — matches agent.yaml required_trust_level.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        fulfillment_instruction = state.get("fulfillment_instruction", {})
        hitl_review_outcome = state.get("hitl_review_outcome", "auto_approved")

        if not fulfillment_instruction:
            emit_trace_event("logistics_notify_skipped", {"reason": "no fulfillment_instruction"}, state)
            return {
                "notification_sent": False,
                "hitl_escalated": hitl_review_outcome == "rejected",
                "fulfillment_status": "FAILED",
                "status": AgentStatus.SUCCESS.value,
            }

        notification_sent = notify_logistics(fulfillment_instruction)
        hitl_escalated = hitl_review_outcome == "rejected"

        if fulfillment_instruction.get("action") != "ship":
            fulfillment_status = "HITL_ESCALATION" if hitl_escalated else "FAILED"
        else:
            fulfillment_status = "ORDER_ROUTED"

        emit_trace_event(
            "logistics_notified",
            {"notification_sent": notification_sent, "fulfillment_status": fulfillment_status},
            state,
        )

        return {
            "notification_sent": notification_sent,
            "hitl_escalated": hitl_escalated,
            "fulfillment_status": fulfillment_status,
            "formatted_output": (f"order_id={fulfillment_instruction.get('order_id')} status={fulfillment_status}"),
            "status": AgentStatus.SUCCESS.value,
        }
