"""AgentCore Platform v1.0"""

# Inner subgraph node — Step 2 (InventoryCheckNode) of the Engineer Review
# workflow. Runs inside FulfillmentWorkflowGraph (src/graph/fulfillment_workflow_graph.py).
# Inner graph only receives user_input (string) + ctx — no outer state — so
# this is also the entry node: it JSON-decodes validated_order from user_input.

import json
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.services.fulfillment_service import aggregate_inventory


class InventoryCheckNode(FunctionNode):
    """Aggregate real-time inventory across EC / POS / WMS for the order items."""

    # S-1: inner subgraph node — trust already authenticated at the outer backbone.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        raw = state.get("user_input", "")
        try:
            validated_order = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            validated_order = None

        if not isinstance(validated_order, dict) or not validated_order.get("items"):
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["InventoryCheckNode: validated_order payload malformed or has no items"],
            }

        inventory_snapshot = aggregate_inventory(validated_order["items"])

        emit_trace_event(
            "inventory_checked",
            {"order_id": validated_order.get("order_id"), "sku_count": len(inventory_snapshot)},
            state,
        )

        return {
            "validated_order": validated_order,
            "inventory_snapshot": inventory_snapshot,
            "status": AgentStatus.SUCCESS.value,
        }
