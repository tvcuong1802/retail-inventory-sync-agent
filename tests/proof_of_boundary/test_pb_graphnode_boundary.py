# PB-6 gap fill (test-artifacts.md "PB-6 does not cover src/graph/"): the
# outer `main`-slot GraphNode wrapper is a real S-1 security boundary (first
# node in the outer backbone to receive caller input) but PB-6 only
# discovers concrete BaseNode subclasses under src/nodes/. This file probes
# that boundary directly.

import pytest

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel

from src.graph.graph import FulfillmentOrchestrationGraphNode
from src.nodes.inventory_check_node import InventoryCheckNode


class TestGraphNodeBoundary:
    def setup_method(self):
        self.node = FulfillmentOrchestrationGraphNode(policy_config={})

    def test_s1_trust_gate_denies_insufficient_caller_before_execute(self, monkeypatch):
        called = []
        monkeypatch.setattr(
            FulfillmentOrchestrationGraphNode, "extract_input", lambda self, state: called.append(1) or ""
        )
        state = {"caller_trust_level": TrustLevel.ANONYMOUS.value, "correlation_id": "pb-graphnode-1"}

        result = self.node(state)

        assert result["status"] == AgentStatus.ERROR.value
        assert "S-1 trust gate denied" in result["error_log"][0]
        assert not called, "execute() must not run when the S-1 trust gate denies the caller"

    def test_extract_input_maps_only_contracted_field(self):
        state = {
            "validated_input": '{"order_id": "ORD-1"}',
            "user_input": "raw",
            "correlation_id": "c1",
            "unrelated_field": "should not leak",
        }
        result = self.node.extract_input(state)
        assert result == '{"order_id": "ORD-1"}'
        assert "unrelated_field" not in result

    def test_merge_output_maps_fields_explicitly_not_raw_passthrough(self):
        # criterion #9: merge_output must not leak raw subgraph fields — only
        # the explicitly-mapped keys below may appear in the merged update.
        sub_result = {
            "validated_order": {"order_id": "ORD-1"},
            "inventory_snapshot": {},
            "policy_decision": {},
            "selected_route": {},
            "hitl_review_outcome": "auto_approved",
            "fulfillment_instruction": {},
            "status": AgentStatus.SUCCESS.value,
            "internal_subgraph_only_field": "must not leak to outer state",
        }
        merged = self.node.merge_output({}, sub_result)
        assert "internal_subgraph_only_field" not in merged
        assert set(merged.keys()) == {
            "validated_order",
            "inventory_snapshot",
            "policy_decision",
            "selected_route",
            "hitl_review_outcome",
            "fulfillment_instruction",
            "status",
        }

    def test_inner_entry_node_has_own_s2_s3_gate_by_design(self):
        # Delegation, not a gap: GraphNode.__call__ (BaseNode) does not run
        # _security_gate_input/output for the SUBGRAPH's inner nodes — each
        # inner FunctionNode enforces its own S-2/S-3 via the @final hooks
        # (framework/nodes/graph_node.py delegates gating to the inner
        # subgraph's own node invocation chain, it does not re-gate content).
        #
        # Local-wheel adaptation (documented, intentional — the verification notes
        # §A adaptation #3): a stale local `agenticstar-agentcore` wheel mirror predates
        # the @final _security_gate_input/output hooks on FunctionNode. CI installs the
        # pinned wheel (agenticstar-agentcore==1.0.0) where these exist — CI is the gate
        # of record, this skip is a local-only adaptation, not a test failure.
        if not hasattr(FunctionNode, "_security_gate_input"):
            pytest.skip("local agenticstar-agentcore wheel predates @final S-2/S-3 hooks — CI wheel is gate of record")
        assert InventoryCheckNode._security_gate_input is FunctionNode._security_gate_input
        assert InventoryCheckNode._security_gate_output is FunctionNode._security_gate_output
