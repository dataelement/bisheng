"""Model labels shared by the Desktop catalog and its administration pages."""


def model_display_name(model, server) -> str:
    """Prefer the provider's own model name while keeping the provider visible."""
    provider = server.name.strip() or server.type
    name = model.model_name.strip() or model.name.strip()
    return f"{provider} / {name}"
