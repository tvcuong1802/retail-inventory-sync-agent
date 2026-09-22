"""AgentCore Platform v1.0"""

# Inner subgraph node — Step 3 (FulfillmentPolicyNode) of the Engineer Review
# workflow. Applies config/fulfillment_policy.yaml deterministically (a config
# tool, NOT VectorRAG — Engineer Review §2-4 corrected finding).

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.services.fulfillment_service import apply_fulfillment_policy


class FulfillmentPolicyNode(FunctionNode):
    """Apply the deterministic fulfillment routing + HITL-threshold policy."""

    # S-1: inner subgraph node — trust already authenticated at the outer backbone.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def __init__(self, policy_config: dict[str, Any] | None = None) -> None:
        self._policy_config = policy_config or {}

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        validated_order = state.get("validated_order", {})
        inventory_snapshot = state.get("inventory_snapshot", {})

        if not validated_order:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["FulfillmentPolicyNode: no validated_order in state"],
            }

        policy_decision = apply_fulfillment_policy(self._policy_config, validated_order, inventory_snapshot)

        emit_trace_event(
            "fulfillment_policy_applied",
            {"requires_hitl": policy_decision["requires_hitl"]},
            state,
        )

        return {
            "policy_decision": policy_decision,
            "status": AgentStatus.SUCCESS.value,
        }
