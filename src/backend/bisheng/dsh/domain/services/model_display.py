"""Shared display labels; routing continues to use immutable model IDs."""


def configured_display_names(config) -> dict[str, str]:
    return {
        str(model.id): model.displayName.strip()
        for model in (config.models or [])
        if model.id and model.displayName and model.displayName.strip()
    }


async def read_display_names() -> dict[str, str]:
    from bisheng.llm.domain.services.llm import LLMService

    return configured_display_names(await LLMService.get_workbench_llm())


def model_display_name(model, server, display_name: str | None = None) -> str:
    """Use the configured label with the provider, falling back to the model name."""
    provider = server.name.strip() or server.type
    name = (display_name or "").strip() or model.model_name.strip() or model.name.strip()
    return f"{provider} / {name}"
