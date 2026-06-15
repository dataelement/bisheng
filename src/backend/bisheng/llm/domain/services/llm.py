import asyncio
import hashlib
import json
import os
from collections.abc import Iterable
from typing import Any, Optional

from fastapi import BackgroundTasks, Request, UploadFile
from langchain_core.documents import BaseDocumentCompressor, Document
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from loguru import logger

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError, ServerError
from bisheng.common.errcode.llm import ModelNameRepeatError, ServerAddAllError, ServerAddError, ServerExistError
from bisheng.common.errcode.llm_tenant import (
    LLMModelNotAccessibleError,
    LLMSystemConfigForbiddenError,
)
from bisheng.common.errcode.server import (
    AsrModelConfigDeletedError,
    NoAsrModelConfigError,
    NoTtsModelConfigError,
    TtsModelConfigDeletedError,
)
from bisheng.common.models.config import ConfigKeyEnum
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    get_current_tenant_id,
    strict_tenant_filter,
)
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.database.models.audit_log import AuditLogDao
from bisheng.database.models.tenant import ROOT_TENANT_ID
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeState, KnowledgeTypeEnum
from bisheng.llm.domain.const import LLMModelType
from bisheng.llm.domain.models import LLMDao, LLMModel, LLMServer
from bisheng.llm.domain.models.tenant_system_model_config import TenantSystemModelConfigDao
from bisheng.llm.domain.schemas import (
    AssistantLLMConfig,
    AssistantLLMItem,
    EvaluationLLMConfig,
    KnowledgeLLMConfig,
    LLMModelInfo,
    LLMServerCreateReq,
    LLMServerInfo,
    WorkbenchModelConfig,
    WSModel,
)
from bisheng.llm.domain.share_fallback import avalidate_system_model_refs
from bisheng.tenant.domain.constants import TenantAuditAction
from bisheng.tenant.domain.services.resource_share_service import ResourceShareService
from bisheng.utils import generate_uuid, md5_hash
from bisheng.utils.http_middleware import _check_is_global_super
from bisheng.utils.mask_data import JsonFieldMasker

from ..llm import BishengASR, BishengEmbedding, BishengLLM, BishengTTS
from ..llm.rerank import BishengRerank


def _resolve_tenant_id(tenant_id: int | None) -> int:
    """Pick a tenant_id for system-config DAO calls.

    Precedence: explicit arg > admin-scope ContextVar > Root.
    A warning fires when both are missing — that almost always means a
    Celery worker forgot to thread tenant_id through its task payload
    (INV-T18). The Root fallback keeps the consumer alive but the warn
    surfaces the gap in monitoring.
    """
    if tenant_id is not None:
        return tenant_id
    ctx_tid = get_current_tenant_id()
    if ctx_tid is not None:
        return ctx_tid
    logger.warning(
        "tenant_id missing for system-config call; falling back to "
        "ROOT_TENANT_ID. Likely a Celery worker that omitted tenant_id "
        "(INV-T18). Metric: llm_system_config_tenant_missing_total."
    )
    return ROOT_TENANT_ID


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
                    getattr(workbench_cfg.embedding_model, "id", None),
                    getattr(workbench_cfg.asr_model, "id", None),
                    getattr(workbench_cfg.tts_model, "id", None),
                    getattr(workbench_cfg.chat_title_llm, "id", None),
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
    async def _aget_typed_with_meta(
        cls,
        key: ConfigKeyEnum,
        model_cls,
        tenant_id: int | None,
    ) -> tuple[Any, bool, bool]:
        target = _resolve_tenant_id(tenant_id)
        value, inherited, blocked = await TenantSystemModelConfigDao.aresolve(
            tenant_id=target,
            key=key.value,
        )
        return model_cls(**(json.loads(value) if value else {})), inherited, blocked

    @classmethod
    def _get_typed_sync(
        cls,
        key: ConfigKeyEnum,
        model_cls,
        tenant_id: int | None,
    ):
        target = _resolve_tenant_id(tenant_id)
        value, _, _ = TenantSystemModelConfigDao.resolve(
            tenant_id=target,
            key=key.value,
        )
        return model_cls(**(json.loads(value) if value else {}))

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

        if leaf_id == ROOT_TENANT_ID:
            llm_servers = await LLMDao.aget_all_server()
        else:
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
                LLMDao.aget_shared_server_ids_for_leaf(leaf_id),
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
            if extra_ids:
                with bypass_tenant_filter():
                    shared_servers = await LLMDao.aget_server_by_ids(extra_ids)
                llm_servers = list(own) + list(shared_servers)
            else:
                llm_servers = list(own)

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
        db_server.user_id = login_user.user_id

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
                elif one.model_type == LLMModelType.ASR.value:
                    await cls.get_bisheng_asr(model_id=one.id, ignore_online=True, **common_params)
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
            await LLMDao.adelete_server_by_id(ret.id)
            raise ServerAddAllError.http_exception(failed_msg)
        elif len(success_models) > 0 and failed_msg:
            # Some models added successfully, Delete failed model information
            ret.models = success_models
            await LLMDao.adelete_model_by_ids(model_ids=[one.id for one in failed_models])
            await cls.add_llm_server_hook(request, login_user, ret)
            raise ServerAddError.http_exception(f"<{success_msg.rstrip(',')}>Added{failed_msg}")

        await cls.add_llm_server_hook(request, login_user, ret)
        await _write_llm_audit(
            login_user,
            TenantAuditAction.LLM_SERVER_CREATE.value,
            ret,
            extra={"share_to_children": getattr(server, "share_to_children", True)},
        )
        return ret

    @classmethod
    async def delete_llm_server(cls, request: Request, login_user: UserPayload, server_id: int) -> bool:
        """Delete a service provider"""
        # Snapshot before delete so the audit row preserves name/endpoint.
        with bypass_tenant_filter():
            pre = await LLMDao.aget_server_by_id(server_id)

        await LLMDao.adelete_server_by_id(server_id, operator=login_user)

        if pre is not None:
            await _write_llm_audit(
                login_user,
                TenantAuditAction.LLM_SERVER_DELETE.value,
                pre,
            )
        return True

    @classmethod
    async def add_llm_server_hook(cls, request: Request, login_user: UserPayload, server: LLMServerInfo) -> bool:
        """Add a service provider Next Actions"""

        handle_types = []
        for one in server.models:
            # test model status
            await cls.test_model_status(one, login_user)
            if one.model_type in handle_types:
                continue
            handle_types.append(one.model_type)
            model_info = await LLMDao.aget_model_by_type(LLMModelType(one.model_type))
            # Determine if this is the firstllmorembeddingModels
            if model_info.id == one.id:
                await cls.set_default_model(model_info)
        return True

    @classmethod
    async def test_model_status(cls, model: LLMModel | LLMModelInfo, login_user: UserPayload):
        common_params = {
            "app_id": ApplicationTypeEnum.MODEL_TEST.value,
            "app_name": ApplicationTypeEnum.MODEL_TEST.value,
            "app_type": ApplicationTypeEnum.MODEL_TEST,
            "user_id": login_user.user_id,
        }
        try:
            if model.model_type == LLMModelType.LLM.value:
                bisheng_model = await cls.get_bisheng_llm(model_id=model.id, ignore_online=True, **common_params)
                await bisheng_model.ainvoke("hello")
            elif model.model_type == LLMModelType.EMBEDDING.value:
                bisheng_embed = await cls.get_bisheng_embedding(model_id=model.id, ignore_online=True, **common_params)
                await bisheng_embed.aembed_query("hello")
            elif model.model_type == LLMModelType.TTS.value:
                bisheng_tts = await cls.get_bisheng_tts(model_id=model.id, ignore_online=True, **common_params)
                await bisheng_tts.ainvoke("hello")
            elif model.model_type == LLMModelType.ASR.value:
                example_file_path = os.path.join(os.path.dirname(__file__), "./asr_example.wav")
                with open(example_file_path, "rb") as f:
                    bisheng_asr = await cls.get_bisheng_asr(model_id=model.id, ignore_online=True, **common_params)
                    await bisheng_asr.ainvoke(f)
            elif model.model_type == LLMModelType.RERANK.value:
                bisheng_rerank = await cls.get_bisheng_rerank(model_id=model.id, ignore_online=True, **common_params)
                await bisheng_rerank.acompress_documents(
                    documents=[Document(page_content="hello world")], query="hello"
                )
        except Exception as e:
            LLMDao.update_model_status(model.id, 1, str(e))
            logger.exception(f"test model status: {model.id} {model.model_name}")

    @classmethod
    async def set_default_model(cls, model: LLMModel | LLMModelInfo):
        """Set default model configuration"""
        # Set defaultllmmodel config
        if model.model_type == LLMModelType.LLM.value:
            # Set default model configuration for knowledge base
            knowledge_llm = await cls.aget_knowledge_llm()
            knowledge_change = False
            if not knowledge_llm.extract_title_model_id:
                knowledge_llm.extract_title_model_id = model.id
                knowledge_change = True
            if not knowledge_llm.source_model_id:
                knowledge_llm.source_model_id = model.id
                knowledge_change = True
            if not knowledge_llm.qa_similar_model_id:
                knowledge_llm.qa_similar_model_id = model.id
                knowledge_change = True
            if knowledge_change:
                await cls.update_knowledge_llm(knowledge_llm)

            # Set default model configuration for reviews
            evaluation_llm = await cls.get_evaluation_llm()
            if not evaluation_llm.model_id:
                evaluation_llm.model_id = model.id
                await cls.update_evaluation_llm(evaluation_llm)

            # Setting the default model configuration for the assistant
            assistant_llm = await cls.get_assistant_llm()
            assistant_change = False
            if not assistant_llm.auto_llm:
                assistant_llm.auto_llm = AssistantLLMItem(model_id=model.id)
                assistant_change = True
            if not assistant_llm.llm_list:
                assistant_change = True
                assistant_llm.llm_list = [AssistantLLMItem(model_id=model.id, default=True)]
            if assistant_change:
                await cls.update_assistant_llm(assistant_llm)

            workbench_llm = await cls.get_workbench_llm()
            workbench_change = False
            if not workbench_llm.chat_title_llm:
                workbench_llm.chat_title_llm = WSModel(id=str(model.id), name=model.model_name)
                workbench_change = True
            if workbench_change:
                await cls.update_workbench_llm(0, workbench_llm, BackgroundTasks())

        elif model.model_type == LLMModelType.EMBEDDING.value:
            knowledge_llm = cls.get_knowledge_llm()
            if not knowledge_llm.embedding_model_id:
                knowledge_llm.embedding_model_id = model.id
                await cls.update_knowledge_llm(knowledge_llm)

        elif model.model_type == LLMModelType.TTS.value:
            workbench_llm = await cls.get_workbench_llm()
            if not workbench_llm.tts_model or not workbench_llm.tts_model.id:
                workbench_llm.tts_model = WSModel(id=str(model.id), name=model.model_name)
                await cls.update_workbench_llm(0, workbench_llm, BackgroundTasks())
        elif model.model_type == LLMModelType.ASR.value:
            workbench_llm = await cls.get_workbench_llm()
            if not workbench_llm.asr_model or not workbench_llm.asr_model.id:
                workbench_llm.asr_model = WSModel(id=str(model.id), name=model.model_name)
                await cls.update_workbench_llm(0, workbench_llm, BackgroundTasks())

    @classmethod
    async def update_llm_server(
        cls, request: Request, login_user: UserPayload, server: LLMServerCreateReq
    ) -> LLMServerInfo:
        """Update Service Provider Information"""
        exist_server = await LLMDao.aget_server_by_id(server.id)
        if not exist_server:
            raise NotFoundError.http_exception()

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

        exist_server.name = server.name
        exist_server.description = server.description
        exist_server.type = server.type
        exist_server.limit_flag = server.limit_flag
        exist_server.limit = server.limit
        mask_maker = JsonFieldMasker()
        exist_server.config = mask_maker.update_json_with_masked(exist_server.config, server.config)

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

        # Determine if the model status needs to be re-determined
        for one in new_server_info.models:
            if one.id not in old_model_dict:
                await cls.set_default_model(one)
            # The new model, or the model name or type has changed
            if (
                one.id not in old_model_dict
                or old_model_dict[one.id].model_name != one.model_name
                or old_model_dict[one.id].model_type != one.model_type
            ):
                await cls.test_model_status(one, login_user)
        return new_server_info

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
    def get_knowledge_llm(cls, tenant_id: int | None = None) -> KnowledgeLLMConfig:
        """Default knowledge-base model config for ``tenant_id``.

        ``tenant_id=None`` falls back to the admin-scope ContextVar then
        Root — see ``_resolve_tenant_id``. Sync resolve goes through the
        same Root-share fallback as ``aget_knowledge_llm`` so workflow
        nodes see the same config as API consumers.
        """
        return cls._get_typed_sync(ConfigKeyEnum.KNOWLEDGE_LLM, KnowledgeLLMConfig, tenant_id)

    @classmethod
    async def aget_knowledge_llm(cls, tenant_id: int | None = None) -> KnowledgeLLMConfig:
        """Get the default model configuration for the knowledge base"""
        cfg, _, _ = await cls.aget_knowledge_llm_with_meta(tenant_id)
        return cfg

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
        cls,
        data: dict,
        key: ConfigKeyEnum,
        tenant_id: int | None = None,
    ) -> dict:
        """Persist ``data`` under ``key`` for ``tenant_id``.

        Routes to ``tenant_system_model_config`` (F022). Callers should
        pass an explicit ``tenant_id`` when handling Celery payloads or
        cross-tenant admin actions; otherwise the ContextVar / Root
        fallback in ``_resolve_tenant_id`` applies.
        """
        target = _resolve_tenant_id(tenant_id)
        await TenantSystemModelConfigDao.aupsert(
            tenant_id=target,
            key=key.value,
            value=json.dumps(data, ensure_ascii=False),
        )
        return data

    @classmethod
    async def update_knowledge_llm(
        cls,
        data: KnowledgeLLMConfig,
        tenant_id: int | None = None,
    ) -> KnowledgeLLMConfig:
        """Update default model configuration for knowledge base"""
        target = _resolve_tenant_id(tenant_id)
        await avalidate_system_model_refs(
            [data.embedding_model_id, data.source_model_id, data.extract_title_model_id, data.qa_similar_model_id],
            target,
        )
        await cls._base_update_llm_config(
            data=data.model_dump(),
            key=ConfigKeyEnum.KNOWLEDGE_LLM,
            tenant_id=tenant_id,
        )
        return data

    @classmethod
    async def get_assistant_llm(cls, tenant_id: int | None = None) -> AssistantLLMConfig:
        """Get the default model configuration related to the assistant"""
        cfg, _, _ = await cls.aget_assistant_llm_with_meta(tenant_id)
        return cfg

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
    def sync_get_assistant_llm(cls, tenant_id: int | None = None) -> AssistantLLMConfig:
        """Get the default model configuration related to the assistant"""
        return cls._get_typed_sync(
            ConfigKeyEnum.ASSISTANT_LLM,
            AssistantLLMConfig,
            tenant_id,
        )

    @classmethod
    async def update_assistant_llm(
        cls,
        data: AssistantLLMConfig,
        tenant_id: int | None = None,
    ) -> AssistantLLMConfig:
        """Update default model configurations related to the assistant"""
        target = _resolve_tenant_id(tenant_id)
        ids = [item.model_id for item in (data.llm_list or [])]
        if data.auto_llm:
            ids.append(data.auto_llm.model_id)
        await avalidate_system_model_refs(ids, target)
        await cls._base_update_llm_config(
            data=data.model_dump(),
            key=ConfigKeyEnum.ASSISTANT_LLM,
            tenant_id=tenant_id,
        )
        return data

    @classmethod
    async def get_evaluation_llm(cls, tenant_id: int | None = None) -> EvaluationLLMConfig:
        """Get the default model configuration for the evaluation feature"""
        cfg, _, _ = await cls.aget_evaluation_llm_with_meta(tenant_id)
        return cfg

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
    def sync_get_evaluation_llm(cls, tenant_id: int | None = None) -> EvaluationLLMConfig:
        """Get the default model configuration for the evaluation feature"""
        return cls._get_typed_sync(
            ConfigKeyEnum.EVALUATION_LLM,
            EvaluationLLMConfig,
            tenant_id,
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
        cls,
        data: EvaluationLLMConfig,
        tenant_id: int | None = None,
    ) -> EvaluationLLMConfig:
        """Update default model configuration for review feature"""
        target = _resolve_tenant_id(tenant_id)
        await avalidate_system_model_refs([data.model_id], target)
        await cls._base_update_llm_config(
            data=data.model_dump(),
            key=ConfigKeyEnum.EVALUATION_LLM,
            tenant_id=tenant_id,
        )
        return data

    @classmethod
    async def update_workflow_llm(
        cls,
        data: EvaluationLLMConfig,
        tenant_id: int | None = None,
    ) -> EvaluationLLMConfig:
        """Update workflow Default Model Configuration for"""
        target = _resolve_tenant_id(tenant_id)
        await avalidate_system_model_refs([data.model_id], target)
        await cls._base_update_llm_config(
            data=data.model_dump(),
            key=ConfigKeyEnum.WORKFLOW_LLM,
            tenant_id=tenant_id,
        )
        return data

    @classmethod
    async def get_workflow_llm(cls, tenant_id: int | None = None) -> EvaluationLLMConfig:
        """Get the default model configuration for the evaluation feature"""
        cfg, _, _ = await cls.aget_workflow_llm_with_meta(tenant_id)
        return cfg

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
        assistant_llm = await cls.get_assistant_llm()
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
        invoke_user_id: int,
        config_obj: WorkbenchModelConfig,
        background_tasks: BackgroundTasks,
        tenant_id: int | None = None,
    ):
        """
        Update Invisible Model Configuration
        :param invoke_user_id:
        :param config_obj:
        :param background_tasks:
        :param tenant_id: Owner tenant for the system config row;
            ``None`` falls back to the admin-scope ContextVar then Root.
        :return:
        """
        # Delay imports to avoid looping imports
        from bisheng.worker.knowledge.rebuild_knowledge_worker import rebuild_knowledge_celery

        target = _resolve_tenant_id(tenant_id)
        await avalidate_system_model_refs(
            [
                # linsight_default_model_id is already a model-id string (F035),
                # not a WSModel; pass it directly alongside the WSModel ids.
                config_obj.linsight_default_model_id,
                *(
                    (ws.id if ws else None)
                    for ws in (
                        config_obj.embedding_model,
                        config_obj.asr_model,
                        config_obj.tts_model,
                        config_obj.chat_title_llm,
                    )
                ),
            ],
            target,
        )
        old_value, _, _ = await TenantSystemModelConfigDao.aresolve(
            tenant_id=target,
            key=ConfigKeyEnum.LINSIGHT_LLM.value,
        )
        config_old_obj = WorkbenchModelConfig(**json.loads(old_value)) if old_value else WorkbenchModelConfig()

        if config_obj.embedding_model:
            # Determine consistency
            if (
                config_obj.embedding_model.id and config_old_obj.embedding_model is None
            ) or config_obj.embedding_model.id != (
                config_old_obj.embedding_model.id if config_old_obj.embedding_model else None
            ):
                embeddings = await cls.get_bisheng_embedding(
                    model_id=config_obj.embedding_model.id,
                    app_id=ApplicationTypeEnum.LINSIGHT.value,
                    app_name=ApplicationTypeEnum.LINSIGHT.value,
                    app_type=ApplicationTypeEnum.LINSIGHT,
                    user_id=invoke_user_id,
                )
                try:
                    await embeddings.aembed_query("test")
                except Exception as e:
                    raise Exception(f"EmbeddingModel initialization failed: {e!s}")
                from bisheng.linsight.domain.services.sop_manage import SOPManageService

                background_tasks.add_task(SOPManageService.rebuild_sop_vector_store_task, embeddings)

                # Update Personal Knowledge Base
                # 1.Upgrading alltypeare2(Private Repository)right of privacyknowledgeStatus and Model
                private_knowledges = await KnowledgeDao.aget_all_knowledge(knowledge_type=KnowledgeTypeEnum.SPACE)

                updated_count = 0
                for knowledge in private_knowledges:
                    # Update status is rebuilding, model is newmodel_id
                    knowledge.state = KnowledgeState.REBUILDING.value
                    knowledge.model = config_obj.embedding_model.id
                    await KnowledgeDao.aupdate_one(knowledge)
                    updated_count += 1

                    # 3. For eachknowledgeStart asynchronous task
                    rebuild_knowledge_celery.delay(knowledge.id, int(knowledge.model), invoke_user_id)
                    logger.info(f"Started rebuild task for knowledge_id={knowledge.id} with model_id={knowledge.model}")

                logger.info(
                    f"Updated {updated_count} private knowledge bases to use new embedding model {config_obj.embedding_model.id}"
                )

        await TenantSystemModelConfigDao.aupsert(
            tenant_id=target,
            key=ConfigKeyEnum.LINSIGHT_LLM.value,
            value=json.dumps(config_obj.model_dump(), ensure_ascii=False),
        )

        return config_obj

    @classmethod
    async def get_workbench_llm(cls, tenant_id: int | None = None) -> WorkbenchModelConfig:
        """
        Get Workbench Model Configuration
        """
        cfg, _, _ = await cls.aget_workbench_llm_with_meta(tenant_id)
        return cfg

    @classmethod
    async def aget_workbench_llm_with_meta(
        cls,
        tenant_id: int | None = None,
    ) -> tuple[WorkbenchModelConfig, bool, bool]:
        return await cls._aget_typed_with_meta(
            ConfigKeyEnum.LINSIGHT_LLM,
            WorkbenchModelConfig,
            tenant_id,
        )

    @classmethod
    def get_workbench_llm_sync(cls, tenant_id: int | None = None) -> WorkbenchModelConfig:
        return cls._get_typed_sync(
            ConfigKeyEnum.LINSIGHT_LLM,
            WorkbenchModelConfig,
            tenant_id,
        )

    @classmethod
    async def invoke_workbench_asr(cls, login_user: UserPayload, file: UploadFile) -> str:
        """Call the workbench'sasrModels Convert Voice to Text"""
        if not file:
            raise ServerError.http_exception("no file upload")
        workbench_llm = await cls.get_workbench_llm()
        if not workbench_llm.asr_model or not workbench_llm.asr_model.id:
            raise NoAsrModelConfigError.http_exception()
        model_info = await LLMDao.aget_model_by_id(int(workbench_llm.asr_model.id))
        if not model_info:
            raise AsrModelConfigDeletedError.http_exception()
        asr_client = await cls.get_bisheng_asr(
            model_id=int(workbench_llm.asr_model.id),
            app_id=ApplicationTypeEnum.ASR.value,
            app_name=ApplicationTypeEnum.ASR.value,
            app_type=ApplicationTypeEnum.ASR,
            user_id=login_user.user_id,
        )
        return await asr_client.ainvoke(file.file)

    @classmethod
    async def invoke_workbench_tts(cls, login_user: UserPayload, text: str) -> str:
        """
        Call the workbench'sttsModels Convert text to speech
        :return: minioPath to
        """

        workbench_llm = await cls.get_workbench_llm()

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
        audio_bytes = await tts_client.ainvoke(text)
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
