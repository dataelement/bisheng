import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, BackgroundTasks, Depends, HTTPException, Query, Request, UploadFile
from loguru import logger

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.llm_tenant import LLMSystemConfigForbiddenError
from bisheng.common.models.config import ConfigKeyEnum
from bisheng.common.schemas.api import resp_200, UnifiedResponseModel
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.database.models.audit_log import AuditLogDao
from bisheng.database.models.tenant import ROOT_TENANT_ID
from bisheng.utils.http_middleware import _check_is_global_super
from bisheng.utils.mask_data import JsonFieldMasker
from ..domain import LLMService
from ..domain.models.tenant_system_model_config import TenantSystemModelConfigDao
from ..domain.schemas import KnowledgeLLMConfig, AssistantLLMConfig, EvaluationLLMConfig, LLMServerCreateReq, \
    WorkbenchModelConfig

router = APIRouter(prefix='/llm', tags=['LLM'])


# --- F022 helpers: write-side authz + audit -------------------------------


async def _assert_can_write_system_config(
    login_user: UserPayload, target_tenant_id: int,
) -> None:
    """Defense-in-depth check that ``target_tenant_id`` lies within the
    caller's manageable set. Redundant in the natural request path
    (target is sourced from ``get_current_tenant_id()`` which honors
    F019 admin-scope, and admin-scope is super-only) — kept so any
    future refactor that surfaces ``target_tenant_id`` from request
    body still fails closed.
    """
    if await _check_is_global_super(login_user.user_id):
        return
    if target_tenant_id == ROOT_TENANT_ID:
        # Non-super caller targeting Root — disallowed regardless of
        # any partial admin grant they might hold elsewhere.
        raise HTTPException(
            status_code=403,
            detail={
                'status_code': LLMSystemConfigForbiddenError.Code,
                'status_message': LLMSystemConfigForbiddenError.Msg,
            },
        )
    if await login_user.has_tenant_admin(target_tenant_id):
        return
    raise HTTPException(
        status_code=403,
        detail={
            'status_code': LLMSystemConfigForbiddenError.Code,
            'status_message': LLMSystemConfigForbiddenError.Msg,
        },
    )


_AUDIT_MASKER = JsonFieldMasker()


def _redact_payload(payload: Optional[Dict]) -> Dict:
    """Mask sensitive fields in audit metadata using the project-wide
    ``JsonFieldMasker`` rule set. Today's 5 system-config payloads only
    carry model_id refs + a prompt template, so mask_json is effectively
    a no-op — but routing through the shared masker means any future
    field additions inherit the same desensitization rules as the rest
    of the codebase (see ``bisheng/utils/mask_data.py``).
    """
    if not payload:
        return {}
    return _AUDIT_MASKER.mask_json(payload)


async def _audit_system_config_update(
    login_user: UserPayload,
    key: str,
    target_tenant_id: int,
    before: Optional[Dict],
    after: Optional[Dict],
) -> None:
    """Fire-and-forget audit log for system-config writes. Mirrors the
    F020 ``_write_llm_audit`` shape so SIEM dashboards can join across
    LLM events.
    """
    try:
        await AuditLogDao.ainsert_v2(
            tenant_id=target_tenant_id,
            operator_id=login_user.user_id,
            operator_tenant_id=get_current_tenant_id() or ROOT_TENANT_ID,
            action='llm.system_config.update',
            target_type='llm_system_config',
            target_id=key,
            metadata={
                'key': key,
                'target_tenant_id': target_tenant_id,
                'before': _redact_payload(before),
                'after': _redact_payload(after),
            },
        )
    except Exception:  # noqa: BLE001 — audit must never block user action
        logger.exception(
            'audit_log write failed action=llm.system_config.update key=%s target_tenant=%s',
            key, target_tenant_id,
        )


async def _read_before_snapshot(target_tenant_id: int, key: str) -> Optional[Dict]:
    """Read the current row for the audit ``before`` field. ``aresolve``
    isn't right here — we want the literal own-row state, not the Root
    fallback. Returns None when the row is absent.
    """
    row = await TenantSystemModelConfigDao.aget(target_tenant_id, key)
    if row is None or not row.value:
        return None
    try:
        return json.loads(row.value)
    except (TypeError, ValueError):
        return None


def _envelope(cfg, inherited: bool, blocked: bool) -> Dict[str, Any]:
    """Wrap a typed config dump for the GET responses."""
    if hasattr(cfg, 'model_dump'):
        data = cfg.model_dump()
    else:
        data = cfg
    return {
        'data': data,
        'inherited_from_root': inherited,
        'fallback_blocked': blocked,
    }


def _resolve_write_target(login_user: UserPayload) -> int:
    """Pick the tenant_id for system-config writes.

    Source: ``get_current_tenant_id()`` (admin-scope honored by F019
    middleware). Falls back to Root for super admins without an active
    scope.
    """
    return get_current_tenant_id() or ROOT_TENANT_ID


# --- LLM server CRUD (unchanged from F020) ---------------------------------


@router.get('')
async def get_all_llm(
        request: Request,
        only_shared: bool = Query(
            False,
            description='Return only Root-owned servers currently shared '
                        'to ≥1 Child (mount-preview dialog). Super-admin only.',
        ),
        login_user: UserPayload = Depends(UserPayload.get_login_user)):
    ret = await LLMService.get_all_llm(only_shared=only_shared, operator=login_user)
    return resp_200(data=ret)


@router.post('')
async def add_llm_server(request: Request,
                         login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
                         server: LLMServerCreateReq = Body(..., description="Service Provider All Data")):
    ret = await LLMService.add_llm_server(request, login_user, server)
    return resp_200(data=ret)


@router.delete('')
async def delete_llm_server(request: Request,
                            login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
                            server_id: int = Body(..., embed=True, description="Service Provider UniqueID")):
    await LLMService.delete_llm_server(request, login_user, server_id)
    return resp_200()


@router.put('')
async def update_llm_server(request: Request,
                            login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
                            server: LLMServerCreateReq = Body(..., description="Service Provider All Data")):
    ret = await LLMService.update_llm_server(request, login_user, server)
    return resp_200(data=ret)


@router.get('/info')
async def get_one_llm(request: Request,
                      login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
                      server_id: int = Query(..., description="Service Provider UniqueID")):
    ret = await LLMService.get_one_llm(server_id, operator=login_user)
    return resp_200(data=ret)


@router.post('/online')
async def update_model_online(request: Request,
                              login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
                              model_id: int = Body(..., embed=True, description="Model UniqueID"),
                              online: bool = Body(..., embed=True, description="Online or not")):
    ret = await LLMService.update_model_online(model_id, online)
    return resp_200(data=ret)


# --- F022: 5 system-config endpoints with tenant-scoped envelope -----------


@router.get('/workbench', summary="Get workbench-related model configurations", response_model=UnifiedResponseModel)
async def get_workbench_llm(
        request: Request,
        login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """Get Idea-Related Model Configurations. Honors admin-scope; envelope
    surfaces ``inherited_from_root`` / ``fallback_blocked`` for the UI."""
    cfg, inherited, blocked = await LLMService.aget_workbench_llm_with_meta()
    return resp_200(data=_envelope(cfg, inherited, blocked))


@router.post('/workbench', summary="Update workbench related model configurations", response_model=UnifiedResponseModel)
async def update_workbench_llm(
        background_tasks: BackgroundTasks,
        login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
        config_obj: WorkbenchModelConfig = Body(..., description="Model Configuration Object")):
    """Update Idea-Related Model Configurations."""
    target = _resolve_write_target(login_user)
    await _assert_can_write_system_config(login_user, target)
    before = await _read_before_snapshot(target, ConfigKeyEnum.LINSIGHT_LLM.value)
    ret = await LLMService.update_workbench_llm(
        login_user.user_id, config_obj, background_tasks, tenant_id=target,
    )
    await _audit_system_config_update(
        login_user, ConfigKeyEnum.LINSIGHT_LLM.value, target,
        before=before, after=config_obj.model_dump(),
    )
    return resp_200(data=ret)


@router.post('/workbench/asr')
async def invoke_workbench_asr(request: Request, login_user: UserPayload = Depends(UserPayload.get_login_user),
                               file: UploadFile = None):
    """ Call the workbench'sasrModels Convert Voice to Text """
    text = await LLMService.invoke_workbench_asr(login_user, file)
    return resp_200(data=text)


@router.post('/workbench/tts')
async def invoke_workbench_tts(request: Request, login_user: UserPayload = Depends(UserPayload.get_login_user),
                               text: str = Body(..., embed=True, description="Text that needs to be synthesized")):
    """ Call the workbench'sttsModels Convert text to speech """
    audio_url = await LLMService.invoke_workbench_tts(login_user, text)
    return resp_200(data=audio_url)


@router.get('/knowledge')
async def get_knowledge_llm(
        request: Request,
        login_user: UserPayload = Depends(UserPayload.get_login_user)):
    cfg, inherited, blocked = await LLMService.aget_knowledge_llm_with_meta()
    return resp_200(data=_envelope(cfg, inherited, blocked))


@router.post('/knowledge')
async def update_knowledge_llm(
        request: Request,
        login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
        data: KnowledgeLLMConfig = Body(..., description="Knowledge Base Default Model Configuration")):
    """ Update default model configuration for knowledge base """
    target = _resolve_write_target(login_user)
    await _assert_can_write_system_config(login_user, target)
    before = await _read_before_snapshot(target, ConfigKeyEnum.KNOWLEDGE_LLM.value)
    ret = await LLMService.update_knowledge_llm(data, tenant_id=target)
    await _audit_system_config_update(
        login_user, ConfigKeyEnum.KNOWLEDGE_LLM.value, target,
        before=before, after=data.model_dump(),
    )
    return resp_200(data=ret)


@router.get('/assistant')
async def get_assistant_llm(
        request: Request,
        login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ Get assistant related model configuration """
    cfg, inherited, blocked = await LLMService.aget_assistant_llm_with_meta()
    return resp_200(data=_envelope(cfg, inherited, blocked))


@router.post('/assistant')
async def update_assistant_llm(
        request: Request,
        login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
        data: AssistantLLMConfig = Body(..., description="Assistant Default Model Configuration")):
    """ Update assistant related model configurations """
    target = _resolve_write_target(login_user)
    await _assert_can_write_system_config(login_user, target)
    before = await _read_before_snapshot(target, ConfigKeyEnum.ASSISTANT_LLM.value)
    ret = await LLMService.update_assistant_llm(data, tenant_id=target)
    await _audit_system_config_update(
        login_user, ConfigKeyEnum.ASSISTANT_LLM.value, target,
        before=before, after=data.model_dump(),
    )
    return resp_200(data=ret)


@router.get('/evaluation')
async def get_evaluation_llm(
        request: Request,
        login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ Get evaluation related model configurations """
    cfg, inherited, blocked = await LLMService.aget_evaluation_llm_with_meta()
    return resp_200(data=_envelope(cfg, inherited, blocked))


@router.post('/evaluation')
async def update_evaluation_llm(
        request: Request,
        login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
        data: EvaluationLLMConfig = Body(..., description="Evaluate default model configuration")):
    """ Update review related model configurations """
    target = _resolve_write_target(login_user)
    await _assert_can_write_system_config(login_user, target)
    before = await _read_before_snapshot(target, ConfigKeyEnum.EVALUATION_LLM.value)
    ret = await LLMService.update_evaluation_llm(data, tenant_id=target)
    await _audit_system_config_update(
        login_user, ConfigKeyEnum.EVALUATION_LLM.value, target,
        before=before, after=data.model_dump(),
    )
    return resp_200(data=ret)


@router.get('/workflow')
async def get_workflow_llm(
        request: Request,
        login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ Get workflow-related model configurations """
    cfg, inherited, blocked = await LLMService.aget_workflow_llm_with_meta()
    return resp_200(data=_envelope(cfg, inherited, blocked))


@router.post('/workflow')
async def update_workflow_llm(
        request: Request,
        login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
        data: EvaluationLLMConfig = Body(..., description="Workflow default model configuration")):
    """ Update workflow-related model configurations """
    target = _resolve_write_target(login_user)
    await _assert_can_write_system_config(login_user, target)
    before = await _read_before_snapshot(target, ConfigKeyEnum.WORKFLOW_LLM.value)
    ret = await LLMService.update_workflow_llm(data, tenant_id=target)
    await _audit_system_config_update(
        login_user, ConfigKeyEnum.WORKFLOW_LLM.value, target,
        before=before, after=data.model_dump(),
    )
    return resp_200(data=ret)


@router.get('/assistant/llm_list')
async def get_assistant_llm_list(request: Request, login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """ Get a list of optional models for the assistant """
    ret = await LLMService.get_assistant_llm_list(request, login_user)
    return resp_200(data=ret)
