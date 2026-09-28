# RET-C2-267 — Unit Tests: src/services/fulfillment_service.py (pure functions)

from src.services.fulfillment_service import (
    aggregate_inventory,
    apply_fulfillment_policy,
    build_fulfillment_instruction,
    notify_logistics,
    region_from_address,
    select_route,
    validate_order_payload,
)

POLICY_CONFIG = {
    "routing": {"channel_priority": ["WMS", "POS", "EC"]},
    "hitl": {"amount_threshold_jpy": 500000, "volume_threshold_units": 100},
}


def test_validate_order_payload_complete():
    ok, missing = validate_order_payload(
        {"order_id": "O1", "channel": "EC", "items": [{}], "quantity": 1, "delivery_address": "Tokyo"}
    )
    assert ok is True
    assert missing == []


def test_validate_order_payload_missing_fields():
    ok, missing = validate_order_payload({"order_id": "O1"})
    assert ok is False
    assert "channel" in missing


def test_region_from_address_dict():
    assert region_from_address({"region": "Osaka", "street": "1-1-1"}) == "Osaka"


def test_region_from_address_string():
    assert region_from_address("Tokyo, Shibuya, 1-2-3") == "Tokyo"


def test_region_from_address_unknown():
    assert region_from_address(None) == "UNKNOWN_REGION"


def test_aggregate_inventory_fixed_ceiling():
    snapshot = aggregate_inventory([{"sku": "SKU-1", "qty": 5}])
    assert snapshot["SKU-1"]["channel_stock"] == {"EC": 10, "POS": 20, "WMS": 50}


def test_apply_fulfillment_policy_below_threshold():
    order = {"items": [{"qty": 2, "unit_price": 1000}], "quantity": 2}
    decision = apply_fulfillment_policy(POLICY_CONFIG, order, {})
    assert decision["requires_hitl"] is False


def test_apply_fulfillment_policy_above_amount_threshold():
    order = {"items": [{"qty": 5, "unit_price": 600000}], "quantity": 5}
    decision = apply_fulfillment_policy(POLICY_CONFIG, order, {})
    assert decision["requires_hitl"] is True


def test_apply_fulfillment_policy_above_volume_threshold():
    order = {"items": [{"qty": 150, "unit_price": 1}], "quantity": 150}
    decision = apply_fulfillment_policy(POLICY_CONFIG, order, {})
    assert decision["requires_hitl"] is True


def test_select_route_picks_priority_channel():
    snapshot = {"SKU-1": {"qty_needed": 15, "channel_stock": {"WMS": 50, "POS": 20, "EC": 10}}}
    route = select_route(snapshot, {"channel_priority": ["WMS", "POS", "EC"]})
    assert route["source_channel"] == "WMS"
    assert route["fulfillable"] is True


def test_select_route_no_stock():
    snapshot = {"SKU-1": {"qty_needed": 999, "channel_stock": {"WMS": 50, "POS": 20, "EC": 10}}}
    route = select_route(snapshot, {"channel_priority": ["WMS", "POS", "EC"]})
    assert route["fulfillable"] is False


def test_build_fulfillment_instruction_ships_when_fulfillable_and_approved():
    instr = build_fulfillment_instruction({"order_id": "O1"}, {"fulfillable": True, "source_channel": "WMS"}, "auto_approved")
    assert instr["action"] == "ship"


def test_build_fulfillment_instruction_holds_when_rejected():
    instr = build_fulfillment_instruction({"order_id": "O1"}, {"fulfillable": True, "source_channel": "WMS"}, "rejected")
    assert instr["action"] == "hold"


def test_notify_logistics_true_with_order_id():
    assert notify_logistics({"order_id": "O1", "action": "ship"}) is True


def test_notify_logistics_false_without_order_id():
    assert notify_logistics({"action": "hold"}) is False
