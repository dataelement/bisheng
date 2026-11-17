"""Allowlisted discovery metadata derived only from configured model facts."""

import json

from bisheng.dsh.domain.schemas.chat import ChatCapabilities


def model_metadata(model, capabilities: ChatCapabilities) -> dict:
    """Add Codex-style aliases without exposing arbitrary provider parameters."""
    result = {"input_modalities": ["text", "image"] if capabilities.vision else ["text"]}
    name = getattr(model, "model_name", None)
    if isinstance(name, str) and name.strip():
        result["slug"] = name.strip()

    config = getattr(model, "config", None)
    custom = config.get("user_kwargs") if isinstance(config, dict) else None
    if isinstance(custom, str):
        try:
            custom = json.loads(custom)
        except ValueError:
            # Optional discovery metadata: malformed advanced config has no known window.
            custom = None
    window = custom.get("context_window") if isinstance(custom, dict) else None
    if type(window) is int and window > 0:
        result["context_window"] = window

    reasoning = capabilities.reasoning
    if reasoning is not None:
        result["supported_reasoning_levels"] = [
            {"effort": effort.id, "description": effort.name} for effort in reasoning.efforts
        ]
        if reasoning.defaultEffort is not None:
            result["default_reasoning_level"] = reasoning.defaultEffort
    return result
