"""Upload-only preview preparation, isolated from registered file editing."""

import hashlib
import json
from time import time
from uuid import uuid4

from loguru import logger

from bisheng.api.v1.schemas import KnowledgeFileOne, KnowledgeFileProcess
from bisheng.common.errcode.knowledge import (
    KnowledgeOperationPlanChangedError,
    KnowledgeOperationPlanConflictError,
    KnowledgeProcessingJobNotFoundError,
)
from bisheng.core.cache.utils import save_uploaded_file
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.application.file_processing_adapter import (
    legacy_rule_from_snapshot,
    resolve_file_processing_snapshot,
    system_processing_defaults,
)
from bisheng.knowledge.domain.repositories.processing_settings_repository import ProcessingSettingsRepository
from bisheng.knowledge.domain.repositories.upload_preview_repository import FROZEN_PREFIX, UploadPreviewRepository
from bisheng.knowledge.domain.schemas.processing_settings import DocumentProcessingRule, ProcessingOverrides
from bisheng.knowledge.domain.schemas.upload_preview import PreparedUpload
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.knowledge.domain.services.processing_settings_service import ProcessingSettingsService
from bisheng.knowledge.domain.upload_file_size import validate_knowledge_upload_file_size


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class UploadPreviewService:
    def __init__(self, space_service, repository=None):
        self.space_service = space_service
        self.repository = repository or UploadPreviewRepository()

    async def stage(self, space_id, parent_id, file):
        space = await self.space_service.require_upload_container(space_id, parent_id)
        validate_knowledge_upload_file_size(file.filename, file.size)
        name = await KnowledgeService.save_upload_file_original_name(file.filename)
        path = str(await save_uploaded_file(file, "bisheng", name))
        receipt = await self.repository.create(
            {
                "space_id": space_id,
                "parent_id": parent_id,
                "tenant_id": space.tenant_id,
                "actor_user_id": self.space_service.login_user.user_id,
                "file_path": path,
                "file_name": file.filename,
                "state": "OPEN",
                "expires_at": int(time()) + 86400,
                "preview": None,
            }
        )
        return {
            "upload_id": receipt["upload_id"],
            "file_path": path,
            "file_name": file.filename,
            "repeat": False,
            "expires_at": receipt["expires_at"],
        }

    def _owned(self, receipt, space_id, tenant_id):
        if (
            receipt["space_id"] != space_id
            or receipt["tenant_id"] != tenant_id
            or receipt["actor_user_id"] != self.space_service.login_user.user_id
        ):
            raise KnowledgeProcessingJobNotFoundError()

    async def read(self, space_id, upload_id):
        receipt = await self.repository.get(upload_id)
        if receipt["space_id"] != space_id or receipt["actor_user_id"] != self.space_service.login_user.user_id:
            raise KnowledgeProcessingJobNotFoundError()
        # Resolve canonical container facts before trusting any client scope.
        space = await self.space_service.require_upload_container(space_id, receipt["parent_id"])
        self._owned(receipt, space_id, space.tenant_id)
        return receipt

    async def rule(self, receipt, overrides):
        sid = receipt["space_id"]
        with tenant_execution_scope(receipt["tenant_id"]):
            async with get_async_db_session() as session:
                settings = await ProcessingSettingsService(ProcessingSettingsRepository()).get_settings(
                    session, sid, system_defaults=system_processing_defaults(sid)
                )
        defaults = (
            settings.effective_defaults if hasattr(settings, "effective_defaults") else settings["effective_defaults"]
        )
        version = settings.config_version if hasattr(settings, "config_version") else settings["config_version"]
        from bisheng.knowledge.domain.schemas.processing_settings import ProcessingDefaults

        defaults = ProcessingDefaults.model_validate(defaults)
        snapshot = resolve_file_processing_snapshot(
            file_name=receipt["file_name"],
            file_source="file",
            system_defaults=defaults,
            space_defaults=None,
            space_config_version=version,
            file_overrides=overrides,
        )
        return legacy_rule_from_snapshot(snapshot, space_id=sid)

    async def start(self, space_id, upload_id, overrides):
        receipt = await self.read(space_id, upload_id)
        rule = await self.rule(receipt, overrides)
        preview_id = uuid4().hex

        def change(value):
            self._owned(value, space_id, receipt["tenant_id"])
            if value["state"] != "OPEN":
                raise KnowledgeOperationPlanConflictError()
            value["preview"] = {
                "preview_id": preview_id,
                "status": "processing",
                "revision": 0,
                "rule_digest": digest(rule.model_dump(mode="json")),
            }

        await self.repository.mutate(upload_id, change)
        return receipt, rule, preview_id

    async def parse(self, receipt, rule, preview_id):
        upload_id = receipt["upload_id"]
        try:
            with tenant_execution_scope(receipt["tenant_id"]):
                req = KnowledgeFileProcess(
                    **rule.model_dump(),
                    file_list=[KnowledgeFileOne(file_path=receipt["file_path"], excel_rule=rule.excel_rule)],
                )
                parse_type, url, chunks, partitions = await KnowledgeService.parse_staged_file(
                    self.space_service.login_user, req, cache_key=f"space_upload_preview:{upload_id}:{preview_id}"
                )
            result = {
                "parse_type": parse_type,
                "file_url": url,
                "chunks": [c.model_dump(mode="json") for c in chunks],
                "partitions": partitions,
            }
            status = "completed"
        except Exception:
            logger.exception("Upload preview parsing failed for upload={}", upload_id)
            status, result = "error", {"code": 10952}

        def finish(value):
            preview = value.get("preview")
            if value["state"] == "OPEN" and preview and preview["preview_id"] == preview_id:
                preview.update(status=status, data=result)

        await self.repository.mutate(upload_id, finish)

    @staticmethod
    def preview(receipt, preview_id):
        preview = receipt.get("preview")
        if not preview or preview["preview_id"] != preview_id:
            raise KnowledgeOperationPlanChangedError()
        return preview

    async def edit(self, space_id, upload_id, preview_id, index, revision, update):
        receipt = await self.read(space_id, upload_id)

        def change(value):
            self._owned(value, space_id, receipt["tenant_id"])
            preview = self.preview(value, preview_id)
            if value["state"] != "OPEN" or preview["status"] != "completed" or preview["revision"] != revision:
                raise KnowledgeOperationPlanChangedError()
            chunks = preview["data"]["chunks"]
            found = next((c for c in chunks if c["metadata"]["chunk_index"] == index), None)
            if found is None:
                raise KnowledgeProcessingJobNotFoundError()
            if update is None:
                if len(chunks) <= 1:
                    raise KnowledgeOperationPlanChangedError()
                chunks.remove(found)
            else:
                found["text"] = update.text
                found["metadata"]["bbox"] = update.bbox
            preview["revision"] += 1

        value = await self.repository.mutate(upload_id, change)
        return value["preview"]

    async def freeze(self, receipt, item, mode, request_digest):
        rule = await self.rule(receipt, item.overrides)
        # Pin every resolved field, including defaults omitted by sparse clients.
        # A settings change between freeze and SQL preparation must not alter it.
        effective = ProcessingOverrides.model_validate(
            {
                "document": rule.model_dump(include=set(DocumentProcessingRule.model_fields)),
                "table": rule.excel_rule.model_dump(mode="json"),
            }
        )
        cache_key = FROZEN_PREFIX + uuid4().hex

        def change(value):
            self._owned(value, receipt["space_id"], receipt["tenant_id"])
            if value["state"] != "OPEN":
                raise KnowledgeOperationPlanConflictError()
            chunks = None
            if mode == "previewed" and value.get("preview"):
                preview = self.preview(value, item.preview_id)
                if (
                    preview["status"] != "completed"
                    or preview["revision"] != item.expected_revision
                    or preview["rule_digest"] != digest(rule.model_dump(mode="json"))
                ):
                    raise KnowledgeOperationPlanChangedError()
                chunks = preview["data"]["chunks"]
                if not chunks:
                    raise KnowledgeOperationPlanChangedError()
            elif item.preview_id is not None and mode != "direct":
                raise KnowledgeOperationPlanChangedError()
            value.update(
                state="COMMITTING", request_digest=request_digest, frozen_cache_key=cache_key if chunks else ""
            )
            return (cache_key, chunks) if chunks else None

        value = await self.repository.mutate(receipt["upload_id"], change)
        return PreparedUpload(overrides=effective, cache_key=value["frozen_cache_key"])
