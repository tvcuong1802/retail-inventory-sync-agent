# Template Design Specification — RET-C2-267

## Position in AgentCore Architecture

- **Agent Class**: `FulfillmentOrchestrationGraph`
- **L1 Base**: AgentBaseGraph (outer) — Cat 2, no autonomous loop, no `AutonomousBaseGraph`
- **Three-Layer Separation**:
  - State: flat TypedDict composition (no Pydantic — msgpack incompatible), `src/schemas/state.py`
  - Node: L1 inheritance (Template Method: `execute(self, state: dict) -> dict` override only)
  - Graph: composition (outer `AgentBaseGraph` + `GraphNode` in `main` wrapping an inner `BaseGraph`)

## Architecture Overview — Cat 2 (outer + inner subgraph)

Per CoE 2026-06-17 mandate (the Cat-2 composition pattern), this template does **not** flatten the
7-step workflow into a single `MainNode`. Instead:

```
OUTER (AgentBaseGraph — src/graph/graph.py):
  initialize → pre_process(OrderIngest) → main(GraphNode) → post_process(NotifyLogistics) → finalize
                                              │ get_subgraph().invoke(validated_input, ctx)
                                              ▼
INNER (BaseGraph — src/graph/fulfillment_workflow_graph.py):
  START → inventory_check → fulfillment_policy → route_select → hitl_gate (D6 interrupt())
        → fulfillment_instruct → END
```

### Node Configuration

| Node | Slot | Responsibility | Input State | Output State | Inherits/Overrides |
|------|------|-----------------|-------------|--------------|---------------------|
| initialize | outer | schema_version, session_id, trust_level | — | — | InitializeNode (default) |
| OrderIngestNode | outer pre_process | Validate order envelope; S-2 region-only delivery address; serialize `validated_input` | `user_input` | `validated_order`, `delivery_region`, `validated_input` | FunctionNode |
| FulfillmentOrchestrationGraphNode | outer main | Wraps the inner subgraph; propagates the D6 HITL interrupt as `AWAITING_HUMAN` | `validated_input` | merged inner fields (`selected_route`, `fulfillment_instruction`, `hitl_review_outcome`, ...) | GraphNode |
| InventoryCheckNode | inner (entry) | Aggregate real-time inventory across EC/POS/WMS | `user_input` (= validated_order JSON) | `validated_order`, `inventory_snapshot` | FunctionNode |
| FulfillmentPolicyNode | inner | Apply `config/fulfillment_policy.yaml` deterministically (routing priority + HITL thresholds) | `validated_order`, `inventory_snapshot` | `policy_decision` | FunctionNode |
| RouteSelectNode | inner | Select the optimal fulfillment source location | `inventory_snapshot`, `policy_decision` | `selected_route` | FunctionNode |
| HITLGateNode | inner | D6 `interrupt()` when `policy_decision.requires_hitl`; never auto-approve on timeout | `policy_decision`, `selected_route` | `hitl_review_outcome`, `hitl_draft`, `hitl_feedback` | FunctionNode |
| FulfillmentInstructNode | inner | Emit the fulfillment instruction | `validated_order`, `selected_route`, `hitl_review_outcome` | `fulfillment_instruction` | FunctionNode |
| NotifyLogisticsNode | outer post_process | Notify logistics; assemble the final terminal state | merged inner fields | `notification_sent`, `hitl_escalated`, `fulfillment_status` | FunctionNode |
| finalize | outer | response_metadata, total_time_ms | — | — | FinalizeNode (default) |

### Data Flow

```
START → initialize → pre_process → main(GraphNode→inner subgraph) → {route} → post_process → finalize → END
                                            ↓ (retry)
                                          pre_process
```

`GraphNode.execute()` only forwards `validated_input` (a JSON string) to the inner subgraph — the
inner graph does not see outer State directly. `OrderIngestNode` serializes `validated_order` to
`validated_input`; `InventoryCheckNode` (inner entry) `json.loads()`s it back. Config (the
`fulfillment_policy.yaml` policy dict, `memory_enabled`, `hitl`) reaches the inner graph via
`FulfillmentOrchestrationGraphNode._parent_config()`, never via State.

### State Definition

| Field | Type | Purpose | Required |
|-------|------|---------|----------|
| `validated_order` | `dict` | Order envelope after S-2 region-reduction (order_id, channel, items, quantity) | NotRequired |
| `delivery_region` | `str` | Region-only delivery location (S-2 — full address never persisted) | NotRequired |
| `inventory_snapshot` | `dict` | Per-SKU EC/POS/WMS stock snapshot | NotRequired |
| `policy_decision` | `dict` | Channel priority + `requires_hitl` + threshold values | NotRequired |
| `selected_route` | `dict` | Chosen source channel + fulfillable flag | NotRequired |
| `hitl_review_outcome` | `str` | `auto_approved` \| `approved` \| `rejected` | NotRequired |
| `fulfillment_instruction` | `dict` | Instruction payload for logistics | NotRequired |
| `notification_sent` | `bool` | Logistics notification result | NotRequired |
| `hitl_escalated` | `bool` | True when the HITL reviewer rejected the order | NotRequired |
| `fulfillment_status` | `str` | Terminal state: `ORDER_ROUTED` \| `HITL_ESCALATION` \| `FAILED` | NotRequired |

**State Constraints (mandatory):**
- Flat TypedDict only (primitives + JSON-serializable types)
- No JWT, API keys, credentials in State (checkpoint DB leakage)
- InvocationContext via `config["configurable"]` only (not in State)
- No Pydantic models, dataclass, arbitrary Python objects (msgpack incompatible)

## Framework Utilization

### Shared Components Used
- [x] InvocationContext (correlation_id, session_id, permissions, credential handle)
- [x] ConnectionPolicy (retry/timeout strategy — `max_retry`/`timeout_seconds` in `config/agent.yaml`)
- [ ] SecurityViolationError (no domain condition currently raises this; validation failures return
      `AgentStatus.ERROR` dicts instead, per code-contracts.md)
- [ ] S-2: `_extra_security_gate_input()` — no additional domain PII check beyond the default scan;
      the delivery-address region-reduction in `OrderIngestNode.execute()` is the domain control (S-2)
- [ ] S-3: `_extra_security_gate_output()` — no additional domain output check beyond the default
      credential scan; the fulfillment output carries no PII (region-only address, no customer name)
- [x] S-4: `emit_trace_event()` — at least one domain-specific event inside each `execute()`
      (**mandatory**; do NOT emit `node_start` / `node_complete` / `node_error` —
      `BaseNode.__call__()` emits these automatically; duplicates corrupt audit trail)

> **S-2/S-3 gate behaviour by node type (ADR-017):**
> - `FunctionNode` subclass → framework `@final` gate always runs automatically;
>   extend via `_extra_security_gate_input()` / `_extra_security_gate_output()` only
> - `GraphNode` / `RemoteAgentNode` → deliberate no-op (upstream or remote node's gate already applied)
> - Custom `BaseNode` subclass → must implement `_security_gate_input()` and
>   `_security_gate_output()` directly (`@abstractmethod` — omission raises `TypeError` at instantiation)

### Composition Pattern

- **Pattern**: GraphNode (subgraph) — outer `AgentBaseGraph` + inner `BaseGraph`
  (`FulfillmentOrchestrationGraphNode` wraps `FulfillmentWorkflowGraph`)
- **Composition target**: `src/graph/fulfillment_workflow_graph.py` (inner 5-node domain workflow)
- **Error propagation strategy**: `propagate` (fail fast on inner `SubgraphError`); the D6 HITL
  `interrupt()` inside the inner subgraph is a special case — `_handle_call_error` re-raises
  `GraphBubbleUp`/interrupt exceptions as-is (`propagate_hitl=True`) so the outer graph's own
 checkpointed Pregel loop converts it into `AWAITING_HUMAN`, matching the framework contract.

## Import Isolation Confirmation
- [x] Template does not import agenticstar-platform SDK (Level 0)
- [x] Import targets: framework/ and shared/ only (no agents/base/ required)

## Design Decision Record

| Decision | Option A | Option B | Chosen | Rationale |
|----------|----------|----------|--------|-----------|
| L1 base type | AgentBaseGraph | AutonomousBaseGraph | **AgentBaseGraph** | Fixed 7-step pipeline with defined terminal states, not a self-directed think→act loop |
| Composition pattern | Flat 3-slot (Cat 1 style) | Outer AgentBaseGraph + GraphNode + inner BaseGraph | **GraphNode + inner subgraph** | Cat 2 (CoE 2026-06-17 mandate) — `gate-composition` requires this shape for a multi-step job-to-be-done |
| Fulfillment policy source | VectorRAG lookup | Deterministic `config/fulfillment_policy.yaml` | **Deterministic config** | Corrected finding (Engineer Review §2-4): routing rules are business config, not a retrieval problem |
| HITL trigger | Hard-coded threshold | Config-driven threshold (`hitl.amount_threshold_jpy` / `hitl.volume_threshold_units`) | **Config-driven** | the framework contract prohibits hardcoded HITL triggers; retailer-tunable without a code change |
| Delivery address handling | Full address in State | Region-only in State (S-2) | **Region-only** | Engineer Review §11 risk #3 — customer address PII exposure mitigation |

## Dependencies (per Engineer Review §12 — tracked, non-blocking for engineering)

- EC platform / POS / WMS APIs: per-retailer integration — this template ships a deterministic
  simulated `aggregate_inventory()` in `src/services/fulfillment_service.py`; a real deployment
  injects the retailer's EC/POS/WMS client at node construction time.
- `config/fulfillment_policy.yaml`: shipped as an illustrative default; retailers tune
  `routing.channel_priority` and `hitl.*_threshold_*` per their own operations.


## Marketplace round (revised 2026-09-14)

**The order is read out of the message.** `OrderIngestNode` required `user_input` to be a
JSON order and returned `status=ERROR` otherwise; the Marketplace runner types the message
as a STRING, so every real platform request ended at "agent failed". Resolution order,
cheapest first: a packet in `input_context`, then patterns in the sentence (an order
number, a quantity, SKUs, a channel word, the region), then the model for whatever is
still missing. `drafting_degraded="pattern_only"` travels with an order assembled from
prose, so the sender is told to check it before acting.

**Only the REGION is ever read from an address.** The narrowest read that satisfies the
policy is the one that cannot leak: a street-level address is never extracted, so it can
never be stored.

**What the model may add, and what it may not.** Measured against the real model on
2026-09-14:

| Observation | What it forced |
|---|---|
| It returned `items` as the string `"['SKU-001']"` | The model never OVERWRITES a field the pattern already read — a blind merge put that string over the parsed list, and the stock lookup would have iterated its characters as SKUs |
| It returned an order number as `"EC 100231"` | The SEPARATOR is canonicalised; the result must still match the order-number pattern, so nothing unverifiable gets through. Without it a complete order was answered with "tell me the order number", which the sender had just given |
| It did not map 「ネットショップからのご注文」 to a channel code even with the closed set declared | The channel vocabulary lives in a deterministic table where it is testable; the model only ever ADDS what the table misses |
| A descriptive hint as a field value made every field come back empty | `INTAKE_POLICY["fields"]` values are `None` (any value) or a CLOSED SET — a free-text hint is iterated as its characters |

Every value the model proposes is checked for SHAPE and dropped if it does not fit. A
dropped field leaves the envelope incomplete and the sender is asked, which is recoverable;
a silently coerced value is not.

**`aggregate_inventory` accepts a bare SKU string.** It raised `AttributeError` — an
unhandled crash rather than an answer — for the item shape a person is most likely to send.

**The answer says where the order ships from.** The body was `order_id=... status=...`,
which never said the one thing this agent exists to decide. It now carries the selected
location, the delivery region, the stock each channel reported at lookup time, and the
terminal state in words. The machine-readable `fulfillment_status` /
`fulfillment_instruction` / `hitl_review_outcome` stay in the envelope for a calling system.

**HITL.** `interrupt()` is guarded by `hitl_allowed`: a parent `GraphNode` runs this agent
with `hitl_allowed=False` precisely to say nobody is there to answer, and an unguarded
`interrupt()` deadlocks that composition (the framework contract calls it a blocking defect). The
order still needs a human, so the run reports `referred_for_human_review` instead of
suspending — the caller gets a decision they can act on rather than a run that never
returns.

**Also:** every unusable input is answered with guidance naming the missing fields;
framework refusals raised around `execute()` reach the sender; `domain_config` is read where
it is declared; PyYAML is declared untyped rather than pinned as a dependency.
