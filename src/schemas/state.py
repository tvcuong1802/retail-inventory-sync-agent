"""AgentCore Platform v1.0"""

# ADR-005: State must be a flat TypedDict — never Pydantic BaseModel.
# LangGraph checkpoints use msgpack serialization; Pydantic objects
# cause silent corruption. Extend AgentState with agent-specific
# fields only. Do NOT add credentials, secrets, or Pydantic models.

from typing import Any, NotRequired

from framework.schemas.agent_state import AgentState


class State(AgentState):
    """RET-C2-267 Omnichannel Inventory Sync & Fulfillment Orchestration state.

    All shared fields (user_input, validated_input, status, session_id,
    node_history, error_log, hitl_*, etc.) are inherited from AgentState.
    """

    # Set by outer pre_process (OrderIngestNode) — validated order + region-only
    # delivery address (S-2: never store the full street-level address).
    validated_order: NotRequired[dict[str, Any]]
    delivery_region: NotRequired[str]

    # Set by inner subgraph (via GraphNode.merge_output) — one artifact per step.
    inventory_snapshot: NotRequired[dict[str, Any]]
    policy_decision: NotRequired[dict[str, Any]]
    selected_route: NotRequired[dict[str, Any]]
    hitl_review_outcome: NotRequired[str]
    fulfillment_instruction: NotRequired[dict[str, Any]]

    # Set by outer post_process (NotifyLogisticsNode) — final terminal-state output.
    notification_sent: NotRequired[bool]
    hitl_escalated: NotRequired[bool]
    fulfillment_status: NotRequired[str]  # ORDER_ROUTED | HITL_ESCALATION | FAILED
    # Declared because LangGraph merges only fields the schema names: a node can return a
    # key, read it back as missing one step later, and the branch that depended on it
    # never runs. The symptom is silence, not an error.
    answer_language: NotRequired[str]
    input_unusable: NotRequired[bool]
    result: NotRequired[str]
    drafting_degraded: NotRequired[str]
