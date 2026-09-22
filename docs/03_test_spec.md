# Test Specification — RET-C2-267

## Test Strategy
- Coverage target: all BL paths (unit + integration); hard % threshold enforced by CI gate
- Test types: Unit / Integration / Proof-of-Boundary

## Framework Compliance Tests (Mandatory)

| TC-ID | Test | Expected Result | Result |
|-------|------|----------------|--------|
| TC-01 | State contract: flat TypedDict | Type check pass, no Pydantic/dataclass | PASS |
| TC-02 | SecurityViolationError fires on invalid input | Error raised / ERROR status dict, no raise | PASS |
| TC-03 | No JWT/Credential in State | CI `gate-credential-scan`: 0 violations (S-5 enforcement moved to CI by (internal reference removed)) | PASS |
| TC-04 | InvocationContext via configurable only | Direct access raises error | PASS |
| TC-05 | S-4: no duplicate lifecycle events in `execute()` | `node_start` / `node_complete` / `node_error` absent from `execute()` body | 0 duplicates |
| TC-06 | S-2: `_security_gate_input()` not overridden (`FunctionNode` subclass) | `TypeError` raised at class definition if overridden (`@final` enforced by framework) | 0 overrides |
| TC-07 | S-3: `_security_gate_output()` not overridden (`FunctionNode` subclass) | `TypeError` raised at class definition if overridden (`@final` enforced by framework) | 0 overrides |
| TC-08 | `required_trust_level` enforced | Insufficient trust → refused | PASS |
| TC-09 | S-2: `_extra_security_gate_input()` non-trivial when domain checks needed | N/A — region-reduction in `OrderIngestNode.execute()` is the S-2 domain control; no `_extra_security_gate_input` override needed | N/A |
| TC-10 | S-3: `_extra_security_gate_output()` non-trivial when domain checks needed | N/A — output carries no PII (region-only address); no `_extra_security_gate_output` override needed | N/A |
| TC-11 | S-4: at least one domain `emit_trace_event()` inside each `execute()` | Domain event emitted on every invocation path (all 7 nodes) | ≥1 per node |

## Proof-of-Boundary Tests (Mandatory)

| PB-ID | Boundary | Test | Expected Result | Result |
|-------|----------|------|----------------|--------|
| PB-1 | BaseNode → EventEmitter | `emit_trace_event()` fires on every invocation path | No silent failures | PASS |
| PB-2 | State serialization | Post-invoke State is primitives only | No Pydantic/dataclass | PASS |
| PB-3 | Level 2 → External service | EC/POS/WMS aggregation is a deterministic simulated lookup (per-retailer integration is a tracked dependency, Engineer Review §12); no real external service call in this template | N/A (documented) |
| PB-4 | Import isolation | No Level 0 imports | AST scan: 0 violations | PASS |
| PB-5 | Checkpoint safety | No JWT/Pydantic in checkpoint | Inspection pass | PASS |
| PB-6 | Invoke execution order | `__call__()`: S-1 trust gate → S-4 `node_start` → S-2 `_security_gate_input` → `execute()` → S-3 `_security_gate_output` → S-4 `node_complete` | Order verified for every `src/nodes/*` class | PASS |
| PB-7 | HITL interrupt propagation | `interrupt()` inside the inner `HITLGateNode` raises `GraphInterrupt`; propagates through `BaseNode.__call__()`, is NOT caught by the application error boundary, surfaces as outer `AWAITING_HUMAN` (never `status=error`) via the Cat 2 GraphNode boundary (`propagate_hitl=True`) | PASS |

## Business Logic Tests

| TC-ID | Test | Input | Expected Result | Result |
|-------|------|-------|----------------|--------|
| BL-01 | Low-value/volume order routes without HITL | Order below both thresholds, sufficient stock on a channel | `fulfillment_status == "ORDER_ROUTED"`, `hitl_review_outcome == "auto_approved"` | PASS |
| BL-02 | High-value order suspends at HITL, resumes on approval | Order at/above `amount_threshold_jpy` | `invoke()` returns `AWAITING_HUMAN`; `resume(feedback={"decision":"approved"})` completes with `fulfillment_status == "ORDER_ROUTED"` | PASS |
| BL-03 | High-value order rejected at HITL | Same as BL-02, resumed with `{"decision":"rejected"}` | `fulfillment_status == "HITL_ESCALATION"`, `hitl_escalated == True` | PASS |
| BL-04 | Malformed / missing-field order envelope | Order missing `items` | `OrderIngestNode` returns `AgentStatus.ERROR`, no raise | PASS |
| BL-05 | No channel has sufficient stock | Order with an unfulfillable quantity | `selected_route.fulfillable == False`; `fulfillment_instruction.action == "hold"`; `fulfillment_status == "FAILED"` | PASS |

## Test Execution Summary
- Execution date: 2026-07-12
- Total tests: see CI `run-tests` job output (unit + integration + proof_of_boundary)
- Pass: all / Fail: 0 / Skip: PB-6 and PB-7-adjacent framework-attribute checks skip only on a stale
  local `agenticstar-agentcore` wheel mirror that predates `emit_trace_event` in `base_node` — this is
  an expected local adaptation, not a test failure. CI installs the pinned wheel
  (`agenticstar-agentcore==1.0.0`) where PB-6/PB-7 run in full; CI is the gate of record.
- Coverage: all BL paths (unit + integration); hard % threshold enforced by CI gate


## Marketplace round (added 2026-09-14)

`tests/unit/test_order_read_from_a_sentence.py` — 17 cases across four groups: reading the
sentence (whole order, region-only address, channel words vs the order id), what the model
is allowed to add (never overwrite, shape-checked, separator canonicalised), the stock
lookup accepting a bare SKU string, and the sender being answered rather than failed.

Ten mutants, all killed (mutation-tested 2026-09-14), including the `hitl_allowed` guard.

## Refused input — what the sender receives (shared contract, 2026-09-15)

Measured across the fleet with a real model: a message the framework's S-2 gate declined
came back as `status: error` carrying the generic line "No answer could be produced for
this request." `normalize_terminal_output()` raises on any status but SUCCESS, so the
runner discarded the whole envelope and the sender read **"agent failed"** — with nothing
to act on, and no reason to send anything different next time.

| Situation | What is returned | Why |
|---|---|---|
| S-2 declined the MESSAGE | `status: success`, `refusal_kind: "input"`, a sentence naming what to change, plus the trailer | The sender is legitimate and holds something they can fix; they only learn that if the reply reaches them |
| The agent has its own refusal wording | That wording, not the shared sentence | "The shipment could not be classified" says which step stopped; the generic line does not |
| S-1 denied the CALLER | `status: error`, `refusal_kind: "trust"`, the refusal and nothing else | A caller not permitted to invoke the agent must not be told what it is for |
| S-3 blocked the agent's OWN output | unchanged — `status: error` | The agent produced something its output gate would not pass. The sender can do nothing with that, and must not be invited to retry |
| The agent genuinely broke | unchanged — `status: error` | The one signal that says this is an operations problem |

Nothing downstream reads `status` to detect a refusal any more: the envelope names the
refusal in `refusal_kind`. A contract that could only be read by the symptom it was fixing
was not a contract.

Enforced by `tests/unit/test_disclaimer_always_present.py` —
`test_a_refused_MESSAGE_is_delivered_and_says_what_to_change`,
`test_a_REAL_failure_is_still_an_error` (its control), and
`test_the_gate_token_is_matched_as_a_whole_token`.
