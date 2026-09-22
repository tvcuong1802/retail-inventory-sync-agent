# RET-C2-267 — Unit Tests: HITLGateNode
#
# The requires_hitl=True interrupt() path requires a real LangGraph run
# context (get_config() raises outside one) — that path is covered by the
# integration test (tests/integration/test_graph.py) and PB-7
# (tests/proof_of_boundary/test_pb7_hitl_interrupt_propagation.py). This unit
# test only covers the direct-callable auto_approved (non-interrupt) path.

import pytest

from framework.schemas.agent_status import AgentStatus
from src.nodes.hitl_gate_node import HITLGateNode


class TestHITLGateNode:
    def setup_method(self):
        self.node = HITLGateNode()

    def test_no_hitl_required_auto_approved_no_interrupt(self):
        state = {"policy_decision": {"requires_hitl": False}, "node_history": [], "error_log": []}
        result = self.node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS
        assert result["hitl_review_outcome"] == "auto_approved"

    def test_missing_policy_decision_defaults_no_hitl(self):
        state = {"node_history": [], "error_log": []}
        result = self.node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS
        assert result["hitl_review_outcome"] == "auto_approved"


class TestTheInterruptIsGuarded:
    """An unconditional `interrupt()` deadlocks a composition (the framework contract).

    A parent GraphNode runs this agent with `hitl_allowed=False` precisely to say there is
    no one to answer. Suspending anyway leaves the parent waiting for a resume that never
    comes -- a blocking defect, and invisible until someone composes the agent.

    The order still needs a human, so the non-interactive path says that rather than
    returning silence: the caller gets something they can act on.
    """

    def _state(self, **over):
        st = {
            "policy_decision": {"requires_hitl": True, "reason": "above threshold"},
            "selected_route": "manual_review",
            "node_history": [],
            "error_log": [],
        }
        st.update(over)
        return st

    def test_with_hitl_not_allowed_it_refers_instead_of_suspending(self):
        from src.nodes.hitl_gate_node import HITLGateNode

        out = HITLGateNode().execute(self._state(hitl_allowed=False))
        assert out["hitl_review_outcome"] == "referred_for_human_review"
        assert out["status"] == "success"
        assert "hitl_feedback" not in out, "nothing was answered, so nothing may be recorded as an answer"
        assert out["hitl_draft"], "the draft must survive so a human sees what was proposed"

    def test_with_hitl_allowed_it_still_reaches_the_interrupt(self):
        """The other direction, or the guard could disable HITL altogether.

        Called directly, `interrupt()` raises `RuntimeError("Called get_config outside of
        a runnable context")` -- it needs a real LangGraph run, which is what PB-7
        (tests/proof_of_boundary/test_pb7_hitl_interrupt_propagation.py) covers. Reaching
        the raise is what this test pins: the guard let the call through.
        """
        from src.nodes.hitl_gate_node import HITLGateNode

        with pytest.raises(RuntimeError, match="runnable context"):
            HITLGateNode().execute(self._state(hitl_allowed=True))

    def test_the_default_is_still_to_interrupt(self):
        """`state.get("hitl_allowed", True)` — absence means the caller said nothing, and
        the documented framework contract (the framework contract) treats that as permitted."""
        from src.nodes.hitl_gate_node import HITLGateNode

        with pytest.raises(RuntimeError, match="runnable context"):
            HITLGateNode().execute(self._state())
