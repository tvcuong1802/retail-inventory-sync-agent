"""Reading an order out of a sentence — the shape the Marketplace actually delivers.

Every assertion here comes from something measured against the real model on 2026-09-14,
or from a mutant that survived the rest of the suite.
"""

import pytest

from src.nodes.order_ingest_node import (
    _canonical_order_id,
    _merge_model_fields,
    _order_from_text,
    OrderIngestNode,
)
from src.services.fulfillment_service import aggregate_inventory, validate_order_payload


class TestReadingTheSentence:
    def test_a_whole_order_written_as_prose_is_read(self) -> None:
        order = _order_from_text("注文 EC-100231（SKU-001 を2点、大阪府宛、ECチャネル）")
        assert validate_order_payload(order)[0]
        assert order["order_id"] == "EC-100231"
        assert order["items"] == [{"sku": "SKU-001", "qty": 2}]
        assert order["delivery_address"] == {"region": "大阪府"}

    def test_only_the_region_is_ever_taken_from_an_address(self) -> None:
        """The narrowest read that satisfies the policy is also the one that cannot leak.
        A street-level address is never extracted, so it can never be stored."""
        order = _order_from_text("大阪府大阪市北区梅田1-2-3 宛、注文 EC-100231、SKU-001 を1点")
        assert order["delivery_address"] == {"region": "大阪府"}
        assert "梅田" not in str(order)

    @pytest.mark.parametrize(
        "message,expected",
        [
            ("ネットショップからのご注文", "ec"),
            ("店頭でのご購入", "store"),
            ("オンラインで注文しました", "ec"),
            ("注文 EC-100231 について", None),
        ],
    )
    def test_the_channel_is_read_from_channel_WORDS_not_from_the_order_id(
        self, message: str, expected: str | None
    ) -> None:
        """"ec" is a substring of the order id "EC-100231". An unanchored match read a
        channel out of the order NUMBER and looked like it had understood the sentence."""
        assert _order_from_text(message).get("channel") == expected


class TestWhatTheModelIsAllowedToAdd:
    def test_the_model_never_overwrites_what_the_pattern_read(self) -> None:
        """Measured against the real model 2026-09-14: asked about this order it returned
        `items` as the STRING "['SKU-001']". A blind merge put that over the correctly
        parsed list, and the stock lookup would then have iterated its characters."""
        read = {"items": [{"sku": "SKU-001", "qty": 2}], "quantity": 2}
        merged = _merge_model_fields(read, {"items": "['SKU-001']", "quantity": 99})
        assert merged["items"] == [{"sku": "SKU-001", "qty": 2}]
        assert merged["quantity"] == 2

    @pytest.mark.parametrize(
        "field,value",
        [
            ("order_id", "not an order number"),
            ("channel", "carrier-pigeon"),
            ("quantity", "two"),
            ("quantity", -1),
            ("items", "SKU-001"),
        ],
    )
    def test_a_value_of_the_wrong_shape_is_dropped_not_coerced(self, field: str, value: object) -> None:
        """The envelope stays incomplete and the sender is asked, which is recoverable.
        A silently coerced value is not."""
        assert field not in _merge_model_fields({}, {field: value})

    def test_an_order_number_written_with_a_space_is_canonicalised(self) -> None:
        """A person writes "EC 100231" and the model repeats it that way. Normalising the
        SEPARATOR is not a reading -- the result still has to match the order-number
        pattern. Without it a complete order was answered with "tell me the order number",
        which the sender had just given."""
        assert _canonical_order_id("EC 100231") == "EC-100231"
        assert _merge_model_fields({}, {"order_id": "EC 100231"})["order_id"] == "EC-100231"
        # and a separator fix cannot rescue something that is not an order number
        assert "order_id" not in _merge_model_fields({}, {"order_id": "the usual one"})


class TestTheStockLookupAcceptsHowPeopleWrite:
    def test_a_bare_sku_string_does_not_crash_the_stock_lookup(self) -> None:
        """It raised AttributeError out of aggregate_inventory -- an unhandled crash, not
        an answer -- for the item shape a person is most likely to send."""
        snapshot = aggregate_inventory(["SKU-001"])
        assert "SKU-001" in snapshot
        assert snapshot["SKU-001"]["qty_needed"] == 1

    def test_the_dict_shape_still_carries_its_quantity(self) -> None:
        snapshot = aggregate_inventory([{"sku": "SKU-001", "qty": 4}])
        assert snapshot["SKU-001"]["qty_needed"] == 4


class TestTheSenderIsAnswered:
    def test_a_message_with_no_order_is_told_what_is_missing(self) -> None:
        out = OrderIngestNode().execute({"user_input": "いつ届きますか"})
        assert out["status"] == "success"
        assert out["input_unusable"] is True
        assert "order_id" in out["formatted_output"]

    def test_a_pattern_only_read_says_so(self) -> None:
        """The sender should check an order this agent assembled from their prose before
        acting on it; an order they sent as JSON needs no such warning."""
        out = OrderIngestNode().execute({"user_input": "注文 EC-100231（SKU-001 を2点、大阪府宛、EC）"})
        assert out["drafting_degraded"] == "pattern_only"
