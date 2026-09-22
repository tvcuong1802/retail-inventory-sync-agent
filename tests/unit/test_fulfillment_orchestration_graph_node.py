# RET-C2-267 — Unit Tests: FulfillmentOrchestrationGraphNode (outer `main` GraphNode wrapper)
#
# Full compile()+invoke() traversal through the inner subgraph is covered by
# tests/integration/test_graph.py and the PB-7 HITL propagation test. This
# unit test only covers the GraphNode hook contract in isolation
# (extract_input / merge_output / _parent_config), per code-contracts.md.

import json

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel

from src.graph.graph import FulfillmentOrchestrationGraphNode


class TestFulfillmentOrchestrationGraphNode:
    def setup_method(self):
        self.node = FulfillmentOrchestrationGraphNode(policy_config={"routing": {"channel_priority": ["WMS"]}})

    def test_extract_input_prefers_validated_input(self):
        state = {"validated_input": json.dumps({"order_id": "ORD-001"}), "user_input": "raw", "correlation_id": "c1"}
        result = self.node.extract_input(state)
        assert json.loads(result)["order_id"] == "ORD-001"

    def test_extract_input_falls_back_to_user_input(self):
        state = {"user_input": "fallback", "correlation_id": "c1"}
        result = self.node.extract_input(state)
        assert result == "fallback"

    def test_merge_output_maps_expected_keys(self):
        sub_result = {
            "validated_order": {"order_id": "ORD-001"},
            "inventory_snapshot": {"SKU-1": {}},
            "policy_decision": {"requires_hitl": False},
            "selected_route": {"source_channel": "WMS", "fulfillable": True},
            "hitl_review_outcome": "auto_approved",
            "fulfillment_instruction": {"action": "ship"},
            "status": "success",
        }
        merged = self.node.merge_output({}, sub_result)
        assert merged["hitl_review_outcome"] == "auto_approved"
        assert merged["fulfillment_instruction"]["action"] == "ship"
        assert merged["status"] == "success"

    def test_parent_config_forwards_memory_and_hitl_and_policy(self):
        cfg = self.node._parent_config()
        assert cfg["memory_enabled"] is True
        assert cfg["hitl"]["enabled"] is True
        assert cfg["policy"]["routing"]["channel_priority"] == ["WMS"]

    def test_required_trust_level_matches_agent_yaml(self):
        # S-1 (3i): the outer main-slot GraphNode is the first node in the
        # outer backbone to receive caller input — it must declare a trust
        # gate matching agent.yaml (VERIFIED_EXTERNAL), not inherit the
        # framework default (ANONYMOUS). gate-trust-level-check does NOT
        # scan GraphNode subclasses, so this is the only coverage for it.
        assert FulfillmentOrchestrationGraphNode.required_trust_level == TrustLevel.VERIFIED_EXTERNAL

    def test_call_denies_insufficient_trust_before_execute(self, monkeypatch):
        # TC-08/PB-6 boundary: __call__ (BaseNode, not overridden) must refuse
        # ANONYMOUS callers before extract_input()/get_subgraph() ever run.
        called = []
        monkeypatch.setattr(FulfillmentOrchestrationGraphNode, "extract_input", lambda self, state: called.append(1) or "")
        state = {"caller_trust_level": TrustLevel.ANONYMOUS.value, "correlation_id": "c1"}
        result = self.node(state)
        assert result["status"] == AgentStatus.ERROR.value
        assert not called, "execute()/extract_input() must not run when the S-1 trust gate denies the caller"
