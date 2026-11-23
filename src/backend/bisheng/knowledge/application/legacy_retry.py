"""Live duplicate overwrite through existing file actions and retry worker."""

import json
from copy import deepcopy

from loguru import logger

from bisheng.api.v1.schemas import FileProcessBase
from bisheng.common.errcode.knowledge import (
    KnowledgeOperationConfirmationRequiredError,
    KnowledgeProcessingConflictError,
)
from bisheng.core.context.tenant import (
    get_admin_scope_tenant_id,
    get_current_tenant_id,
    get_is_management_api,
    get_visible_tenant_ids,
    is_tenant_filter_bypassed,
)
from bisheng.core.database import get_async_db_session
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.knowledge.application.file_processing_adapter import (
    resolve_file_processing_snapshot,
    system_processing_defaults,
)
from bisheng.knowledge.application.knowledge_processing_commands import KnowledgeProcessingCommands
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KNOWLEDGE_FILE_NAME_MAX_LENGTH
from bisheng.knowledge.domain.repositories.legacy_retry_repository import LegacyRetryRepository, blocked
from bisheng.knowledge.domain.schemas.processing_job import ProcessingCreateRequest
from bisheng.knowledge.domain.schemas.processing_settings import EffectiveProcessingSnapshot
from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils
from bisheng.permission.application.business_authorization import batch_check_business_actions, require_business_action
from bisheng.permission.application.identity import get_current_permission_actor
from bisheng.resource_reference.application.read_identity import AuthenticatedSourceReadIdentity


def _scope():
    return (
        get_current_tenant_id(),
        get_admin_scope_tenant_id(),
        get_is_management_api(),
        get_visible_tenant_ids(),
        is_tenant_filter_bypassed(),
        get_current_permission_actor(),
    )


class LegacyRetryApplication:
    def __init__(self, *, session_factory=None, repository=None, commands=None):
        self.sessions = session_factory or get_async_db_session
        self.repo = repository or LegacyRetryRepository()
        self.commands = commands
        self.identity = AuthenticatedSourceReadIdentity()

    @staticmethod
    def _inputs(req_data):
        value = deepcopy(req_data)
        if type(value) is not dict:
            blocked("invalid_request")
        items = value.get("file_objs")
        if items is None:
            items = []
        if type(items) is not list:
            blocked("invalid_request")
        by_id = {}
        for item in items:
            if (
                type(item) is not dict
                or type(item.get("id")) is not int
                or not 0 < item["id"] <= 2**63 - 1
                or item["id"] in by_id
            ):
                blocked("invalid_file_id")
            by_id[item["id"]] = item
        return value, by_id

    async def aretry(self, *, request, identity, req_data, space_id):
        command, items = self._inputs(req_data)
        if not items:
            return Knowledge(id=space_id), [], set()
        pin = _scope()
        if type(pin[0]) is not int or pin[0] <= 0 or pin[4]:
            blocked("tenant_required")
        original = await self.identity.acapture(identity)

        def current():
            if _scope() != pin:
                blocked("identity_changed")

        async def guard():
            current()
            if await self.identity.acapture(identity) != original:
                blocked("identity_changed")
            current()

        async def authorize():
            ids = sorted(items)
            for start in range(0, len(ids), 200):
                await guard()
                actions = await batch_check_business_actions(
                    identity, resource_type="knowledge_file", resource_ids=ids[start : start + 200], actions=("rename",)
                )
                await guard()
                if any("rename" not in actions.get(str(ident), ()) for ident in ids[start : start + 200]):
                    from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError

                    raise SpacePermissionDeniedError()

        confirmed = all(command.get(name) for name in ("confirmation_id", "plan_digest", "idempotency_key"))
        await guard()
        async with self.sessions() as session, session.begin():
            await session.connection()
            current()
            before = await self.repo.aread(
                session,
                space_id=space_id,
                file_ids=sorted(items),
                allow_processing=confirmed,
            )
            current()
        if command.get("knowledge_id", space_id) != space_id:
            blocked("space_mismatch")
        await authorize()
        patches, copies, cache_keys, advanced = self._prepare(before, items)
        if advanced or confirmed:
            if copies or any(patches[ident]["file_name"] != before["files"][ident]["file_name"] for ident in patches):
                blocked("mixed_advanced_and_overwrite")
            if not all(command.get(name) for name in ("confirmation_id", "plan_digest", "idempotency_key")):
                raise KnowledgeOperationConfirmationRequiredError()
            await require_business_action(
                identity, resource_type="knowledge_space", resource_id=space_id, action="edit"
            )
            await guard()
            commands = self.commands or KnowledgeProcessingCommands()
            confirmation = ProcessingCreateRequest.model_validate(
                {name: command[name] for name in ("confirmation_id", "plan_digest", "idempotency_key")}
            )
            async with commands.sessions() as session:
                plan = await commands.service.plans._locked(session, confirmation.confirmation_id)
                if plan.operation not in {"file_reprocess", "file_resplit"} or {
                    row["file_id"] for row in plan.target_manifest
                } != set(items):
                    blocked("advanced_scope_changed")
            await guard()
            accepted = await commands.aconfirm(space_id, confirmation, identity=identity)
            await guard()
            return accepted
        storage = await get_minio_storage() if copies else None
        await guard()
        for source, target in copies:
            await guard()
            await storage.copy_object(
                source_object=source, dest_object=target, source_bucket=storage.tmp_bucket, dest_bucket=storage.bucket
            )
            await guard()
        await authorize()
        async with self.sessions() as session, session.begin():
            await session.connection()
            current()
            after = await self.repo.aread(session, space_id=space_id, file_ids=sorted(items), lock=True)
            current()
            self.repo.same(before, after)
            files = await self.repo.awrite(session, scope=after, patches=patches, identity=identity)
            current()
        await guard()
        from bisheng.worker.knowledge.file_worker import retry_knowledge_file_celery

        uncertain = False
        for file in files:
            current()
            try:
                retry_knowledge_file_celery.delay(file.id, cache_keys[file.id], None)
            except Exception:
                logger.exception("Legacy retry broker acknowledgement is unknown file_id={}", file.id)
                uncertain = True
            current()
        if uncertain:
            raise KnowledgeProcessingConflictError(reason="legacy_retry_pending_dispatch")
        await guard()
        return Knowledge(**before["root"]), files, {file.file_level_path for file in files if file.file_level_path}

    @staticmethod
    def _prepare(scope, items):
        patches, copies, cache_keys, advanced = {}, [], {}, False
        root = scope["root"]
        for ident, item in items.items():
            row = scope["files"][ident]
            if "file_level_path" in item and (item["file_level_path"] or "") != (row["file_level_path"] or ""):
                blocked("parent_changed")
            if "knowledge_id" in item and item["knowledge_id"] != root["id"]:
                blocked("space_mismatch")
            source = item.get("object_name", row["object_name"])
            name = row["file_name"]
            remark = item.get("remark")
            if remark:
                try:
                    metadata = json.loads(remark)
                except (TypeError, ValueError):
                    # Legacy plain-text error remarks do not rename a file.
                    logger.debug("Legacy retry keeps the name for a non-JSON remark")
                    metadata = {}
                if type(metadata) is dict and metadata.get("new_name"):
                    name = metadata["new_name"]
            if (
                type(name) is not str
                or not name
                or len(name) > KNOWLEDGE_FILE_NAME_MAX_LENGTH
                or "/" in name
                or "\\" in name
            ):
                blocked("invalid_name")
            staged = type(source) is str and source.startswith("tmp/")
            if not staged and source != row["object_name"]:
                blocked("invalid_object")
            target = source
            if staged:
                target = KnowledgeUtils.get_knowledge_file_object_name(ident, name)
                expected_tmp = "tmp/" + target.removeprefix("original/")
                suffix = name.rsplit(".", 1)[-1]
                if source != expected_tmp or not suffix.isascii() or not suffix.isalnum():
                    blocked("invalid_object")
                copies.append((source, target))
            raw = item.get("split_rule", row["split_rule"])
            if type(raw) is not str:
                blocked("invalid_rule")
            try:
                payload = json.loads(raw)
                if (
                    type(payload) is not dict
                    or type(payload.get("knowledge_id")) is not int
                    or payload["knowledge_id"] != root["id"]
                ):
                    blocked("rule_space_mismatch")
                FileProcessBase.model_validate(deepcopy(payload))
                marker = payload.get("_effective_processing")
                snapshot = EffectiveProcessingSnapshot.model_validate(marker) if marker is not None else None
                effective = resolve_file_processing_snapshot(
                    file_name=name,
                    file_source=row["file_source"],
                    system_defaults=system_processing_defaults(root["id"]),
                    space_defaults=None,
                    space_config_version=snapshot.space_config_version
                    if snapshot is not None
                    else root["processing_config_version"],
                    legacy_split_rule=payload,
                )
                if snapshot is not None and (
                    snapshot.file_kind != effective.file_kind or snapshot.effective_rule != effective.effective_rule
                ):
                    blocked("rule_snapshot_changed")
            except (TypeError, ValueError) as error:
                blocked("invalid_rule:" + type(error).__name__)
            if not staged and (raw != row["split_rule"] or row["status"] == 2):
                advanced = True
            cache_keys[ident] = KnowledgeUtils.preview_cache_key_for_split_rule(
                root["id"], item.get("file_path", ""), json.loads(row["split_rule"]) if row["split_rule"] else {}
            )
            patches[ident] = {"file_name": name, "object_name": target, "split_rule": raw}
        return patches, copies, cache_keys, advanced


def get_legacy_retry_application():
    return LegacyRetryApplication()
