from fastapi import APIRouter, Body, Depends, Request
from loguru import logger

from bisheng.api.v1.schemas import (
    KnowledgeSpaceConfig,
    LinsightConfig,
    SubscriptionConfig,
    UnifiedResponseModel,
    WorkstationConfig,
    resp_200,
)
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.services.config_service import settings as bisheng_settings
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.llm.domain.services.model_rate_limit import ModelRateLimitService
from bisheng.llm.domain.services.model_rate_limit_state import (
    ModelRateLimitState,
    ModelRateLimitView,
)
from bisheng.workstation.domain.schemas.workstation_schema import WorkstationModelRateLimitProjection
from bisheng.workstation.domain.services import WorkStationService

from ..dependencies import LoginUserDep

router = APIRouter()


async def project_workstation_model_states(
    models: list[dict],
    *,
    tenant_id: int,
    rate_limit_service=None,
) -> list[dict]:
    if not models:
        return []

    projected = [dict(model) for model in models]
    model_ids: list[int] = []
    for model in projected:
        try:
            model_id = int(model["id"])
        except (KeyError, TypeError, ValueError):
            continue
        if model_id not in model_ids:
            model_ids.append(model_id)

    states: dict[int, ModelRateLimitView] = {}
    if model_ids:
        service = rate_limit_service or ModelRateLimitService()
        try:
            states = await service.list_model_states(tenant_id, model_ids)
        except Exception as exc:
            logger.warning(
                "F051 workstation model state projection failed: tenant_id={} error_type={}",
                tenant_id,
                type(exc).__name__,
            )

    for model in projected:
        try:
            model_id = int(model["id"])
        except (KeyError, TypeError, ValueError):
            model_id = 0
        state = states.get(
            model_id,
            ModelRateLimitView(
                model_id=model_id,
                rate_limit_state=ModelRateLimitState.NORMAL,
                busy_until=None,
                status_version=0,
            ),
        )
        projection = WorkstationModelRateLimitProjection(
            rate_limit_state=state.rate_limit_state,
            busy_until=state.busy_until,
            status_version=state.status_version,
        )
        model.update(projection.model_dump(mode="json", by_alias=True))
    return projected


@router.get("/config", summary="Get workbench configuration", response_model=UnifiedResponseModel)
async def get_config(request: Request, login_user=LoginUserDep):
    ret = await WorkStationService.get_daily_chat_config()
    linsight_config = await WorkStationService.get_linsight_config()
    # `enable_etl4lm` historically gated the frontend on `etl4lm.url` alone, but the
    # parse pipeline now supports mineru / paddle_ocr as alternative providers that
    # also handle images. Use the unified image-parsing capability flag so the flag
    # follows whichever loader_provider is actually selected and configured.
    knowledge_conf = await bisheng_settings.async_get_knowledge()
    ret = ret.model_dump(exclude_unset=True) if ret else {}
    models = ret.get("models")
    if isinstance(models, list):
        tenant_id = get_current_tenant_id() or login_user.tenant_id
        ret["models"] = await project_workstation_model_states(models, tenant_id=tenant_id)
    # The admin curates this tool list, but each tool keeps its own resource
    # permission, so only offer the ones this user may actually run. Task mode
    # binds the same daily selection (see `_build_linsight_submit_payload`), so
    # filtering here covers both modes. The admin-facing `/config/daily` is
    # deliberately left unfiltered — that endpoint edits the curated list.
    if ret.get("tools"):
        ret["tools"] = await WorkStationService.afilter_tools_by_use_permission(ret["tools"], login_user)
    ret["linsightConfig"] = linsight_config.model_dump() if linsight_config else {}
    ret["enable_etl4lm"] = knowledge_conf.image_parser_enabled
    linsight_invitation_code = (await bisheng_settings.aget_all_config()).get("linsight_invitation_code", None)
    ret["linsight_invitation_code"] = linsight_invitation_code if linsight_invitation_code else False
    ret["linsight_cache_dir"] = "./"
    ret["waiting_list_url"] = (await bisheng_settings.aget_linsight_conf()).waiting_list_url
    # Forward the Shougang deployment namespace (for example deployment_label
    # and portal_admin_url), and derive the feature gate from its prefix.
    shougang_raw = (await bisheng_settings.aget_all_config()).get("shougang", None)
    if isinstance(shougang_raw, dict):
        prefix = shougang_raw.get("prefix")
        enabled = bool(prefix and str(prefix).strip())
        ret["shougang"] = {**shougang_raw, "enabled": enabled}
    else:
        ret["shougang"] = None
    # Forward the knowledge-space directory-tree gate to KnowledgeSpaceItem.
    # Default to true; the COFCO deployment disables folder expansion.
    ks_raw = (await bisheng_settings.aget_all_config()).get("knowledge_space", None)
    tree_display = True
    if isinstance(ks_raw, dict):
        tree_display = bool(ks_raw.get("tree_structured_directory_display", True))
    ret["knowledge_space"] = {"tree_structured_directory_display": tree_display}
    # Workbench AI assistant custom name, forwarded to the client chat panel header.
    # Sourced from tenant-level config (WORKSTATION_KNOWLEDGE_SPACE / WORKSTATION_SUBSCRIPTION),
    # a different source than the YAML-derived tree_structured_directory_display above.
    # Already tenant-inherited via aresolve; empty string => client falls back to its
    # localized default assistant label.
    ks_assistant_cfg = await WorkStationService.get_knowledge_space_config()
    sub_assistant_cfg = await WorkStationService.get_subscription_config()
    ret["knowledge_space"]["assistant_name"] = (ks_assistant_cfg.assistant_name or "") if ks_assistant_cfg else ""
    ret["subscription"] = {"assistant_name": (sub_assistant_cfg.assistant_name or "") if sub_assistant_cfg else ""}
    # Sidebar entry names for the knowledge-space / subscription modules; the home and
    # app-center ones ride along in the daily config dump above. Empty => client i18n default.
    ret["knowledge_space"]["menu_display_name"] = (ks_assistant_cfg.menu_display_name or "") if ks_assistant_cfg else ""
    ret["subscription"]["menu_display_name"] = (sub_assistant_cfg.menu_display_name or "") if sub_assistant_cfg else ""
    return resp_200(data=ret)


@router.get("/config/daily", summary="Get daily workbench configuration", response_model=UnifiedResponseModel)
async def get_daily_config(request: Request, login_user=LoginUserDep):
    (
        ret,
        inherited,
        source_tenant_id,
        has_override,
        is_fallback,
    ) = await WorkStationService.get_daily_chat_config_with_meta()
    return resp_200(
        data={
            "data": ret.model_dump(exclude_unset=True) if ret else None,
            "inherited_from_root": inherited,
            "source_tenant_id": source_tenant_id,
            "has_override": has_override,
            # Nothing was stored — this payload is the built-in default, not the
            # admin's settings. The config page confirms before persisting it.
            "is_fallback": is_fallback,
        }
    )


@router.post("/config/daily", summary="Update daily workbench configuration", response_model=UnifiedResponseModel)
async def update_daily_config(
    request: Request,
    data: WorkstationConfig = Body(...),
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
):
    ret = await WorkStationService.update_daily_chat_config(data)
    return resp_200(data=ret)


@router.get("/config/linsight", summary="Get linsight configuration", response_model=UnifiedResponseModel)
async def get_linsight_config(request: Request, login_user=LoginUserDep):
    ret, inherited, source_tenant_id, has_override = await WorkStationService.get_linsight_config_with_meta()
    return resp_200(
        data={
            "data": ret.model_dump(exclude_unset=True) if ret else None,
            "inherited_from_root": inherited,
            "source_tenant_id": source_tenant_id,
            "has_override": has_override,
        }
    )


@router.post("/config/linsight", summary="Update linsight configuration", response_model=UnifiedResponseModel)
async def update_linsight_config(
    request: Request,
    data: LinsightConfig = Body(...),
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
):
    ret = await WorkStationService.update_linsight_config(data)
    return resp_200(data=ret)


@router.get("/config/subscription", summary="Get subscription configuration", response_model=UnifiedResponseModel)
async def get_subscription_config(request: Request, login_user=LoginUserDep):
    ret, inherited, source_tenant_id, has_override = await WorkStationService.get_subscription_config_with_meta()
    return resp_200(
        data={
            "data": ret.model_dump(exclude_unset=True) if ret else None,
            "inherited_from_root": inherited,
            "source_tenant_id": source_tenant_id,
            "has_override": has_override,
        }
    )


@router.post("/config/subscription", summary="Update subscription configuration", response_model=UnifiedResponseModel)
async def update_subscription_config(
    request: Request,
    data: SubscriptionConfig = Body(...),
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
):
    ret = await WorkStationService.update_subscription_config(data)
    return resp_200(data=ret)


@router.get("/config/knowledge_space", summary="Get knowledge_space configuration", response_model=UnifiedResponseModel)
async def get_knowledge_space_config(request: Request, login_user=LoginUserDep):
    ret, inherited, source_tenant_id, has_override = await WorkStationService.get_knowledge_space_config_with_meta()
    return resp_200(
        data={
            "data": ret.model_dump(exclude_unset=True) if ret else None,
            "inherited_from_root": inherited,
            "source_tenant_id": source_tenant_id,
            "has_override": has_override,
        }
    )


@router.post(
    "/config/knowledge_space", summary="Update knowledge_space configuration", response_model=UnifiedResponseModel
)
async def update_knowledge_space_config(
    request: Request,
    data: KnowledgeSpaceConfig = Body(...),
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
):
    ret = await WorkStationService.update_knowledge_space_config(data)
    return resp_200(data=ret)
