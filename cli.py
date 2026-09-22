"""Marketplace entrypoint — what `CMD ["python", "cli.py"]` runs inside the Pod.

`run_agent_marketplace()` owns the whole lifecycle: it constructs the agent as
`FulfillmentOrchestrationGraph(config=...)`, provisions secrets, compiles it, reads the invocation from the
database, runs the graph and writes the result back.

The class is imported from `src.graph.graph`, where it is defined — not from the package
path the manifest used to declare, whose __init__.py exports nothing.
"""

from pathlib import Path

from framework.utils.config_loader import load_agent_config
from shared.bootstrap.marketplace_app import run_agent_marketplace

from src.graph.graph import FulfillmentOrchestrationGraph

if __name__ == "__main__":
    run_agent_marketplace(
        FulfillmentOrchestrationGraph,
        agent_name="ret-c2-267",
        # Without this the runner builds `agent_cls(config={})` and every knob in
        # config/config.yaml is a promise with no delivery.
        config=load_agent_config(Path(__file__).resolve().parent),
    )
