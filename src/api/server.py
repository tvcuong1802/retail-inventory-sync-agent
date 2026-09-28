"""AgentCore Platform v1.0"""

from typing import Any


# Standalone HTTP entry point for the agent.
# Entry points are adapters only — no business logic here.
# For platform-level routing, AgentGateway calls agent.invoke() directly.

import os
import secrets
from pathlib import Path
from uuid import uuid4

import yaml
from fastapi import FastAPI, HTTPException, Request
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel

from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from framework.secrets.context import bound_secrets
from shared.secrets import factory as secrets_factory
from src.graph.graph import Graph

app = FastAPI(title="RET-C2-267 Retail Omnichannel Inventory Sync & Fulfillment Orchestration Agent")

_policy_path = Path(__file__).resolve().parents[2] / "config" / "fulfillment_policy.yaml"
_policy_config = yaml.safe_load(_policy_path.read_text(encoding="utf-8")) if _policy_path.exists() else {}

agent = Graph(
    config={
        "max_retry": 3,
        "timeout_seconds": 30,
        # hitl.enabled: true (config/agent.yaml) requires memory_enabled + a
        # checkpointer attached at compile time (the framework contract) — the outer
        # graph itself suspends when the inner HITL gate (propagate_hitl=True)
        # surfaces an AWAITING_HUMAN status.
        "memory_enabled": True,
        "hitl": {"enabled": True, "max_hitl": 8},
        "policy": _policy_config,
    }
)
agent.compile(checkpointer=InMemorySaver())
# EnvProvider first, exactly as marketplace_app.py chains it. Without it this adapter
# cannot read a secret from the process environment, so a local run silently exercises the
# degradation path while the platform exercises the real one -- and the two look identical
# from the outside. ImportError-guarded: the chained/env providers ship only in the vendor
# wheel, and a bare import here turns a missing extra into a dead entry point.
_FACTORY = secrets_factory(namespace="ret-c2-267", agent_name="fulfillment-orchestration")
try:
    from framework.secrets.chained_provider import ChainedSecretProvider
    from framework.secrets.env_provider import EnvProvider

    _PROVIDER = ChainedSecretProvider(EnvProvider(), _FACTORY)
except ImportError:  # pragma: no cover — registry wheel ships neither module
    _PROVIDER = _FACTORY

agent.provision_secrets(_PROVIDER)


class InvokeRequest(BaseModel):
    input: str
    session_id: str = ""


@app.post("/invoke")
async def invoke(req: InvokeRequest, request: Request) -> dict[str, Any]:
    trust = getattr(request.state, "trust_level", TrustLevel.ANONYMOUS)
    # Standalone/STG caller auth (the deployment runbook): when
    # INVOKE_AUTH_TOKEN is set on the server environment, callers that no upstream
    # middleware vouched for (still ANONYMOUS) must present it as a Bearer token
    # and run at VERIFIED_EXTERNAL. Middleware-established trust is never demoted.
    # This adapter is the entry-point auth boundary (standalone equivalent of
    # platform AuthMiddleware) — a deployment-level caller credential, not an
    # agent secret, so ctx.secrets does not apply (no InvocationContext exists
    # before auth); see the framework contract "Entry-point exception".
    expected = os.environ.get("INVOKE_AUTH_TOKEN")
    if expected and trust is TrustLevel.ANONYMOUS:
        supplied = request.headers.get("authorization", "")
        # Compare bytes: compare_digest raises TypeError on non-ASCII str input
        # (headers decode as latin-1), which would 500 instead of the generic 401.
        if not secrets.compare_digest(supplied.encode(), f"Bearer {expected}".encode()):
            # Generic body on purpose — do not leak whether the token was absent,
            # malformed, or wrong.
            raise HTTPException(status_code=401, detail="Token is invalid or expired.")
        trust = TrustLevel.VERIFIED_EXTERNAL
    with bound_secrets(agent._secrets_provider):
        ctx = InvocationContext(
            session_id=req.session_id or str(uuid4()),
            caller_trust_level=trust,
            caller_id=getattr(request.state, "caller_id", ""),
        )
        envelope: dict[str, Any] = agent.invoke(req.input, ctx=ctx)
        return envelope


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "agent": "ret-c2-267"}
