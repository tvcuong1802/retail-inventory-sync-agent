"""AgentCore Platform v1.0"""

# Outer pre_process node — Step 1 (OrderIngestNode) of the Engineer Review
# workflow. Validates the inbound order envelope and reduces the delivery
# address to a region-only string (S-2) before it ever enters State.
# Serializes validated_order (JSON string) for the inner fulfillment subgraph.

import json
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.services.fulfillment_service import region_from_address, validate_order_payload

import re

from src.services.agent_scope import INTAKE_POLICY, PACKET_GUIDANCE
from src.services.caller_packet import caller_packet
from src.services.input_intake import understand_input
from src.services.llm_provider import build_llm_client

#: The structured fields a caller may supply through `input_context`. The Marketplace
#: runner types the message as a STRING and seeds `input_context` with
#: `conversation_history` alone, so this is the OTHER entry point, not the main one.
PACKET_FIELDS = ("order_id", "channel", "items", "quantity")

#: An order id and a quantity are PATTERNS, not intent -- there is nothing here a model
#: does better, and reading them deterministically costs no call on the common path.
_ORDER_ID_RE = re.compile(r"\b([A-Z]{2,4}-\d{4,10})\b")
_QUANTITY_RE = re.compile(r"(\d+)\s*(?:点|個|pcs?\b|units?\b)", re.IGNORECASE)
_SKU_RE = re.compile(r"\b(SKU-[A-Z0-9-]+)\b", re.IGNORECASE)
#: How people actually name the two channels. Measured against the real model 2026-09-14:
#: even with the closed set ("ec", "store") declared in INTAKE_POLICY, it did not map
#: 「ネットショップからのご注文」 to a channel code -- so the vocabulary lives here, where it
#: is deterministic and testable, and the model only ever ADDS what this misses.
_CHANNELS = {
    "ec": "ec",
    "オンライン": "ec",
    "ネットショップ": "ec",
    "ネット注文": "ec",
    "通販": "ec",
    "webshop": "ec",
    "web": "ec",
    "online": "ec",
    "mail order": "ec",
    "store": "store",
    "店舗": "store",
    "店頭": "store",
    "実店舗": "store",
    "在庫店": "store",
    "in-store": "store",
}

#: Only the REGION is ever wanted, so only the region is looked for. A street-level address
#: is never extracted, never stored, and never asked for -- the narrowest read that
#: satisfies the policy is also the one that cannot leak.
_REGION_RE = re.compile(r"([\u4e00-\u9fff]{2,3}[都道府県])")


def _order_from_text(message: str) -> dict[str, Any]:
    """Whatever of the order is written plainly in the message. Never a guess."""
    order: dict[str, Any] = {}
    found = _ORDER_ID_RE.search(message or "")
    if found:
        order["order_id"] = found.group(1)
    qty = _QUANTITY_RE.search(message or "")
    if qty:
        order["quantity"] = int(qty.group(1))
    skus = _SKU_RE.findall(message or "")
    if skus:
        # The shape the inventory lookup consumes. A bare string works too now, but
        # emitting the canonical shape here keeps one representation in the record.
        qty_each = int(qty.group(1)) if qty else 1
        order["items"] = [{"sku": s.upper(), "qty": qty_each} for s in skus]
    region = _REGION_RE.search(message or "")
    if region:
        order["delivery_address"] = {"region": region.group(1)}
    # Word-anchored: "ec" is a substring of the order id "EC-100231", so an unanchored
    # match read a channel out of the order number and looked like it had understood the
    # sentence. Japanese tokens carry no word boundary, so they are matched as written.
    lowered = (message or "").lower()
    for token, channel in _CHANNELS.items():
        low = token.lower()
        hit = re.search(rf"(?<![a-z0-9-]){re.escape(low)}(?![a-z0-9-])", lowered) if low.isascii() else (low in lowered)
        if hit:
            order["channel"] = channel
            break
    return order


def _merge_model_fields(read: dict[str, Any], proposed: Any) -> dict[str, Any]:
    """Add what the model read, and ONLY what the deterministic pass did not already read.

    Two rules, each from a measured failure:

    * The model never OVERWRITES a field. Measured against the real model 2026-09-14: asked
      about an order it returned `items` as the string ``"['SKU-001']"`` -- a blind merge
      put that over the correctly parsed list, and the stock lookup would then have
      iterated its characters as SKUs.
    * Every value is checked for SHAPE before it is accepted. A field of the wrong type is
      dropped, not coerced: the envelope stays incomplete and the sender is asked, which is
      recoverable, where a silently coerced value is not.
    """
    merged = dict(read)
    if not isinstance(proposed, dict):
        return merged
    for key, value in proposed.items():
        if key not in _MODEL_FIELD_SHAPES or key in merged or value in (None, ""):
            continue
        if _MODEL_FIELD_SHAPES[key](value):
            merged[key] = _MODEL_FIELD_NORMALISERS.get(key, lambda v: v)(value)
    return merged


#: The shape each field must already have. Nothing is coerced into shape -- a wrong type is
#: dropped and the sender is asked for it.
_MODEL_FIELD_SHAPES: dict[str, Any] = {
    # A person writes "EC 100231" and the model repeats it that way. Canonicalising the
    # SEPARATOR is a format normalisation, not a reading: the result still has to match the
    # order-number pattern, so nothing unverifiable gets through. Measured against the real
    # model 2026-09-14 -- without this the value was discarded and a complete order was
    # answered with "tell me the order number", which the sender had just given.
    "order_id": lambda v: isinstance(v, str) and bool(_ORDER_ID_RE.search(_canonical_order_id(v))),
    "channel": lambda v: isinstance(v, str) and v.strip().lower() in {"ec", "store"},
    "quantity": lambda v: isinstance(v, int) and v > 0,
    "items": lambda v: isinstance(v, list) and all(isinstance(i, (str, dict)) for i in v) and bool(v),
}


def _canonical_order_id(value: str) -> str:
    """ "EC 100231" / "ec_100231" -> "EC-100231". Separator only; never invents digits."""
    return re.sub(r"[\s_]+", "-", str(value).strip()).upper()


_MODEL_FIELD_NORMALISERS: dict[str, Any] = {
    "order_id": _canonical_order_id,
    "channel": lambda v: str(v).strip().lower(),
    "items": lambda v: [{"sku": str(i).upper()} if isinstance(i, str) else i for i in v],
}


def _guidance(language: str, missing: list[str] | None = None) -> dict[str, Any]:
    """SUCCESS with the sentence that says what to send.

    The Marketplace runner raises on every status but SUCCESS, so an ERROR here is shown as
    "agent failed" -- and this agent cannot look an order up on its own, so the sentence
    saying what the order envelope needs IS the value of this path.
    """
    body = PACKET_GUIDANCE
    if missing:
        body = f"**Missing from the order: {', '.join(str(m) for m in missing)}.**\n\n{body}"
    return {
        "input_unusable": True,
        "answer_language": language,
        "formatted_output": body,
        "result": body,
        "status": AgentStatus.SUCCESS.value,
    }


def _script_language(text: str) -> str | None:
    """ "ja" for kana/kanji, "en" for Latin words, None when the text carries neither."""
    japanese = sum(1 for ch in text or "" if "\u3040" <= ch <= "\u30ff" or "\u4e00" <= ch <= "\u9fff")
    latin = sum(len(w) for w in re.findall(r"[A-Za-z][A-Za-z']*", text or "") if 2 <= len(w) <= 20)
    if japanese and japanese * 2 >= latin:
        return "ja"
    return "en" if latin else None


class OrderIngestNode(FunctionNode):
    """Validate the inbound order; region-only delivery address (S-2)."""

    # S-1 (the framework contract): outer boundary node — matches agent.yaml required_trust_level.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__()
        # Settings only (max_tokens, temperature, timeout) -- never a client.
        self._config = config or {}

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        user_input = state.get("user_input", "")
        message = user_input if isinstance(user_input, str) else ""
        language = _script_language(message) or ""
        drafting_degraded = ""

        try:
            payload = json.loads(user_input) if isinstance(user_input, str) else user_input
        except (TypeError, ValueError):
            payload = None

        if not isinstance(payload, dict):
            packet = caller_packet(state, PACKET_FIELDS)
            if isinstance(packet, dict) and packet.get("order_id"):
                payload = packet

        if not isinstance(payload, dict) and message.strip():
            # The message is a sentence, which is what the Marketplace runner delivers.
            # Read the order out of it: deterministically first (an order id and a quantity
            # are patterns, not intent), then with the model for the rest. Whatever comes
            # back still has to carry every required field -- the deterministic half of the
            # two-signal rule -- or it is discarded and the sender gets the guidance.
            payload = _order_from_text(message)
            drafting_degraded = "pattern_only"
            if not validate_order_payload(payload)[0]:
                proposed, language = self._read_message(message, state, language)
                merged = _merge_model_fields(payload, proposed)
                if validate_order_payload(merged)[0]:
                    payload = merged
                    drafting_degraded = ""

        if not isinstance(payload, dict):
            emit_trace_event("order_ingest_rejected", {"reason": "malformed payload"}, state)
            return _guidance(language)

        is_valid, missing = validate_order_payload(payload)
        if not is_valid:
            emit_trace_event("order_ingest_rejected", {"reason": "missing fields", "missing": missing}, state)
            return _guidance(language, missing=missing)

        # S-2: region-only — the full delivery_address is used here only to
        # derive the region, then discarded (never stored in State).
        delivery_region = region_from_address(payload.get("delivery_address"))

        validated_order = {
            "order_id": payload["order_id"],
            "channel": payload["channel"],
            "items": payload["items"],
            "quantity": payload["quantity"],
        }

        emit_trace_event(
            "order_ingested",
            {"order_id": validated_order["order_id"], "channel": validated_order["channel"]},
            state,
        )

        return {
            "validated_order": validated_order,
            "answer_language": language,
            "drafting_degraded": drafting_degraded,
            "delivery_region": delivery_region,
            "validated_input": json.dumps(validated_order, ensure_ascii=False),
            "status": AgentStatus.SUCCESS.value,
        }

    def _read_message(self, message: str, state: dict[str, Any], language: str) -> tuple[dict[str, Any], str]:
        """(order fields the model read, language). Both from ONE reading of the sentence.

        Splitting language and extraction into two calls would double the latency of every
        request that reaches here, for no information a single reading does not carry.
        """
        intake = understand_input(
            message,
            build_llm_client(dict(state), self._config.get("llm")),
            policy=INTAKE_POLICY,
            script_language=_script_language,
        )
        decided = "" if intake.get("language_source") == "default" else str(intake.get("answer_language") or "")
        raw = intake.get("fields")
        fields = raw if isinstance(raw, dict) else {}
        return {k: v for k, v in fields.items() if v not in (None, "")}, (decided or language)
