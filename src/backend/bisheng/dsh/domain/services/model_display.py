"""Model labels shared by the Desktop catalog and its administration pages."""


def model_display_name(model, server) -> str:
    """Prefer the configured display name while keeping the provider visible."""
    provider = server.name.strip() or server.type
    name = model.name.strip() or model.model_name.strip()
    return f"{provider} / {name}"
