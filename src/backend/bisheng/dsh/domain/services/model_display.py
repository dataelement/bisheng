"""Shared display labels; routing continues to use immutable model IDs."""


def configured_display_names(config) -> dict[str, str]:
    return {
        str(model.id): model.displayName.strip()
        for model in (config.models or [])
        if model.id and model.displayName and model.displayName.strip()
    }


async def read_workbench_metadata():
    from bisheng.llm.application.model_default_read import get_model_default_read_runtime
    from bisheng.llm.domain.schemas import WorkbenchModelConfig

    record = await get_model_default_read_runtime().aget_default("linsight_llm")
    return WorkbenchModelConfig.model_validate_json(record.payload_json)


async def read_display_names() -> dict[str, str]:
    return configured_display_names(await read_workbench_metadata())


def model_display_name(model, server, display_name: str | None = None) -> str:
    """Use the configured label with the provider, falling back to the model name."""
    provider = server.name.strip() or server.type
    name = (display_name or "").strip() or model.model_name.strip() or model.name.strip()
    return f"{provider} / {name}"
