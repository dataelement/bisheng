import asyncio
import hashlib
import os
from collections.abc import Iterable
from typing import Any, Optional

from fastapi import BackgroundTasks, HTTPException, Request, UploadFile
from langchain_core.documents import BaseDocumentCompressor, Document
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from loguru import logger

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.dsh import DshModelNotAllowedError
from bisheng.common.errcode.http_error import NotFoundError, ServerError
from bisheng.common.errcode.llm import (
    ModelNameRepeatError,
    ServerAddAllError,
    ServerAddError,
    ServerExistError,
    SpeechCredentialError,
)
from bisheng.common.errcode.llm_tenant import (
    LLMModelNotAccessibleError,
    LLMSystemConfigForbiddenError,
)
from bisheng.common.errcode.server import (
    AsrModelConfigDeletedError,
    AsrTranscriptionFailedError,
    NoAsrModelConfigError,
    NoTtsModelConfigError,
    TtsModelConfigDeletedError,
    TtsSynthesisFailedError,
)
from bisheng.common.models.config import ConfigKeyEnum
from bisheng.core.ai.asr.volcengine import SpeechAccessRejected, VolcengineRealtimeASRClient
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    get_current_tenant_id,
    strict_tenant_filter,
)
from bisheng.core.database import get_async_db_session
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.database.models.audit_log import AuditLogDao
from bisheng.database.models.tenant import ROOT_TENANT_ID
from bisheng.llm.application.model_default import ModelDefaultApplication, current_model_default_tenant
from bisheng.llm.application.model_default_read import get_model_default_read_runtime
from bisheng.llm.domain.const import LLMModelStatus, LLMModelType, LLMServerType
from bisheng.llm.domain.models import LLMDao, LLMModel, LLMServer
from bisheng.llm.domain.repositories.model_default_repository import ModelDefaultRepository
from bisheng.llm.domain.schemas import (
    AssistantLLMConfig,
    EvaluationLLMConfig,
    KnowledgeLLMConfig,
    LLMModelCreateReq,
    LLMModelInfo,
    LLMServerCreateReq,
    LLMServerInfo,
    WorkbenchModelConfig,
)
from bisheng.llm.domain.services.context_window import ContextWindowService
from bisheng.llm.domain.utils import invalidate_llm_info_cache, to_llm_invoke_error, usable_proxy_url
from bisheng.resource_reference.application.contracts import canonical_target_id
from bisheng.tenant.domain.constants import TenantAuditAction
from bisheng.tenant.domain.services.resource_share_service import ResourceShareService
from bisheng.utils import generate_uuid, md5_hash
from bisheng.utils.http_middleware import _check_is_global_super
from bisheng.utils.mask_data import JsonFieldMasker

from ..llm import BishengASR, BishengEmbedding, BishengLLM, BishengTTS
from ..llm.rerank import BishengRerank
from .model_discovery import ModelDiscoveryError, ModelDiscoveryRequest, ModelDiscoveryService

# A probe sends a couple of tokens; anything slower than this is unusable in a
# real request anyway, and without a cap one dead endpoint hangs the caller.
MODEL_TEST_TIMEOUT = 30
# Probes started by a save run concurrently, but a provider with many models
# should not get them all at once.
MODEL_TEST_CONCURRENCY = 4
# A save returns before its probes finish, so the tasks outlive the request.
# Keep a strong reference: the event loop holds pending tasks only weakly.
_background_probes: set[asyncio.Task] = set()


def _llm_api_key_hash(config: dict | None) -> str | None:
    """sha256 of the API key, first 16 hex chars — only the fingerprint
    ever lands in audit_log. Returns None when no key is configured."""
    if not config:
        return None
    key = config.get("openai_api_key") or config.get("api_key")
    if not key or not isinstance(key, str):
        return None
    return hashlib.sha256(key.encode()).hexdigest()[:16]


async def _write_llm_audit(
    login_user: "UserPayload",
    action: str,
    server: "LLMServer",
    *,
    extra: dict | None = None,
) -> None:
    # tenant_id = resource-owning tenant; operator_tenant_id = caller's
    # effective scope (admin-scope override respected).
    try:
        await AuditLogDao.ainsert_v2(
            tenant_id=getattr(server, "tenant_id", None) or ROOT_TENANT_ID,
            operator_id=login_user.user_id,
            operator_tenant_id=get_current_tenant_id() or ROOT_TENANT_ID,
            action=action,
            target_type="llm_server",
            target_id=str(getattr(server, "id", "") or ""),
            metadata={
                "server_name": getattr(server, "name", None),
                "endpoint": (getattr(server, "config", None) or {}).get("openai_api_base"),
                "api_key_hash": _llm_api_key_hash(getattr(server, "config", None)),
                **(extra or {}),
            },
        )
    except Exception:
        logger.exception("audit_log write failed action=%s target_id=%s", action, getattr(server, "id", None))


class LLMService:
    @staticmethod
    def _coerce_model_id(value: Any) -> int | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            model_id = int(value)
        except (TypeError, ValueError):
            return None
        return model_id if model_id > 0 else None

    # Credential and endpoint fields in the server config. Users pasting values with
    # leading/trailing whitespace break the http request header(e.g. "Bearer sk-xxx ")
    STRIP_CONFIG_KEY_SUFFIXES = ("_key", "_secret", "_base", "_url", "_endpoint", "_proxy", "_version")

    @classmethod
    def strip_config_whitespace(cls, config: dict | None) -> dict | None:
        """Strip leading/trailing whitespace from credential and endpoint fields in the server config"""
        if not isinstance(config, dict):
            return config
        result = {}
        for key, value in config.items():
            if isinstance(value, dict):
                result[key] = cls.strip_config_whitespace(value)
            elif isinstance(value, str) and key.endswith(cls.STRIP_CONFIG_KEY_SUFFIXES):
                stripped = value.strip()
                if key.endswith("_proxy"):
                    result[key] = usable_proxy_url(stripped) or ""
                else:
                    result[key] = stripped
            else:
                result[key] = value
        return result

    @classmethod
    async def _aget_inherited_system_default_server_ids_for_leaf(
        cls,
        leaf_id: int,
    ) -> list[int]:
        """Root servers referenced by system-config rows this leaf inherits.

        Child tenants can inherit Root's system model config even when the
        underlying Root LLM servers were not explicitly shared via FGA.
        The runtime already resolves those model_ids with dedicated Root-share
        fallback helpers; this method keeps the management UI honest by making
        the referenced servers visible in the list API as readonly rows.
        """
        if leaf_id == ROOT_TENANT_ID:
            return []

        def _extend_ids(dest: set[int], raw_ids: Iterable[Any]) -> None:
            for raw in raw_ids:
                model_id = cls._coerce_model_id(raw)
                if model_id is not None:
                    dest.add(model_id)

        inherited_model_ids: set[int] = set()

        knowledge_cfg, knowledge_inherited, _ = await cls.aget_knowledge_llm_with_meta(tenant_id=leaf_id)
        if knowledge_inherited:
            _extend_ids(
                inherited_model_ids,
                [
                    knowledge_cfg.embedding_model_id,
                    knowledge_cfg.source_model_id,
                    knowledge_cfg.extract_title_model_id,
                    knowledge_cfg.qa_similar_model_id,
                ],
            )

        assistant_cfg, assistant_inherited, _ = await cls.aget_assistant_llm_with_meta(tenant_id=leaf_id)
        if assistant_inherited:
            if assistant_cfg.auto_llm:
                _extend_ids(inherited_model_ids, [assistant_cfg.auto_llm.model_id])
            _extend_ids(
                inherited_model_ids,
                [one.model_id for one in (assistant_cfg.llm_list or [])],
            )

        evaluation_cfg, evaluation_inherited, _ = await cls.aget_evaluation_llm_with_meta(tenant_id=leaf_id)
        if evaluation_inherited:
            _extend_ids(inherited_model_ids, [evaluation_cfg.model_id])

        workflow_cfg, workflow_inherited, _ = await cls.aget_workflow_llm_with_meta(tenant_id=leaf_id)
        if workflow_inherited:
            _extend_ids(inherited_model_ids, [workflow_cfg.model_id])

        workbench_cfg, workbench_inherited, _ = await cls.aget_workbench_llm_with_meta(tenant_id=leaf_id)
        if workbench_inherited:
            _extend_ids(
                inherited_model_ids,
                [
                    *(one.id for one in (workbench_cfg.models or [])),
                    workbench_cfg.linsight_default_model_id,
                    workbench_cfg.chat_default_model_id,
                    getattr(workbench_cfg.embedding_model, "id", None),
                    getattr(workbench_cfg.asr_model, "id", None),
                    getattr(workbench_cfg.tts_model, "id", None),
                    getattr(workbench_cfg.chat_title_llm, "id", None),
                    getattr(workbench_cfg.memory_llm, "id", None),
                ],
            )

        if not inherited_model_ids:
            return []

        with bypass_tenant_filter():
            rows = await LLMDao.aget_model_by_ids(list(inherited_model_ids))
        return list(
            {row.server_id for row in rows if row is not None and row.server_id and row.tenant_id == ROOT_TENANT_ID}
        )

    # --- F022 system-config getters: 5 typed configs share the same
    # resolve-and-deserialize shape, so wire each named method through
    # one of these private helpers. Each named getter stays as a thin
    # delegate so the backward-compatible signatures (and discoverable
    # method names) survive.
    @classmethod
    async def _aget_typed_with_meta(cls, key, model_cls, tenant_id):
        """Raw management/sharing metadata; never an execution admission."""
        current_model_default_tenant(tenant_id)
        raw = await get_model_default_read_runtime().aget_default(key.value)
        return model_cls.model_validate_json(raw.payload_json), raw.inherited_from_root, raw.fallback_blocked

    @classmethod
    def _get_typed_sync(cls, key, model_cls, tenant_id, *, login_user=None, session=None):
        current_model_default_tenant(tenant_id)
        admitted = get_model_default_read_runtime().require_default(key.value, login_user=login_user, session=session)
        return model_cls.model_validate_json(admitted.payload_json)

    @classmethod
    async def _aget_typed_strict(cls, key, model_cls, tenant_id, *, login_user=None, session=None):
        current_model_default_tenant(tenant_id)
        admitted = await get_model_default_read_runtime().arequire_default(
            key.value, login_user=login_user, session=session
        )
        return model_cls.model_validate_json(admitted.payload_json)

    @classmethod
    async def aget_online_chat_models(cls) -> list[tuple[LLMModel, LLMServer]]:
        """Online chat (``llm``) models this tenant can see, with their providers.

        Uses the same server set as the management list (own + Root-shared), so
        the workbench offers exactly the rows an administrator sees there.
        """
        leaf_id = get_current_tenant_id() or ROOT_TENANT_ID
        servers = await cls.acollect_visible_servers(leaf_id)
        server_by_id = {server.id: server for server in servers}
        if not server_by_id:
            return []
        # Root-shared servers live outside the caller tenant; the server set above
        # has already been authorized, so only their models are read here.
        with bypass_tenant_filter():
            models = await LLMDao.aget_model_by_server_ids(list(server_by_id))
        return [
            (model, server_by_id[model.server_id])
            for model in sorted(models, key=lambda row: row.id)
            if model.online and (model.model_type or "").strip() == LLMModelType.LLM.value
        ]

    @classmethod
    async def acollect_visible_servers(cls, leaf_id: int, *, strict: bool = False) -> list[LLMServer]:
        """Every LLM server row this tenant may see: own + Root-shared + inherited.

        Extracted from ``get_all_llm`` so the model protocol face (F051) decides
        "which models can this tenant call" from the same code the management
        list renders, instead of a second query that drifts.

        ``strict=True`` propagates a permission-backend failure instead of
        quietly returning the narrower own-rows-only set — see
        ``LLMDao.aget_shared_server_ids_for_leaf``.
        """

        if leaf_id == ROOT_TENANT_ID:
            return list(await LLMDao.aget_all_server())

        # ``aget_all_server`` is otherwise filtered by the IN-list
        # ``visible_tenant_ids = {leaf, ROOT}`` (CustomMiddleware), which
        # would silently include every Root server here and short-circuit
        # the FGA ``shared_with`` check below. Force strict equality
        # ``tenant_id = leaf`` so ``own`` truly means "leaf's own", and
        # the FGA-derived ``shared_ids`` is the single source of truth
        # for which Root servers this Child sees.
        async def _own_only():
            with strict_tenant_filter():
                return await LLMDao.aget_all_server()

        own, shared_ids, inherited_default_server_ids = await asyncio.gather(
            _own_only(),
            LLMDao.aget_shared_server_ids_for_leaf(leaf_id, raise_on_error=strict),
            cls._aget_inherited_system_default_server_ids_for_leaf(leaf_id),
        )
        existing_ids = {s.id for s in own}
        extra_ids: list[int] = []
        seen_extra: set[int] = set()
        for sid in [*shared_ids, *inherited_default_server_ids]:
            if sid in existing_ids or sid in seen_extra:
                continue
            seen_extra.add(sid)
            extra_ids.append(sid)
        if not extra_ids:
            return list(own)
        with bypass_tenant_filter():
            shared_servers = await LLMDao.aget_server_by_ids(extra_ids)
        return list(own) + list(shared_servers)

    @classmethod
    async def acollect_visible_server_ids(cls, leaf_id: int, *, strict: bool = False) -> list[int]:
        """Ids only — what a caller that will fetch models by server id needs."""

        return [server.id for server in await cls.acollect_visible_servers(leaf_id, strict=strict)]

    @classmethod
    async def get_all_llm(
        cls,
        only_shared: bool = False,
        operator: Optional["UserPayload"] = None,
    ) -> list[LLMServerInfo]:
        """Get all the model data, Exclusion:keyand other sensitive information

        Non-super callers see their own tenant plus any Root server shared
        to their leaf (``{llm_server}#shared_with → tenant:{leaf}``). Root
        self-rows are deduped; merged Root-shared rows carry
        ``is_root_shared_readonly=True`` so the frontend disables edit.

        ``only_shared=True`` (super-admin only) previews the set of Root
        servers currently distributed to ≥1 Child — backing the mount-
        Child dialog.
        """
        if only_shared:
            if operator is None or not await _check_is_global_super(operator.user_id):
                raise LLMSystemConfigForbiddenError.http_exception()
            return await cls._list_shared_root_servers()

        leaf_id = get_current_tenant_id() or ROOT_TENANT_ID
        llm_servers = await cls.acollect_visible_servers(leaf_id)

        # share_to_children is intentionally left at default False on list
        # responses — OpenFGA's /read requires either ``user`` or ``object``
        # to be set, so a single batch call by relation is impossible, and
        # an N+1 per-server query would dominate this hot path. The list
        # row only renders the Root-share readonly Badge (driven by
        # is_root_shared_readonly); the truthful per-server share_to_children
        # is hydrated by ``get_one_llm`` when the user opens the edit view.

        # Root-tenant resources are writable only by a global super admin
        # operating from a Root scope. Anyone else seeing them — child
        # callers, super admins under admin-scope=child, and (the case
        # caught after the v2.5.1 backfill incident) Root-tenant *regular*
        # users — must see them as readonly so the UI greys out the edit
        # affordance. The backend write path also rejects these via
        # ``_assert_root_writable``; this flag keeps the UI honest.
        is_super = operator is not None and await _check_is_global_super(operator.user_id)

        # Resolve Root tenant display name once (only when at least one row
        # is Root-owned) so the readonly badge can show the actual Root
        # tenant name instead of a hard-coded "Root".
        root_tenant_name: str | None = None
        if any(s.tenant_id == ROOT_TENANT_ID for s in llm_servers):
            from bisheng.database.models.tenant import TenantDao

            with bypass_tenant_filter():
                root_tenant = await TenantDao.aget_by_id(ROOT_TENANT_ID)
            root_tenant_name = root_tenant.tenant_name if root_tenant is not None else None

        ret = []
        server_ids = []
        for one in llm_servers:
            server_ids.append(one.id)
            info = LLMServerInfo(**one.model_dump(exclude={"config"}))
            info.is_root_shared_readonly = one.tenant_id == ROOT_TENANT_ID and not (
                leaf_id == ROOT_TENANT_ID and is_super
            )
            if one.tenant_id == ROOT_TENANT_ID:
                info.tenant_name = root_tenant_name
            ret.append(info)

        # Bypass so Child callers see models under Root servers granted
        # via shared_with — the event layer would strip them out.
        with bypass_tenant_filter():
            llm_models = await LLMDao.aget_model_by_server_ids(server_ids)
        server_dicts: dict[int, list] = {}
        for one in llm_models:
            server_dicts.setdefault(one.server_id, []).append(LLMModelInfo(**one.model_dump(exclude={"config"})))

        for one in ret:
            one.models = server_dicts.get(one.id, [])
        return ret

    @classmethod
    async def _list_shared_root_servers(cls) -> list[LLMServerInfo]:
        """Root servers currently shared to ≥1 Child. Hydrates
        ``LLMServerInfo`` rows for the mount-Child preview dialog.

        OpenFGA's /read API rejects relation-only queries (must filter by
        ``user`` or ``object``), so we walk Root servers and probe each
        with ``list_sharing_children``. Root server count is small in
        practice (single-digit to dozens), making this acceptable.
        """
        with bypass_tenant_filter():
            root_servers = [s for s in await LLMDao.aget_all_server() if s.tenant_id == ROOT_TENANT_ID]
        if not root_servers:
            return []

        servers: list[LLMServer] = []
        for s in root_servers:
            children = await ResourceShareService.list_sharing_children(
                "llm_server",
                str(s.id),
            )
            if children:
                servers.append(s)
        if not servers:
            return []

        with bypass_tenant_filter():
            llm_models = await LLMDao.aget_model_by_server_ids([s.id for s in servers])

        by_server: dict[int, list] = {}
        for m in llm_models:
            by_server.setdefault(m.server_id, []).append(LLMModelInfo(**m.model_dump(exclude={"config"})))
        ret = []
        for s in servers:
            info = LLMServerInfo(**s.model_dump(exclude={"config"}))
            info.models = by_server.get(s.id, [])
            info.is_root_shared_readonly = False
            ret.append(info)
        return ret

    @classmethod
    async def get_model_for_call(cls, model_id: int) -> LLMModel:
        """Fetch a model for cross-module invocation. Raises 19802 when
        the model is invisible under the current tenant scope and also
        not Root-shared to the caller's leaf."""
        model = await LLMDao.aget_model_by_id(model_id)
        if model is not None:
            return model

        with bypass_tenant_filter():
            raw = await LLMDao.aget_model_by_id(model_id)
        if raw is not None and raw.server_id:
            leaf_id = get_current_tenant_id() or ROOT_TENANT_ID
            shared_ids = await LLMDao.aget_shared_server_ids_for_leaf(leaf_id)
            if raw.server_id in shared_ids:
                return raw

        raise LLMModelNotAccessibleError.http_exception()

    @classmethod
    async def get_dsh_model_ids(cls) -> list[int]:
        """Reuse the existing model catalog; callers still validate each current snapshot."""
        with strict_tenant_filter():
            servers = await cls.get_all_llm()
        return sorted(
            {
                model.id
                for server in servers
                for model in server.models
                if model.online and model.model_type == LLMModelType.LLM.value
            }
        )

    @classmethod
    async def get_dsh_model_snapshot(cls, model_id: int) -> tuple[LLMModel, LLMServer]:
        """Read an online governed model/provider pair for one DSH invocation."""
        return await cls._get_governed_dsh_model_snapshot(model_id, online_required=True)

    @classmethod
    async def get_dsh_model_metadata_snapshot(cls, model_id: int) -> tuple[LLMModel, LLMServer]:
        """Read governed metadata so authorized administrators can restrict offline models."""
        return await cls._get_governed_dsh_model_snapshot(model_id, online_required=False)

    @classmethod
    async def _get_governed_dsh_model_snapshot(
        cls, model_id: int, *, online_required: bool
    ) -> tuple[LLMModel, LLMServer]:
        """Keep canonical tenant/Root-share checks common to both named operations.

        Ordinary callers retain their existing caching behavior. Root access is
        still decided by get_model_for_call; bypass only resolves the provider
        belonging to that verified model and never authorizes another model.
        """
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            raise DshModelNotAllowedError()
        try:
            with strict_tenant_filter():
                model = await cls.get_model_for_call(model_id)
        except HTTPException as exc:
            if exc.status_code == LLMModelNotAccessibleError.Code:
                raise DshModelNotAllowedError() from exc
            raise
        if (
            model.tenant_id not in {tenant_id, ROOT_TENANT_ID}
            or (online_required and not model.online)
            or model.model_type != LLMModelType.LLM.value
        ):
            raise DshModelNotAllowedError()
        with bypass_tenant_filter():
            server = await LLMDao.aget_server_by_id(model.server_id, cache=False)
        if server is None or server.tenant_id != model.tenant_id:
            raise DshModelNotAllowedError()
        return model, server

    @classmethod
    def build_dsh_llm(cls, model: LLMModel, server: LLMServer, *, user_id: int, streaming: bool = False):
        """Construct the governed wrapper from the exact DSH snapshot, without retries."""
        return BishengLLM.get_class_instance_from_snapshot(
            model_info=model,
            server_info=server,
            max_retries=0,
            app_id="dsh-desktop",
            app_name="DSH Desktop",
            app_type=ApplicationTypeEnum.DSH_DESKTOP,
            user_id=user_id,
            streaming=streaming,
        )

    @classmethod
    async def discover_models(cls, data: ModelDiscoveryRequest, operator: UserPayload) -> dict:
        config = data.config
        if data.server_id:
            info = await cls.get_one_llm(data.server_id, operator=operator)
            if info.is_root_shared_readonly:
                raise LLMSystemConfigForbiddenError()
            if info.type != data.provider:
                raise ModelDiscoveryError(msg="The provider must match the saved connection.")
            stored = await LLMDao.aget_server_by_id(data.server_id)
            if stored is None:
                raise NotFoundError.http_exception()
            config = JsonFieldMasker().update_json_with_masked(stored.config or {}, config)
        return await ModelDiscoveryService.discover(
            data.provider, cls.strip_config_whitespace(config), source=data.source, options=data.options
        )

    @classmethod
    async def get_one_llm(
        cls,
        server_id: int,
        operator: Optional["UserPayload"] = None,
    ) -> LLMServerInfo:
        """Get a service provider's details Containskeyand other sensitive configuration information"""
        leaf_id = get_current_tenant_id() or ROOT_TENANT_ID

        llm = await LLMDao.aget_server_by_id(server_id)
        if llm is None and leaf_id != ROOT_TENANT_ID:
            # Super admin under admin-scope=child (or genuine Child caller)
            # cannot read Root rows through the event-injected
            # ``WHERE tenant_id = leaf`` filter. Re-read under bypass and
            # gate by FGA ``shared_with`` so unshared Root rows stay
            # invisible — same contract as ``get_all_llm``.
            with bypass_tenant_filter():
                raw = await LLMDao.aget_server_by_id(server_id)
            if raw is not None and raw.tenant_id == ROOT_TENANT_ID:
                shared_ids = await LLMDao.aget_shared_server_ids_for_leaf(leaf_id)
                if server_id in shared_ids:
                    llm = raw
        if llm is None:
            raise NotFoundError.http_exception()
        # Defence in depth: even if the IN-list let a Root row through
        # here, gate it by FGA ``shared_with`` for Child-scoped callers.
        if llm.tenant_id == ROOT_TENANT_ID and leaf_id != ROOT_TENANT_ID:
            shared_ids = await LLMDao.aget_shared_server_ids_for_leaf(leaf_id)
            if server_id not in shared_ids:
                raise NotFoundError.http_exception()

        with bypass_tenant_filter():
            models = await LLMDao.aget_model_by_server_ids([server_id])
        models = [LLMModelInfo(**one.model_dump()) for one in models]
        info = LLMServerInfo(**llm.model_dump(), models=models)

        # Only the global super in Root scope is allowed to flip the
        # share_to_children toggle, so only that caller needs the truthful
        # FGA-derived value. Everyone else (Child callers, scope=child
        # super admins, Root-tenant regular users) sees the schema default
        # ``False`` — they cannot write the field anyway.
        is_super = operator is not None and await _check_is_global_super(operator.user_id)
        if llm.tenant_id == ROOT_TENANT_ID and leaf_id == ROOT_TENANT_ID and is_super:
            shared_children = await ResourceShareService.list_sharing_children(
                "llm_server",
                str(server_id),
            )
            info.share_to_children = bool(shared_children)
        info.is_root_shared_readonly = llm.tenant_id == ROOT_TENANT_ID and not (leaf_id == ROOT_TENANT_ID and is_super)
        if llm.tenant_id == ROOT_TENANT_ID:
            from bisheng.database.models.tenant import TenantDao

            with bypass_tenant_filter():
                root_tenant = await TenantDao.aget_by_id(ROOT_TENANT_ID)
            if root_tenant is not None:
                info.tenant_name = root_tenant.tenant_name
        return info

    @classmethod
    async def _ensure_volcengine_speech(cls, server_type: str, config: dict | None, models) -> None:
        """Reject a Volcengine Resource ID the credentials are not granted, before saving.

        Construction only checks that the id is one of the four known values. The
        vendor answers a mismatch with HTTP 403 on the websocket handshake, which
        used to surface the first time someone pressed the microphone.
        """
        if server_type != LLMServerType.VOLCENGINE.value:
            return
        if not any(model.model_type == LLMModelType.ASR_RT.value for model in models):
            return
        try:
            await VolcengineRealtimeASRClient("bigmodel", config or {}).verify_access()
        except SpeechAccessRejected:
            raise SpeechCredentialError.http_exception() from None
        except Exception as exc:
            logger.exception("volcengine speech credential check failed")
            raise ServerAddAllError.http_exception(str(exc)) from None

    @classmethod
    async def add_llm_server(
        cls, request: Request, login_user: UserPayload, server: LLMServerCreateReq
    ) -> LLMServerInfo:
        """Add a service provider"""
        exist_server = await LLMDao.aget_server_by_name(server.name)
        if exist_server:
            raise ServerExistError.http_exception()

        model_dict = {}
        for one in server.models:
            if one.model_name not in model_dict:
                model_dict[one.model_name] = LLMModel(**one.model_dump(), user_id=login_user.user_id)
            else:
                raise ModelNameRepeatError.http_exception()

        db_server = LLMServer(**server.model_dump(exclude={"models", "share_to_children"}))
        db_server.config = cls.strip_config_whitespace(db_server.config)
        db_server.user_id = login_user.user_id
        await cls._ensure_volcengine_speech(db_server.type, db_server.config, model_dict.values())

        db_server = await LLMDao.ainsert_server_with_models(
            db_server,
            list(model_dict.values()),
            share_to_children=server.share_to_children,
            operator=login_user,
        )

        ret = await cls.get_one_llm(db_server.id, operator=login_user)
        success_models = []
        success_msg = ""
        failed_models = []
        failed_msg = ""
        # Try to instantiate the corresponding model, delete it if there is an error
        common_params = {
            "app_id": ApplicationTypeEnum.MODEL_TEST.value,
            "app_name": ApplicationTypeEnum.MODEL_TEST.value,
            "app_type": ApplicationTypeEnum.MODEL_TEST,
            "user_id": login_user.user_id,
        }
        for one in ret.models:
            try:
                if one.model_type == LLMModelType.LLM.value:
                    await cls.get_bisheng_llm(model_id=one.id, ignore_online=True, **common_params)
                elif one.model_type == LLMModelType.EMBEDDING.value:
                    await cls.get_bisheng_embedding(model_id=one.id, ignore_online=True, **common_params)
                elif LLMModelType.is_speech(one.model_type):
                    # Constructing the client does not talk to the vendor. A sample
                    # transcription does, and a refusal or an unreachable endpoint
                    # drops the model instead of saving it as usable.
                    async with asyncio.timeout(MODEL_TEST_TIMEOUT):
                        await cls._invoke_model_probe(one, common_params)
                elif one.model_type == LLMModelType.TTS.value:
                    await cls.get_bisheng_tts(model_id=one.id, ignore_online=True, **common_params)

                success_msg += f"{one.model_name},"
                success_models.append(one)
            except Exception as e:
                logger.exception("init_model_error")
                # If model initialization fails, do not add to the model list
                failed_msg += f"<{one.model_name}>Add failed, Reason for failure:{e!s}\n"
                failed_models.append(one)

        # Description Failed to add all models
        if len(success_models) == 0 and failed_msg:
            cleanup = await cls._cleanup_failed_added_models(login_user, server, ret.id, success_models)
            if not cleanup:
                failed_msg += "Failed model rows were preserved because protected cleanup could not complete."
            raise ServerAddAllError.http_exception(failed_msg)
        elif len(success_models) > 0 and failed_msg:
            # Some models added successfully, Delete failed model information
            ret.models = success_models
            cleanup = await cls._cleanup_failed_added_models(login_user, server, ret.id, success_models)
            if not cleanup:
                failed_msg += "Failed model rows were preserved because protected cleanup could not complete."
            await cls.add_llm_server_hook(request, login_user, ret)
            raise ServerAddError.http_exception(f"<{success_msg.rstrip(',')}>Added{failed_msg}")

        await cls.add_llm_server_hook(request, login_user, ret)
        # Record what the share flag actually did, not what the request asked
        # for: ``ainsert_server_with_models`` only fans out when the new row is
        # Root-owned, and a super admin creating under a child-tenant admin
        # scope lands in that child. Logging the raw request value there would
        # claim a share that never happened.
        shared_to_children = bool(getattr(server, "share_to_children", True)) and db_server.tenant_id == ROOT_TENANT_ID
        await _write_llm_audit(
            login_user,
            TenantAuditAction.LLM_SERVER_CREATE.value,
            ret,
            extra={"share_to_children": shared_to_children},
        )
        return ret

    @classmethod
    async def _cleanup_failed_added_models(cls, login_user, server, server_id, successful):
        from bisheng.llm.application.model_deletion import get_model_deletion_application

        try:
            application = await get_model_deletion_application()
            if not successful:
                await application.adelete_server(identity=login_user, server_id=server_id)
            else:
                retained = [LLMModelCreateReq.model_validate(one.model_dump()) for one in successful]
                cleanup = server.model_copy(update={"id": server_id, "models": retained}, deep=True)
                await application.aupdate_server(identity=login_user, server=cleanup)
            return True
        except Exception:
            # A failed add must never bypass Coverage, confirmation, or an
            # existing provider fence merely to remove its failed probe rows.
            logger.exception("Protected model creation cleanup could not complete for provider {}", server_id)
            return False

    @classmethod
    async def delete_llm_server(
        cls,
        request: Request,
        login_user: UserPayload,
        server_id: int,
        *,
        force=False,
        confirmation_id=None,
        plan_digest=None,
    ) -> bool:
        """Delete a service provider"""
        from bisheng.llm.application.model_deletion import get_model_deletion_application

        application = await get_model_deletion_application()
        await application.adelete_server(
            identity=login_user,
            server_id=server_id,
            force=force,
            confirmation_id=confirmation_id,
            plan_digest=plan_digest,
        )
        return True

    @classmethod
    async def _after_protected_server_delete(cls, login_user, server):
        if server is not None:
            await _write_llm_audit(login_user, TenantAuditAction.LLM_SERVER_DELETE.value, server)

    @classmethod
    async def add_llm_server_hook(cls, request: Request, login_user: UserPayload, server: LLMServerInfo) -> bool:
        """Add a service provider Next Actions"""

        handle_types = []
        for one in server.models:
            if one.model_type in handle_types:
                continue
            handle_types.append(one.model_type)
            model_info = await LLMDao.aget_model_by_type(LLMModelType(one.model_type))
            # Determine if this is the firstllmorembeddingModels
            if model_info.id == one.id:
                await cls.set_default_model(model_info, login_user=login_user)
        await cls.probe_models_in_background(server.models, login_user)
        return True

    @classmethod
    async def probe_models_in_background(cls, models: list[LLMModel | LLMModelInfo], login_user: UserPayload) -> None:
        """Mark the models as unknown now and probe them after the request returns.

        A probe is a real call to the provider and can take up to
        MODEL_TEST_TIMEOUT. Saving a provider must not wait for it: one slow
        response used to hold the save button for the whole timeout. The status
        is reset first, so the list never shows a verdict about a model that the
        save has just changed. If the process stops before a probe finishes, the
        model stays unknown and the admin can check it again from the list.
        """
        if not models:
            return
        for one in models:
            await LLMDao.aupdate_model_status(one.id, LLMModelStatus.UNKNOWN.value, "")
        semaphore = asyncio.Semaphore(MODEL_TEST_CONCURRENCY)

        async def _probe(model: LLMModel | LLMModelInfo) -> None:
            async with semaphore:
                await cls.test_model_status(model, login_user)

        async def _probe_all() -> None:
            # test_model_status records every failure on the model itself, so
            # nothing is expected to reach here; log it if something does.
            results = await asyncio.gather(*(_probe(one) for one in models), return_exceptions=True)
            for model, result in zip(models, results, strict=True):
                if isinstance(result, BaseException):
                    logger.opt(exception=result).error("background model probe failed: {}", model.id)

        task = asyncio.create_task(_probe_all())
        _background_probes.add(task)
        task.add_done_callback(_background_probes.discard)

    @classmethod
    async def test_model_status(cls, model: LLMModel | LLMModelInfo, login_user: UserPayload):
        """Probe a model with one real call and record the verdict.

        Writes on BOTH outcomes: a model that was marked abnormal and has since
        been fixed has to be able to go back to normal, otherwise re-checking it
        can never change anything.
        """
        common_params = {
            "app_id": ApplicationTypeEnum.MODEL_TEST.value,
            "app_name": ApplicationTypeEnum.MODEL_TEST.value,
            "app_type": ApplicationTypeEnum.MODEL_TEST,
            "user_id": login_user.user_id,
        }
        try:
            async with asyncio.timeout(MODEL_TEST_TIMEOUT):
                await cls._invoke_model_probe(model, common_params)
        except TimeoutError:
            LLMDao.update_model_status(model.id, 1, f"Timeout after {MODEL_TEST_TIMEOUT}s")
            logger.warning("test model status timeout: {} {}", model.id, model.model_name)
        except Exception as e:
            LLMDao.update_model_status(model.id, 1, str(e))
            logger.exception(f"test model status: {model.id} {model.model_name}")
        else:
            # Clear any stale failure reason along with the status.
            LLMDao.update_model_status(model.id, 0, "")

    @classmethod
    async def _invoke_model_probe(cls, model: LLMModel | LLMModelInfo, common_params: dict):
        """Issue the smallest meaningful call for this model type."""
        if model.model_type == LLMModelType.LLM.value:
            bisheng_model = await cls.get_bisheng_llm(
                model_id=model.id, ignore_online=True, streaming=False, **common_params
            )
            await bisheng_model.ainvoke("hello")
        elif model.model_type == LLMModelType.EMBEDDING.value:
            bisheng_embed = await cls.get_bisheng_embedding(model_id=model.id, ignore_online=True, **common_params)
            await bisheng_embed.aembed_query("hello")
        elif model.model_type == LLMModelType.TTS.value:
            bisheng_tts = await cls.get_bisheng_tts(model_id=model.id, ignore_online=True, **common_params)
            await bisheng_tts.ainvoke("hello")
        elif LLMModelType.is_speech(model.model_type):
            example_file_path = os.path.join(os.path.dirname(__file__), "./asr_example.wav")
            with open(example_file_path, "rb") as f:
                bisheng_asr = await cls.get_bisheng_asr(model_id=model.id, ignore_online=True, **common_params)
                transcript = await bisheng_asr.ainvoke(f)
                if not transcript.strip():
                    raise ValueError("ASR model check returned no final transcript for the sample")
        elif model.model_type == LLMModelType.RERANK.value:
            bisheng_rerank = await cls.get_bisheng_rerank(model_id=model.id, ignore_online=True, **common_params)
            await bisheng_rerank.acompress_documents(documents=[Document(page_content="hello world")], query="hello")

    @classmethod
    async def set_default_model(cls, model: LLMModel | LLMModelInfo, *, login_user=None):
        tenant = current_model_default_tenant()
        await ModelDefaultApplication._authorize(login_user, tenant)

        async def original(key, schema):
            async with get_async_db_session() as active:
                resolved = await ModelDefaultRepository().aresolve(active, key.value)
            # Adding a provider does not convert an active inherited default
            # into a partial Child override or copy Root's configured IDs.
            if resolved.inherited_from_root:
                return None
            return schema.model_validate_json(resolved.own.payload_json) if resolved.own is not None else schema()

        # Every setting that takes a model is registered in system_model_autofill.SLOTS;
        # a newly added model fills the empty ones of its kind.
        from bisheng.llm.domain.services.system_model_autofill import CONFIG_TYPES, fill_empty_slots, kind_of

        if kind_of(model.model_type) is None:
            return
        savers = {
            ConfigKeyEnum.KNOWLEDGE_LLM: cls.update_knowledge_llm,
            ConfigKeyEnum.ASSISTANT_LLM: cls.update_assistant_llm,
            ConfigKeyEnum.EVALUATION_LLM: cls.update_evaluation_llm,
            ConfigKeyEnum.WORKFLOW_LLM: cls.update_workflow_llm,
        }
        for key, schema in CONFIG_TYPES.items():
            config = await original(key, schema)
            if config is None or not fill_empty_slots(key, config, model):
                continue
            if key == ConfigKeyEnum.LINSIGHT_LLM:
                await cls.update_workbench_llm(login_user.user_id, config, BackgroundTasks(), login_user=login_user)
            else:
                await savers[key](config, login_user=login_user)

    @classmethod
    async def update_llm_server(
        cls,
        request: Request,
        login_user: UserPayload,
        server: LLMServerCreateReq,
        *,
        force=False,
        confirmation_id=None,
        plan_digest=None,
    ) -> LLMServerInfo:
        """Update Service Provider Information"""
        exist_server = await LLMDao.aget_server_by_id(server.id)
        if not exist_server:
            raise NotFoundError.http_exception()

        from bisheng.llm.application.model_deletion import get_model_deletion_application

        application = await get_model_deletion_application()
        old_models = await LLMDao.aget_model_by_server_ids([exist_server.id])
        old_model_dict = {one.id: one for one in old_models}
        if exist_server.name != server.name:
            # If you change your name, determine if it already exists
            name_server = await LLMDao.aget_server_by_name(server.name)
            if name_server and name_server.id != server.id:
                raise ServerExistError.http_exception(f"<{server.name}>already exists")

        model_dict = {}
        for one in server.models:
            if one.model_name not in model_dict:
                model_dict[one.model_name] = LLMModel(**one.model_dump())
                # Explanation is to add a model
                if not one.id:
                    model_dict[one.model_name].user_id = login_user.user_id
                    model_dict[one.model_name].server_id = exist_server.id
            else:
                raise ModelNameRepeatError.http_exception()

        retained_ids = tuple(one.id for one in server.models if one.id)
        if len(retained_ids) != len(set(retained_ids)) or not set(retained_ids) <= set(old_model_dict):
            from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError

            raise ResourceReferenceInvalidError(reason="model_retained_identity_invalid")
        if set(old_model_dict) - set(retained_ids) or confirmation_id is not None or force:
            return await application.aupdate_server(
                identity=login_user,
                server=server,
                force=force,
                confirmation_id=confirmation_id,
                plan_digest=plan_digest,
            )

        replay = await application.areplay_completed_update(identity=login_user, server=server)
        if replay is not None:
            return replay
        if exist_server.tenant_id == ROOT_TENANT_ID:
            from bisheng.llm.application.model_sharing import get_model_sharing_application

            sharing_application = await get_model_sharing_application()
            await sharing_application.aresume_existing(
                identity=login_user, server_id=exist_server.id, enabled=server.share_to_children
            )
        await application.arequire_idle(server_id=exist_server.id)

        mask_maker = JsonFieldMasker()
        merged_config = cls.strip_config_whitespace(
            mask_maker.update_json_with_masked(exist_server.config, server.config)
        )
        await cls._ensure_volcengine_speech(server.type, merged_config, model_dict.values())

        exist_server.name = server.name
        exist_server.description = server.description
        exist_server.type = server.type
        exist_server.limit_flag = server.limit_flag
        exist_server.limit = server.limit
        exist_server.config = merged_config

        # Route share_to_children flips through the dedicated DAO helper
        # so super-admin / Root-only invariants are enforced via FGA.
        # Short-circuit when the requested state matches FGA truth — every
        # PUT carries ``share_to_children`` (pydantic default=True), so
        # without this guard a no-op edit would re-issue ``enable_sharing``
        # and FGA's non-idempotent ``write_tuples`` raises 400 on the
        # already-present tuples.
        if exist_server.tenant_id == ROOT_TENANT_ID and hasattr(server, "share_to_children"):
            current_shared_ids = await ResourceShareService.list_sharing_children(
                "llm_server",
                str(exist_server.id),
            )
            currently_shared = bool(current_shared_ids)
            if currently_shared != server.share_to_children:
                await LLMDao.aupdate_server_share(
                    exist_server.id,
                    server.share_to_children,
                    login_user,
                )

        db_server = await LLMDao.update_server_with_models(
            exist_server,
            list(model_dict.values()),
            operator=login_user,
        )
        new_server_info = await cls.get_one_llm(db_server.id, operator=login_user)
        if hasattr(server, "share_to_children") and exist_server.tenant_id == ROOT_TENANT_ID:
            await _write_llm_audit(
                login_user,
                TenantAuditAction.LLM_SERVER_TOGGLE_SHARE.value,
                db_server,
                extra={"share_to_children": server.share_to_children},
            )
        await _write_llm_audit(
            login_user,
            TenantAuditAction.LLM_SERVER_UPDATE.value,
            db_server,
        )

        # The probe below resolves the model and its server through the same 60s
        # in-process cache that no write invalidates, so a model renamed a moment
        # ago would be called under its old name and the verdict recorded against
        # it -- the status the list then shows belongs to the previous name. Evict
        # what this save just changed before probing anything.
        invalidate_llm_info_cache(server_id=db_server.id)
        for one in new_server_info.models:
            invalidate_llm_info_cache(model_id=one.id)
        # F087: the provider-reported context window is cached in Redis for an
        # hour; a saved config (new base URL, model name, ...) must re-read it.
        await ContextWindowService.invalidate([one.id for one in new_server_info.models])

        # Determine if the model status needs to be re-determined
        to_probe = []
        for one in new_server_info.models:
            if one.id not in old_model_dict:
                await cls.set_default_model(one, login_user=login_user)
            # The new model, or the model name or type has changed
            if (
                one.id not in old_model_dict
                or old_model_dict[one.id].model_name != one.model_name
                or old_model_dict[one.id].model_type != one.model_type
            ):
                one.status = LLMModelStatus.UNKNOWN.value
                one.remark = ""
                to_probe.append(one)
        await cls.probe_models_in_background(to_probe, login_user)
        return new_server_info

    @classmethod
    async def _after_protected_server_update(cls, login_user, info, old_server, old_models, request_data):
        if old_server.tenant_id == ROOT_TENANT_ID:
            await _write_llm_audit(
                login_user,
                TenantAuditAction.LLM_SERVER_TOGGLE_SHARE.value,
                info,
                extra={"share_to_children": request_data.share_to_children},
            )
        await _write_llm_audit(login_user, TenantAuditAction.LLM_SERVER_UPDATE.value, info)
        invalidate_llm_info_cache(server_id=info.id)
        old = {model.id: model for model in old_models}
        to_probe = []
        for model in info.models:
            invalidate_llm_info_cache(model_id=model.id)
            if model.id not in old:
                await cls.set_default_model(model, login_user=login_user)
            if (
                model.id not in old
                or old[model.id].model_name != model.model_name
                or old[model.id].model_type != model.model_type
            ):
                model.status, model.remark = LLMModelStatus.UNKNOWN.value, ""
                to_probe.append(model)
        await ContextWindowService.invalidate([model.id for model in info.models])
        await cls.probe_models_in_background(to_probe, login_user)

    @classmethod
    async def verify_model_status(cls, model_id: int, login_user: UserPayload) -> LLMModelInfo:
        """Re-probe one model on demand and return its refreshed state.

        The stored status is otherwise only decided when the provider config is
        saved, so it can be weeks stale; this lets an admin confirm a model is
        actually reachable right now without leaving the model list.
        """
        exist_model = await LLMDao.aget_model_by_id(model_id)
        if not exist_model:
            raise NotFoundError.http_exception()
        # The probe resolves the model through a 60s in-process cache that no
        # write invalidates, so a model renamed moments ago would be called under
        # its old name and reported back as "does not exist". Evict first — an
        # on-demand check that answers from a minute-old snapshot is worthless.
        invalidate_llm_info_cache(model_id=model_id, server_id=exist_model.server_id)
        await ContextWindowService.invalidate([model_id])
        # Probing ignores the online flag on purpose: a model taken offline
        # still needs checking before you decide to bring it back.
        await cls.test_model_status(exist_model, login_user)
        refreshed = await LLMDao.aget_model_by_id(model_id)
        return LLMModelInfo(**refreshed.model_dump())

    @classmethod
    async def update_model_online(cls, model_id: int, online: bool) -> LLMModelInfo:
        """Update whether the model is online"""
        exist_model = await LLMDao.aget_model_by_id(model_id)
        if not exist_model:
            raise NotFoundError.http_exception()
        exist_model.online = online
        await LLMDao.aupdate_model_online(exist_model.id, online)
        return LLMModelInfo(**exist_model.model_dump())

    @classmethod
    def get_knowledge_llm(cls, tenant_id: int | None = None, *, login_user=None, session=None) -> KnowledgeLLMConfig:
        return cls._get_typed_sync(
            ConfigKeyEnum.KNOWLEDGE_LLM, KnowledgeLLMConfig, tenant_id, login_user=login_user, session=session
        )

    @classmethod
    async def aget_knowledge_llm(
        cls, tenant_id: int | None = None, *, login_user=None, session=None
    ) -> KnowledgeLLMConfig:
        return await cls._aget_typed_strict(
            ConfigKeyEnum.KNOWLEDGE_LLM, KnowledgeLLMConfig, tenant_id, login_user=login_user, session=session
        )

    @classmethod
    async def aget_knowledge_llm_with_meta(
        cls,
        tenant_id: int | None = None,
    ) -> tuple[KnowledgeLLMConfig, bool, bool]:
        """Same as ``aget_knowledge_llm`` but also returns the
        ``(inherited_from_root, fallback_blocked)`` envelope flags. Used
        by the router to render the frontend banner; consumers stay on
        the single-value variant for backward compat.
        """
        return await cls._aget_typed_with_meta(
            ConfigKeyEnum.KNOWLEDGE_LLM,
            KnowledgeLLMConfig,
            tenant_id,
        )

    @classmethod
    def get_knowledge_source_llm(
        cls,
        invoke_user_id: int,
        tenant_id: int | None = None,
    ) -> BaseChatModel | None:
        """Get the default model configuration for Knowledge Base Traceability"""
        knowledge_llm = cls.get_knowledge_llm(tenant_id=tenant_id)
        # If no model is configured, usejieba
        if not knowledge_llm.source_model_id:
            return None
        return cls.get_bisheng_llm_sync(
            model_id=knowledge_llm.source_model_id,
            app_id=ApplicationTypeEnum.RAG_TRACEABILITY.value,
            app_name=ApplicationTypeEnum.RAG_TRACEABILITY.value,
            app_type=ApplicationTypeEnum.RAG_TRACEABILITY,
            user_id=invoke_user_id,
        )

    @classmethod
    async def get_knowledge_source_llm_async(
        cls,
        invoke_user_id: int,
        tenant_id: int | None = None,
    ) -> BaseChatModel | None:
        """Get the default model configuration for Knowledge Base Traceability"""
        knowledge_llm = await cls.aget_knowledge_llm(tenant_id=tenant_id)
        # If no model is configured, usejieba
        if not knowledge_llm.source_model_id:
            return None
        return await cls.get_bisheng_llm(
            model_id=knowledge_llm.source_model_id,
            app_id=ApplicationTypeEnum.RAG_TRACEABILITY.value,
            app_name=ApplicationTypeEnum.RAG_TRACEABILITY.value,
            app_type=ApplicationTypeEnum.RAG_TRACEABILITY,
            user_id=invoke_user_id,
        )

    @classmethod
    def get_knowledge_similar_llm(
        cls,
        invoke_user_id: int,
        tenant_id: int | None = None,
    ) -> BaseChatModel | None:
        """Get the default model configuration for knowledge base similar questions"""
        knowledge_llm = cls.get_knowledge_llm(tenant_id=tenant_id)
        # If no model is configured, usejieba
        if not knowledge_llm.qa_similar_model_id:
            return None
        return cls.get_bisheng_llm_sync(
            model_id=knowledge_llm.qa_similar_model_id,
            app_id=ApplicationTypeEnum.KNOWLEDGE_BASE.value,
            app_name=ApplicationTypeEnum.KNOWLEDGE_BASE.value,
            app_type=ApplicationTypeEnum.KNOWLEDGE_BASE,
            user_id=invoke_user_id,
        )

    @classmethod
    def get_knowledge_default_embedding(
        cls,
        invoke_user_id: int,
        tenant_id: int | None = None,
    ) -> Embeddings | None:
        """Get Knowledge Base DefaultsembeddingModels"""
        knowledge_llm = cls.get_knowledge_llm(tenant_id=tenant_id)
        if not knowledge_llm.embedding_model_id:
            return None
        return cls.get_bisheng_knowledge_embedding_sync(
            model_id=knowledge_llm.embedding_model_id, invoke_user_id=invoke_user_id
        )

    @classmethod
    async def _base_update_llm_config(
        cls, data: dict, key: ConfigKeyEnum, tenant_id=None, *, login_user=None, session=None
    ):
        await cls._save_model_default(key.value, data, tenant_id=tenant_id, login_user=login_user, session=session)
        return data

    @classmethod
    async def _save_model_default(cls, key, data, *, tenant_id=None, login_user=None, session=None):
        current_model_default_tenant(tenant_id)

        async def save(active):
            result = await ModelDefaultApplication._asave(active, key, data, login_user=login_user)
            if result.embedding_changed:
                embeddings = await cls.get_bisheng_embedding(
                    model_id=result.config.embedding_model.id,
                    app_id=ApplicationTypeEnum.LINSIGHT.value,
                    app_name=ApplicationTypeEnum.LINSIGHT.value,
                    app_type=ApplicationTypeEnum.LINSIGHT,
                    user_id=login_user.user_id,
                )
                try:
                    await embeddings.aembed_query("test")
                except Exception as error:
                    logger.exception("workbench embedding model probe failed")
                    raise to_llm_invoke_error(embeddings, error) from error
            return result

        if session is not None:
            return (await save(session)).config
        async with get_async_db_session() as active:
            result = await save(active)
            await active.commit()
        return result.config

    @classmethod
    async def update_knowledge_llm(
        cls, data: KnowledgeLLMConfig, tenant_id=None, *, login_user=None, session=None
    ) -> KnowledgeLLMConfig:
        return await cls._save_model_default(
            ConfigKeyEnum.KNOWLEDGE_LLM.value, data, tenant_id=tenant_id, login_user=login_user, session=session
        )

    @classmethod
    async def get_assistant_llm(
        cls, tenant_id: int | None = None, *, login_user=None, session=None
    ) -> AssistantLLMConfig:
        return await cls._aget_typed_strict(
            ConfigKeyEnum.ASSISTANT_LLM, AssistantLLMConfig, tenant_id, login_user=login_user, session=session
        )

    @classmethod
    async def aget_assistant_llm_with_meta(
        cls,
        tenant_id: int | None = None,
    ) -> tuple[AssistantLLMConfig, bool, bool]:
        return await cls._aget_typed_with_meta(
            ConfigKeyEnum.ASSISTANT_LLM,
            AssistantLLMConfig,
            tenant_id,
        )

    @classmethod
    def sync_get_assistant_llm(
        cls, tenant_id: int | None = None, *, login_user=None, session=None
    ) -> AssistantLLMConfig:
        return cls._get_typed_sync(
            ConfigKeyEnum.ASSISTANT_LLM, AssistantLLMConfig, tenant_id, login_user=login_user, session=session
        )

    @classmethod
    async def update_assistant_llm(
        cls, data: AssistantLLMConfig, tenant_id=None, *, login_user=None, session=None
    ) -> AssistantLLMConfig:
        return await cls._save_model_default(
            ConfigKeyEnum.ASSISTANT_LLM.value, data, tenant_id=tenant_id, login_user=login_user, session=session
        )

    @classmethod
    async def get_evaluation_llm(
        cls, tenant_id: int | None = None, *, login_user=None, session=None
    ) -> EvaluationLLMConfig:
        return await cls._aget_typed_strict(
            ConfigKeyEnum.EVALUATION_LLM, EvaluationLLMConfig, tenant_id, login_user=login_user, session=session
        )

    @classmethod
    async def aget_evaluation_llm_with_meta(
        cls,
        tenant_id: int | None = None,
    ) -> tuple[EvaluationLLMConfig, bool, bool]:
        return await cls._aget_typed_with_meta(
            ConfigKeyEnum.EVALUATION_LLM,
            EvaluationLLMConfig,
            tenant_id,
        )

    @classmethod
    def sync_get_evaluation_llm(
        cls, tenant_id: int | None = None, *, login_user=None, session=None
    ) -> EvaluationLLMConfig:
        return cls._get_typed_sync(
            ConfigKeyEnum.EVALUATION_LLM, EvaluationLLMConfig, tenant_id, login_user=login_user, session=session
        )

    @classmethod
    async def get_evaluation_llm_object(
        cls,
        invoke_user_id: int,
        tenant_id: int | None = None,
    ) -> BaseChatModel:
        evaluation_llm = await cls.get_evaluation_llm(tenant_id=tenant_id)
        if not evaluation_llm.model_id:
            raise Exception("Evaluation model is not configured")
        return await cls.get_bisheng_llm(
            model_id=evaluation_llm.model_id,
            app_id=ApplicationTypeEnum.EVALUATION.value,
            app_name=ApplicationTypeEnum.EVALUATION.value,
            app_type=ApplicationTypeEnum.EVALUATION,
            user_id=invoke_user_id,
        )

    @classmethod
    async def get_bisheng_llm(cls, **kwargs) -> BaseChatModel:
        """Initialize LiftedllmConversation Model"""
        return await BishengLLM.get_bisheng_llm(**kwargs)

    @classmethod
    def get_bisheng_llm_sync(cls, **kwargs) -> BaseChatModel:
        """Initialize LiftedllmConversation Model"""
        return BishengLLM(**kwargs)

    @classmethod
    async def get_bisheng_linsight_llm(cls, invoke_user_id: int, **kwargs) -> BaseChatModel:
        return await BishengLLM.get_bisheng_llm(
            app_id=ApplicationTypeEnum.LINSIGHT.value,
            app_name=ApplicationTypeEnum.LINSIGHT.value,
            app_type=ApplicationTypeEnum.LINSIGHT,
            user_id=invoke_user_id,
            **kwargs,
        )

    @classmethod
    async def get_bisheng_rerank(cls, **kwargs) -> BaseDocumentCompressor:
        return await BishengRerank.get_bisheng_rerank(**kwargs)

    @classmethod
    def get_bisheng_rerank_sync(cls, **kwargs) -> BaseDocumentCompressor:
        return BishengRerank(**kwargs)

    @classmethod
    async def get_bisheng_embedding(cls, **kwargs) -> Embeddings:
        """Initialize LiftedembeddingModels"""
        return await BishengEmbedding.get_bisheng_embedding(**kwargs)

    @classmethod
    def get_bisheng_embedding_sync(cls, **kwargs) -> Embeddings:
        """Initialize LiftedembeddingModels"""
        return BishengEmbedding(**kwargs)

    @classmethod
    async def get_bisheng_daily_embedding(cls, invoke_user_id: int, model_id: int) -> Embeddings:
        """Get dailyembeddingModels"""
        return await cls.get_bisheng_embedding(
            model_id=model_id,
            app_id=ApplicationTypeEnum.DAILY_CHAT.value,
            app_name=ApplicationTypeEnum.DAILY_CHAT.value,
            app_type=ApplicationTypeEnum.DAILY_CHAT,
            user_id=invoke_user_id,
        )

    @classmethod
    async def get_bisheng_linsight_embedding(cls, invoke_user_id: int, model_id: int) -> Embeddings:
        """Get Ideas DefaultembeddingModels"""
        return await cls.get_bisheng_embedding(
            model_id=model_id,
            app_id=ApplicationTypeEnum.LINSIGHT.value,
            app_name=ApplicationTypeEnum.LINSIGHT.value,
            app_type=ApplicationTypeEnum.LINSIGHT,
            user_id=invoke_user_id,
        )

    @classmethod
    async def get_bisheng_knowledge_embedding(cls, invoke_user_id: int, model_id: int) -> Embeddings:
        """Get Knowledge Base DefaultsembeddingModels"""
        return await cls.get_bisheng_embedding(
            model_id=model_id,
            app_id=ApplicationTypeEnum.KNOWLEDGE_BASE.value,
            app_name=ApplicationTypeEnum.KNOWLEDGE_BASE.value,
            app_type=ApplicationTypeEnum.KNOWLEDGE_BASE,
            user_id=invoke_user_id,
        )

    @classmethod
    def get_bisheng_knowledge_embedding_sync(cls, invoke_user_id: int, model_id: int) -> Embeddings:
        """Get Knowledge Base DefaultsembeddingModels"""
        return cls.get_bisheng_embedding_sync(
            model_id=model_id,
            app_id=ApplicationTypeEnum.KNOWLEDGE_BASE.value,
            app_name=ApplicationTypeEnum.KNOWLEDGE_BASE.value,
            app_type=ApplicationTypeEnum.KNOWLEDGE_BASE,
            user_id=invoke_user_id,
        )

    @classmethod
    async def get_bisheng_asr(cls, **kwargs) -> BishengASR:
        """Initialize LiftedasrModels"""
        return await BishengASR.get_bisheng_asr(**kwargs)

    @classmethod
    async def get_bisheng_tts(cls, **kwargs) -> BishengTTS:
        """Initialize LiftedttsModels"""
        return await BishengTTS.get_bisheng_tts(**kwargs)

    @classmethod
    async def update_evaluation_llm(
        cls, data: EvaluationLLMConfig, tenant_id=None, *, login_user=None, session=None
    ) -> EvaluationLLMConfig:
        return await cls._save_model_default(
            ConfigKeyEnum.EVALUATION_LLM.value, data, tenant_id=tenant_id, login_user=login_user, session=session
        )

    @classmethod
    async def update_workflow_llm(
        cls, data: EvaluationLLMConfig, tenant_id=None, *, login_user=None, session=None
    ) -> EvaluationLLMConfig:
        return await cls._save_model_default(
            ConfigKeyEnum.WORKFLOW_LLM.value, data, tenant_id=tenant_id, login_user=login_user, session=session
        )

    @classmethod
    async def get_workflow_llm(
        cls, tenant_id: int | None = None, *, login_user=None, session=None
    ) -> EvaluationLLMConfig:
        return await cls._aget_typed_strict(
            ConfigKeyEnum.WORKFLOW_LLM, EvaluationLLMConfig, tenant_id, login_user=login_user, session=session
        )

    @classmethod
    async def aget_workflow_llm_with_meta(
        cls,
        tenant_id: int | None = None,
    ) -> tuple[EvaluationLLMConfig, bool, bool]:
        return await cls._aget_typed_with_meta(
            ConfigKeyEnum.WORKFLOW_LLM,
            EvaluationLLMConfig,
            tenant_id,
        )

    @classmethod
    async def get_assistant_llm_list(cls, request: Request, login_user: UserPayload) -> list[LLMServerInfo]:
        """Get a list of optional models for the assistant"""
        assistant_llm = await cls.get_assistant_llm(login_user=login_user)
        if not assistant_llm.llm_list:
            return []
        model_list = await LLMDao.aget_model_by_ids([one.model_id for one in assistant_llm.llm_list])
        if not model_list:
            return []

        default_llm = next(filter(lambda x: x.default, assistant_llm.llm_list), None)
        if not default_llm:
            default_llm = assistant_llm.llm_list[0]
        model_dict = {}
        default_server = None
        for one in model_list:
            if one.server_id not in model_dict:
                model_dict[one.server_id] = []
            if one.id == default_llm.model_id:
                default_server = one.server_id
                model_dict[one.server_id].insert(0, LLMModelInfo(**one.model_dump(exclude={"config"})))
                continue
            model_dict[one.server_id].append(LLMModelInfo(**one.model_dump(exclude={"config"})))
        server_list = await LLMDao.aget_server_by_ids(list(model_dict.keys()))

        ret = []
        for one in server_list:
            if one.id == default_server:
                ret.insert(0, LLMServerInfo(**one.model_dump(exclude={"config"}), models=model_dict[one.id]))
                continue
            ret.append(LLMServerInfo(**one.model_dump(exclude={"config"}), models=model_dict[one.id]))

        return ret

    @classmethod
    async def update_workbench_llm(
        cls,
        invoke_user_id,
        config_obj: WorkbenchModelConfig,
        background_tasks,
        tenant_id=None,
        *,
        login_user=None,
        session=None,
    ):
        if login_user is not None and invoke_user_id != login_user.user_id:
            raise LLMSystemConfigForbiddenError()
        return await cls._save_model_default(
            ConfigKeyEnum.LINSIGHT_LLM.value, config_obj, tenant_id=tenant_id, login_user=login_user, session=session
        )

    @classmethod
    async def get_workbench_llm(
        cls, tenant_id: int | None = None, *, login_user=None, session=None
    ) -> WorkbenchModelConfig:
        return await cls._aget_typed_strict(
            ConfigKeyEnum.LINSIGHT_LLM, WorkbenchModelConfig, tenant_id, login_user=login_user, session=session
        )

    @classmethod
    async def get_workbench_llm_for_picker(cls) -> WorkbenchModelConfig:
        """Add public provider labels to the already tenant-validated model list."""
        config = (await cls.get_workbench_llm()).model_copy(deep=True)
        if not config.models:
            return config
        # get_workbench_llm has checked local/Root ownership before this batch
        # read. The bypass resolves only those configured models and their servers.
        with bypass_tenant_filter():
            models = await LLMDao.aget_model_by_ids([int(model.id) for model in config.models])
            servers = await LLMDao.aget_server_by_ids(list({model.server_id for model in models}))
        model_by_id = {str(model.id): model for model in models}
        server_by_id = {server.id: server for server in servers}
        for option in config.models:
            model = model_by_id.get(str(option.id))
            server = server_by_id.get(model.server_id) if model else None
            option.provider_id = str(server.id) if server else None
            option.provider_name = (server.name.strip() or server.type) if server else None
            if model:
                option.name = model.model_name
        return config

    @classmethod
    async def aget_workbench_llm_with_meta(
        cls, tenant_id: int | None = None
    ) -> tuple[WorkbenchModelConfig, bool, bool]:
        return await cls._aget_typed_with_meta(ConfigKeyEnum.LINSIGHT_LLM, WorkbenchModelConfig, tenant_id)

    @classmethod
    async def project_workbench_runtime_capabilities(cls, config: WorkbenchModelConfig) -> WorkbenchModelConfig:
        """Derive client capabilities without changing the stored repair metadata."""
        projected = config.model_copy(deep=True)
        if projected.asr_model is not None:
            projected.asr_model.realtime = False
            try:
                model_id = int(canonical_target_id(projected.asr_model.id))
            except (TypeError, ValueError):
                return projected
            model, server = await BishengASR.get_model_server_info(model_id)
            projected.asr_model.realtime = BishengASR.uses_realtime(model, server)
        return projected

    @classmethod
    def get_workbench_llm_sync(
        cls, tenant_id: int | None = None, *, login_user=None, session=None
    ) -> WorkbenchModelConfig:
        return cls._get_typed_sync(
            ConfigKeyEnum.LINSIGHT_LLM, WorkbenchModelConfig, tenant_id, login_user=login_user, session=session
        )

    @classmethod
    async def invoke_workbench_asr(cls, login_user: UserPayload, file: UploadFile) -> str:
        """Call the workbench'sasrModels Convert Voice to Text"""
        if not file:
            raise ServerError.http_exception("no file upload")
        workbench_llm = await cls.get_workbench_llm(login_user=login_user)
        if not workbench_llm.asr_model or not workbench_llm.asr_model.id:
            raise NoAsrModelConfigError.http_exception()
        model_info = await LLMDao.aget_model_by_id(int(workbench_llm.asr_model.id))
        if not model_info:
            raise AsrModelConfigDeletedError.http_exception()
        try:
            asr_client = await cls.get_bisheng_asr(
                model_id=int(workbench_llm.asr_model.id),
                app_id=ApplicationTypeEnum.ASR.value,
                app_name=ApplicationTypeEnum.ASR.value,
                app_type=ApplicationTypeEnum.ASR,
                user_id=login_user.user_id,
            )
            return await asr_client.ainvoke(file.file)
        except BaseErrorCode:
            raise
        except Exception as e:
            # Provider-level recognition failure (rate limit, auth, an audio
            # format the model will not take) — surface as a dedicated business
            # code, not a raw 500, so the client shows a toast naming the reason
            # instead of the global maintenance overlay claiming the platform is
            # down. Same treatment as workbench TTS.
            logger.exception("workbench asr transcription failed")
            # Raised as an instance, not via http_exception: only this path puts
            # the provider's own words into the envelope's `data`, which is where
            # the client reads the {exception} its translated message leaves a
            # slot for. http_exception would have replaced the whole message with
            # the raw error instead, in English, whatever the user's language.
            raise AsrTranscriptionFailedError(exception=e) from e

    @classmethod
    async def invoke_workbench_tts(cls, login_user: UserPayload, text: str) -> str:
        """
        Call the workbench'sttsModels Convert text to speech
        :return: minioPath to
        """

        workbench_llm = await cls.get_workbench_llm(login_user=login_user)

        redis_client = await get_redis_client()

        if not workbench_llm.tts_model or not workbench_llm.tts_model.id:
            raise NoTtsModelConfigError.http_exception()
        model_info = await LLMDao.aget_model_by_id(model_id=int(workbench_llm.tts_model.id))
        if not model_info:
            raise TtsModelConfigDeletedError.http_exception()

        # get from cache
        voice = model_info.config.get("voice", "default") if model_info.config else "default"
        cache_key = f"workbench_tts:{model_info.id}:{voice}:{md5_hash(text)}"
        cache_value = await redis_client.aget(cache_key)
        if cache_value:
            return cache_value

        tts_client = await cls.get_bisheng_tts(
            model_id=int(workbench_llm.tts_model.id),
            app_id=ApplicationTypeEnum.TTS.value,
            app_name=ApplicationTypeEnum.TTS.value,
            app_type=ApplicationTypeEnum.TTS,
            user_id=login_user.user_id,
        )
        try:
            audio_bytes = await tts_client.ainvoke(text)
        except Exception as e:
            # Provider-level synthesis failure (e.g. empty audio from the TTS
            # backend) — surface as a dedicated business code, not a raw 500,
            # so the client shows a toast instead of the global maintenance overlay.
            logger.exception("workbench tts synthesis failed")
            raise TtsSynthesisFailedError.http_exception() from e
        # upload to minio
        object_name = f"tts/{generate_uuid()}.mp3"

        minio_client = await get_minio_storage()
        await minio_client.put_object(
            object_name=object_name, file=audio_bytes, content_type="audio/mpeg", bucket_name=minio_client.tmp_bucket
        )
        cache_value = await minio_client.get_share_link(object_name, bucket=minio_client.tmp_bucket)
        # The tmp bucket automatically clears files older than 7 days, so set the expiration time to 6 days
        await redis_client.aset(cache_key, cache_value, expiration=6 * 24 * 3600)
        return cache_value
