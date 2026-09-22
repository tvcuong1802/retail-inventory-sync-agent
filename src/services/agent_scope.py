"""What this agent is for, in the reader's own words, and what it must not stand in for."""

SUPPORTED_LANGUAGES = ("ja", "en")
DEFAULT_LANGUAGE = "ja"

# The decision this output must NOT be allowed to replace. "AI-generated draft" is true of
# every template in the fleet and tells a reader nothing.
SCOPE_EN = (
    "Which location the fulfillment policy selects for one order, given the stock figures "
    "the connected systems returned at the moment it ran. It does not reserve the stock, "
    "does not dispatch anything, and does not confirm a delivery date. Nothing moves until "
    "the logistics system accepts the instruction."
)

SCOPE_JA = (
    "一件のご注文について、照会時点で各システムが返した在庫数にもとづき、出荷ポリシーが"
    "選定した出荷元をお示しするものです。在庫の引き当ても、出荷の実行も行わず、お届け日を"
    "確約するものでもありません。物流システムが指示を受け付けるまで、実際には何も動きません。"
)

# Shown when the caller sends something this agent cannot work with. Bilingual on purpose:
# this is the path where the reader's language is least knowable.
PACKET_GUIDANCE = """## ご注文の内容をJSON形式でお送りください

出荷元の選定には、注文番号・チャネル・商品・数量が必要です。

```json
{"order_id": "EC-100231", "channel": "ec", "quantity": 2,
 "items": [{"sku": "SKU-001", "qty": 2}],
 "delivery_address": {"prefecture": "大阪府"}}
```

お届け先は**都道府県までしか保持しません**。番地までお送りいただいても記録には残りません。

---

## Send the order as JSON

Choosing a fulfillment location needs the order id, the channel, the items and the quantity.
Use the shape above.

The delivery address is reduced to its region and **the street-level address is never
stored** — send it or not, it does not end up in the record.
"""

# What the answer says when the reading step could not run. The reader is told which
# judgement was NOT made -- never which provider or secret was missing.
DEGRADED_NOTICE_EN = (
    "**The order below was read out of your message by pattern alone; the sentence itself "
    "was not interpreted.** Check the order id and the quantity before acting on this."
)

DEGRADED_NOTICE_JA = (
    "**以下のご注文内容は、文章のパターンのみから読み取ったものです。文意の解釈は行って"
    "いません。** 実行前に、注文番号と数量をご確認ください。"
)

# The refusal body for an input this agent will not process. Separate from the guidance:
# guidance says "send this instead"; a refusal says "this was not accepted, and why".
REFUSAL_JA = (
    "## ご依頼を受け付けられませんでした\n\n入力に、認証情報や個人を特定できる記述に見える"
    "内容が含まれていました。該当箇所を取り除いて、再度お送りください。"
)

REFUSAL_EN = (
    "## The request was not accepted\n\nIt carried something shaped like a credential or "
    "personal data. Remove it and send the order again."
)

# Read by src/services/input_intake.py. Without it the shared helper runs on fleet
# defaults -- it still answers, so nothing looks broken; it just reads every message with
# no idea what this agent does.
INTAKE_POLICY = {
    "languages": SUPPORTED_LANGUAGES,
    "default_language": DEFAULT_LANGUAGE,
    "capabilities": (
        "aggregate stock for an order across the EC platform, store POS and the warehouse, "
        "and select a fulfillment location by the configured policy",
        "hold an order above the configured amount or volume for human review",
        "hand the resulting instruction to the logistics system",
    ),
    # Every field OrderIngestNode merges. Declaring only some of them silently filtered
    # the rest out of the intake result, so the model could never complete an envelope and
    # the fallback looked dead. Each one IS consumed, and only when the deterministic pass
    # left the envelope incomplete.
    # `None` means "any value"; a tuple is the CLOSED SET the value must be a member of --
    # input_intake discards anything outside it. Measured 2026-09-14: given a free-text
    # hint instead, the helper iterated the hint's CHARACTERS as the allowed set and every
    # field came back empty. `channel` is the one field with a closed set here.
    "fields": {
        "order_id": None,
        "channel": ("ec", "store"),
        "items": None,
        "quantity": None,
    },
    "examples": (
        # Near-miss first: "close, but not ours" is what a generic instruction cannot
        # convey, and it is the message people actually send.
        {
            "message": "EC-100231はいつ届きますか。",
            # why: asks for a delivery date; this agent selects where an order ships FROM and commits to no
            #   date
            "expect": {"language": "ja", "fields": {}, "fits": "unsure", "suggestion": None},
        },
        {
            "message": "注文 EC-100231（SKU-001 を2点、大阪府宛、ECチャネル）の出荷元を決めてください。",
            # why: carries the order id, channel, item and quantity in a sentence
            "expect": {"language": "ja", "fields": {}, "fits": "yes", "suggestion": None},
        },
        {
            "message": "明日の天気を教えてください。",
            # why: nothing to do with an order or with fulfillment
            "expect": {"language": "ja", "fields": {}, "fits": "no", "suggestion": None},
        },
    ),
}
