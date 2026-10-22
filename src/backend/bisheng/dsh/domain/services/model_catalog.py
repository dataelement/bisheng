"""The shared user-facing model catalog projected into Chat's existing schema."""

from bisheng.common.errcode.dsh import DshModelNotAllowedError


async def authorized_workbench_models(user_id: int, config=None):
    from bisheng.api.v1.schemas import WSModel
    from bisheng.dsh.domain.services.model_display import configured_display_names, model_display_name
    from bisheng.dsh.infrastructure.model_capabilities import desktop_model_capabilities
    from bisheng.dsh.runtime import read_policy
    from bisheng.llm.domain.services.llm import LLMService

    if config is None:
        config = await LLMService.get_workbench_llm()
    names = configured_display_names(config)
    policy = await read_policy(user_id)
    result = []
    for model_id in policy.allowed_model_ids:
        try:
            model, server = await LLMService.get_dsh_model_snapshot(model_id)
        except DshModelNotAllowedError:
            continue
        capabilities = await desktop_model_capabilities(model, server)
        if capabilities is None:
            continue
        result.append(
            WSModel(
                id=str(model_id),
                key=str(model_id),
                name=model_display_name(model, server, names.get(str(model.id))),
                displayName=model_display_name(model, server, names.get(str(model.id))),
                visual=capabilities.client_fields().get("vision", False),
            )
        )
    return result


async def project_workbench_config(config, user_id: int):
    from bisheng.common.services.config_service import settings

    if not settings.dsh.enabled:
        return config
    from bisheng.llm.domain.schemas import WorkbenchModelConfig

    config = config.model_copy(deep=True) if config else WorkbenchModelConfig()
    config.models = await authorized_workbench_models(user_id, config)
    allowed = {model.id for model in config.models}
    default = config.models[0].id if config.models else None
    for field in ("chat_default_model_id", "linsight_default_model_id"):
        if getattr(config, field) not in allowed:
            setattr(config, field, default)
    return config
