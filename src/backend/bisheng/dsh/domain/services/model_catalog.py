"""The shared user-facing model catalog projected into Chat's existing schema."""

import asyncio

from bisheng.common.errcode.dsh import DshModelNotAllowedError
from bisheng.dsh.domain.services.model_display import read_workbench_metadata


async def authorized_workbench_models(user_id: int, config=None):
    from bisheng.dsh.runtime import read_policy

    if config is None:
        config = await read_workbench_metadata()
    policy = await read_policy(user_id)
    return await _project_models(config, policy.allowed_model_ids)


async def workbench_models_for_display(operator, config=None):
    """Management display only; runtime callers keep personal policy checks."""
    from bisheng.core.context.tenant import get_admin_scope_tenant_id, get_current_tenant_id
    from bisheng.llm.domain.services.llm import LLMService

    target = get_admin_scope_tenant_id()
    if target is None or target == operator.tenant_id:
        return await user_workbench_models(operator.user_id, config)
    if not operator.is_global_super or get_current_tenant_id() != target:
        raise DshModelNotAllowedError()
    # Revalidate ownership/sharing even when an editable metadata payload was
    # supplied. Configured IDs are display candidates, never a billing identity.
    verified = await read_workbench_metadata()
    from bisheng.common.services.config_service import settings

    if not settings.dsh.enabled:
        candidates = await LLMService.aget_online_chat_models()
        return await _project_visible_models(config or verified, candidates, {model.id for model, _ in candidates})
    return await _project_models(config or verified, [int(model.id) for model in verified.models or []])


async def _project_models(config, model_ids):
    from bisheng.api.v1.schemas import WSModel
    from bisheng.dsh.domain.services.model_display import configured_display_names, model_display_name
    from bisheng.dsh.domain.services.vision import read_catalog_vision
    from bisheng.dsh.infrastructure.model_capabilities import model_capabilities
    from bisheng.llm.domain.services.llm import LLMService

    names = configured_display_names(config)
    snapshots = await LLMService.get_dsh_model_catalog_snapshots(model_ids)
    # Keep provider capability validation for the same catalog candidates.
    candidates = list(snapshots.values())
    for model, server in candidates:
        model_capabilities(model, server)
    vision = await read_catalog_vision([model for model, _ in candidates])
    result = []
    for model, server in candidates:
        result.append(
            WSModel(
                id=str(model.id),
                key=str(model.id),
                name=model_display_name(model, server, names.get(str(model.id))),
                displayName=names.get(str(model.id)) or model.model_name.strip() or model.name.strip(),
                provider_id=str(server.id),
                provider_name=server.name.strip() or server.type,
                visual=vision[model.id],
            )
        )
    return result


async def read_visible_model_ids(user_id: int, model_ids: list[int]) -> set[int]:
    """Visibility without DSH: no stored row means everyone may use the model."""

    def read():
        from bisheng.core.database import get_sync_db_session
        from bisheng.dsh.domain.repositories.unified_policy import UnifiedPolicyRepository

        with get_sync_db_session() as session:
            return UnifiedPolicyRepository(session).visible_model_ids(user_id, model_ids)

    return await asyncio.to_thread(read)


async def visible_workbench_models(user_id: int, config=None):
    """Every online chat model of the tenant that this user may see (DSH not deployed).

    The workbench ``models`` entries only carry optional metadata (display name,
    image support); a model needs no entry to be offered. No credits apply.
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


async def user_workbench_models(user_id: int, config=None):
    """The models a user may pick in the workbench, in either deployment mode."""
    from bisheng.common.services.config_service import settings

    if settings.dsh.enabled:
        return await authorized_workbench_models(user_id, config)
    return await visible_workbench_models(user_id, config)


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
