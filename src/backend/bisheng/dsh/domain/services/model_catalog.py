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

    if not settings.credit_billing.enabled:
        candidates = await LLMService.aget_online_chat_models()
        return await _project_visible_models(config or verified, candidates, {model.id for model, _ in candidates})
    return await _project_models(config or verified, [int(model.id) for model in verified.models or []])


async def _project_models(config, model_ids):
    from bisheng.api.v1.schemas import WSModel
    from bisheng.dsh.domain.services.model_display import configured_display_names, model_display_name
    from bisheng.dsh.infrastructure.model_capabilities import desktop_model_capabilities
    from bisheng.llm.domain.services.llm import LLMService

    names = configured_display_names(config)
    result = []
    for model_id in model_ids:
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
                displayName=names.get(str(model.id)) or model.model_name.strip() or model.name.strip(),
                provider_id=str(server.id),
                provider_name=server.name.strip() or server.type,
                visual=capabilities.client_fields().get("vision", False),
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
    from bisheng.dsh.domain.services.vision import read_vision

    result = []
    for model, server in candidates:
        if model.id not in visible:
            continue
        model_name = model.model_name.strip() or model.name.strip()
        result.append(
            WSModel(
                id=str(model.id),
                key=str(model.id),
                name=model_name,
                displayName=names.get(str(model.id)) or model_name,
                provider_id=str(server.id),
                provider_name=server.name.strip() or server.type,
                visual=(await read_vision(model.id, snapshot=(model, server))).vision,
            )
        )
    return result


async def user_workbench_models(user_id: int, config=None):
    """The models a user may pick in the workbench, depending on whether credit billing is active."""
    from bisheng.common.services.config_service import settings

    if settings.credit_billing.enabled:
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
