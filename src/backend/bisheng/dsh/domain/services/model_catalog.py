"""The shared user-facing model catalog projected into Chat's existing schema."""

import asyncio

from bisheng.common.errcode.dsh import DshModelNotAllowedError
from bisheng.dsh.domain.services.model_display import read_workbench_metadata


async def workbench_models_for_display(operator, config=None):
    """Management display only; runtime callers keep personal policy checks."""
    from bisheng.core.context.tenant import get_admin_scope_tenant_id, get_current_tenant_id
    from bisheng.llm.domain.services.llm import LLMService

    target = get_admin_scope_tenant_id()
    if not getattr(operator, "is_global_super", False):
        if target is not None and target != operator.tenant_id:
            raise DshModelNotAllowedError()
        return await user_workbench_models(operator.user_id, config)
    if target is not None and get_current_tenant_id() != target:
        raise DshModelNotAllowedError()
    # Match the system model settings table: metadata is never a model allow-list.
    # The candidate query still verifies tenant ownership and actual Root sharing.
    verified = await read_workbench_metadata()
    candidates = await LLMService.aget_online_chat_models()
    return await _project_visible_models(config or verified, candidates, {model.id for model, _ in candidates})


async def read_visible_model_ids(user_id: int, model_ids: list[int]) -> set[int]:
    """Platform visibility, independent of DSH and personal credit allowances."""

    def read():
        from bisheng.core.database import get_sync_db_session
        from bisheng.dsh.domain.repositories.unified_policy import UnifiedPolicyRepository

        with get_sync_db_session() as session:
            return UnifiedPolicyRepository(session).visible_model_ids(user_id, model_ids)

    return await asyncio.to_thread(read)


async def user_workbench_models(user_id: int, config=None):
    """Every online chat model of the tenant that this user may see.

    The workbench ``models`` entries only carry optional metadata (display name,
    image support); a model needs no entry to be offered. DSH credit checks run
    at invocation and never define the candidate catalog.
    """
    from bisheng.llm.domain.services.llm import LLMService

    if config is None:
        config = await read_workbench_metadata()
    candidates = await LLMService.aget_online_chat_models()
    visible = await read_visible_model_ids(user_id, [model.id for model, _ in candidates])
    return await _project_visible_models(config, candidates, visible)


async def _project_visible_models(config, candidates, visible):
    from bisheng.api.v1.schemas import WSModel
    from bisheng.dsh.domain.services.model_display import configured_display_names

    names = configured_display_names(config)
    from bisheng.dsh.domain.services.vision import read_catalog_vision

    candidates = [(model, server) for model, server in candidates if model.id in visible]
    vision = await read_catalog_vision([model for model, _ in candidates])
    result = []
    for model, server in candidates:
        model_name = model.model_name.strip() or model.name.strip()
        result.append(
            WSModel(
                id=str(model.id),
                key=str(model.id),
                name=model_name,
                displayName=names.get(str(model.id)) or model_name,
                provider_id=str(server.id),
                provider_name=server.name.strip() or server.type,
                visual=vision[model.id],
            )
        )
    return result


async def project_workbench_config(config, user_id: int, *, operator=None):
    from bisheng.llm.domain.schemas import WorkbenchModelConfig

    config = config.model_copy(deep=True) if config else WorkbenchModelConfig()
    config.models = (
        await workbench_models_for_display(operator, config)
        if operator is not None
        else await user_workbench_models(user_id, config)
    )
    allowed = {model.id for model in config.models}
    default = config.models[0].id if config.models else None
    for field in ("chat_default_model_id", "linsight_default_model_id"):
        if getattr(config, field) not in allowed:
            setattr(config, field, default)
    return config
