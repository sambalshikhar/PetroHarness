"""The model the harness runs on: K2-Horizon-7B GRPO (step 200), served by vLLM with native tool calling.

    MODELS[key] = (model card under resources/models, endpoints)

The endpoints are the model's servers, comma-separated in K2H_TOOL_URLS (default: one server on this machine at
vLLM's default port); a question picks one by its task id and rep."""
import os

MODELS = {"k200t": ("models/k2_horizon_7b_grpo200.yaml",
                    [u for u in os.environ.get("K2H_TOOL_URLS", "http://localhost:8000/v1").split(",") if u])}
