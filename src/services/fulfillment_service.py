"""AgentCore Platform v1.0"""

# Service layer: deterministic domain logic for omnichannel inventory sync and
# fulfillment routing. Pure functions only — no agenticstar imports, no side
# effects, no credentials. Nodes call this; EC/POS/WMS integration is injected
# at node construction time (per-retailer, Engineer Review §10 dependency #1).

from __future__ import annotations

from typing import Any

REQUIRED_ORDER_FIELDS = ("order_id", "channel", "items", "quantity", "delivery_address")


def validate_order_payload(payload: dict[str, Any]) -> tuple[bool, list[str]]:
    """Check the inbound order envelope has every required field."""
    missing = [f for f in REQUIRED_ORDER_FIELDS if not payload.get(f)]
    return (not missing, missing)


def region_from_address(delivery_address: Any) -> str:
    """S-2: reduce a delivery address to a region-only string.

    Never persist the full street-level address in State — only the region
    (prefecture/city or an equivalent top-level administrative unit) is kept.
    """
    if isinstance(delivery_address, dict):
        region = delivery_address.get("region") or delivery_address.get("prefecture") or delivery_address.get("city")
        if region:
            return str(region)
        return "UNKNOWN_REGION"
    if isinstance(delivery_address, str) and delivery_address.strip():
        # Free-text address: take the first comma-separated segment as the
        # region-level token (illustrative default — real deployments should
        # inject a proper address-parsing service, Engineer Review dependency #1).
        return delivery_address.split(",")[0].strip() or "UNKNOWN_REGION"
    return "UNKNOWN_REGION"


# Deterministic simulated per-channel stock ceiling (the real EC-platform/POS/WMS
# API call is injected upstream via constructor-injected clients in a real
# deployment; this fixed table keeps local/unit behavior fully reproducible).
_CHANNEL_BASE_STOCK = {"WMS": 50, "POS": 20, "EC": 10}


def aggregate_inventory(
    items: list[dict[str, Any]], channels: tuple[str, ...] = ("EC", "POS", "WMS")
) -> dict[str, Any]:
    """Aggregate real-time stock across EC / POS / WMS channels for each item.

    Deterministic simulated lookup — every channel has a fixed stock ceiling
    (`_CHANNEL_BASE_STOCK`); a channel can fulfill an item only if its ceiling
    is >= the requested quantity. This aggregates a per-channel stock snapshot
    per item so downstream nodes can pick a source (or fail closed when no
    channel has sufficient stock).
    """
    snapshot: dict[str, Any] = {}
    for item in items:
        # A bare SKU string is how a person writes an order line, and it used to raise
        # AttributeError out of this function -- an unhandled crash rather than an answer.
        # Both shapes are accepted; the quantity defaults to 1 exactly as it does for a
        # dict that omits it.
        if isinstance(item, str):
            item = {"sku": item}
        if not isinstance(item, dict):
            continue
        sku = str(item.get("sku") or item.get("item_id") or "UNKNOWN_SKU")
        qty_needed = int(item.get("qty", item.get("quantity", 1)) or 1)
        per_channel = {channel: _CHANNEL_BASE_STOCK.get(channel, 10) for channel in channels}
        snapshot[sku] = {"qty_needed": qty_needed, "channel_stock": per_channel}
    return snapshot


def apply_fulfillment_policy(
    policy_config: dict[str, Any], validated_order: dict[str, Any], inventory_snapshot: dict[str, Any]
) -> dict[str, Any]:
    """Apply the deterministic routing + HITL-threshold policy (config/fulfillment_policy.yaml)."""
    routing = policy_config.get("routing", {}) if isinstance(policy_config, dict) else {}
    hitl_cfg = policy_config.get("hitl", {}) if isinstance(policy_config, dict) else {}

    channel_priority = routing.get("channel_priority") or ["WMS", "POS", "EC"]
    amount_threshold = hitl_cfg.get("amount_threshold_jpy", 500_000)
    volume_threshold = hitl_cfg.get("volume_threshold_units", 100)

    items = validated_order.get("items", [])
    total_amount = sum(float(i.get("unit_price", 0)) * float(i.get("qty", 1)) for i in items)
    total_volume = sum(float(i.get("qty", 1)) for i in items) or float(validated_order.get("quantity", 0) or 0)

    requires_hitl = total_amount >= amount_threshold or total_volume >= volume_threshold

    return {
        "channel_priority": channel_priority,
        "requires_hitl": requires_hitl,
        "total_amount": total_amount,
        "total_volume": total_volume,
        "amount_threshold_jpy": amount_threshold,
        "volume_threshold_units": volume_threshold,
    }


def select_route(inventory_snapshot: dict[str, Any], policy_decision: dict[str, Any]) -> dict[str, Any]:
    """Pick the optimal fulfillment source location per the channel-priority policy."""
    channel_priority = policy_decision.get("channel_priority", ["WMS", "POS", "EC"])

    for sku, info in inventory_snapshot.items():
        needed = info.get("qty_needed", 1)
        channel_stock = info.get("channel_stock", {})
        for channel in channel_priority:
            if channel_stock.get(channel, 0) >= needed:
                return {
                    "source_channel": channel,
                    "sku": sku,
                    "fulfillable": True,
                }

    return {"source_channel": None, "sku": None, "fulfillable": False, "reason": "no channel has sufficient stock"}


def build_fulfillment_instruction(
    validated_order: dict[str, Any], selected_route: dict[str, Any], hitl_review_outcome: str
) -> dict[str, Any]:
    """Build the fulfillment instruction for logistics (Engineer Review §4 Step 6)."""
    proceed = selected_route.get("fulfillable", False) and hitl_review_outcome not in ("rejected",)
    return {
        "order_id": validated_order.get("order_id"),
        "source_channel": selected_route.get("source_channel"),
        "action": "ship" if proceed else "hold",
        "hitl_review_outcome": hitl_review_outcome,
    }


def notify_logistics(fulfillment_instruction: dict[str, Any]) -> bool:
    """Notify the logistics system of the fulfillment instruction (simulated).

    The real logistics-notification API call is injected at node construction
    time; this always signals a successful dispatch for both "ship" and
    "hold" actions (logistics must be informed either way).
    """
    return bool(fulfillment_instruction.get("order_id"))
