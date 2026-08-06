"""跨知识库迁移的管理员命令、查询和幂等批次服务。"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import uuid4

from fastapi import HTTPException, status

from bisheng.common.errcode.knowledge_migration import (
    KnowledgeMigrationCandidateInvalidError,
    KnowledgeMigrationInvalidRequestError,
    KnowledgeMigrationNotFoundError,
    KnowledgeMigrationStateConflictError,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.models.knowledge_migration import (
    KnowledgeMigrationBatch,
    KnowledgeMigrationBatchStatus,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_migration_repository import (
    KnowledgeMigrationRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_migration_source_repository import (
    KnowledgeMigrationSourceRepository,
    MigrationSpaceRecord,
)
from bisheng.knowledge.domain.schemas.knowledge_migration_schema import (
    MigrationAttemptResponse,
    MigrationBatchCreateRequest,
    MigrationBatchResponse,
    MigrationChildResponse,
    MigrationFileResponse,
    MigrationPageResponse,
    MigrationSpaceResponse,
    MigrationUnitResponse,
)
from bisheng.knowledge.domain.services.file_migration.planner import (
    MigrationNode,
    MigrationSelection,
    normalize_selections,
)


class KnowledgeMigrationTaskDispatcher(Protocol):
    def dispatch_preflight(self, batch_id: int) -> str | None: ...
    def dispatch_execution(self, batch_id: int, round_no: int) -> str | None: ...


class CeleryKnowledgeMigrationTaskDispatcher:
    def dispatch_preflight(self, batch_id: int) -> str | None:
        from bisheng.worker.knowledge.file_migration import preflight_knowledge_migration

        task = preflight_knowledge_migration.apply_async(
            args=[batch_id],
            queue="celery",
        )
        return str(task.id) if task.id else None

    def dispatch_execution(self, batch_id: int, round_no: int) -> str | None:
        from bisheng.worker.knowledge.file_migration import execute_knowledge_migration

        task = execute_knowledge_migration.apply_async(
            args=[batch_id, round_no],
            queue="celery",
        )
        return str(task.id) if task.id else None


def require_system_admin(login_user: Any):
    """只接受后端 AdminRole. 不接受账号名或展示角色旁路."""
    is_admin = getattr(login_user, "is_admin", None)
    if login_user is None or not callable(is_admin) or not bool(is_admin()):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System administrator access required",
        )
    return login_user


def _encode_cursor(name: str, node_id: int) -> str:
    raw = json.dumps([name, node_id], ensure_ascii=False, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> tuple[str, int] | None:
    if not cursor:
        return None
    try:
        padding = "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(f"{cursor}{padding}").decode())
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError
        return str(value[0]), int(value[1])
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise KnowledgeMigrationInvalidRequestError(msg="invalid migration cursor") from exc


def sanitize_error_summary(value: str | None) -> str | None:
    if not value:
        return value
    sanitized = re.sub(
        r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+",
        r"\1 [redacted]",
        value,
    )
    sanitized = re.sub(
        r"(?i)\b(token|password|passwd|secret|access[_-]?key|api[_-]?key)"
        r"\s*[:=]\s*[^\s,;]+",
        r"\1=[redacted]",
        sanitized,
    )
    sanitized = re.sub(r"https?://\S+", "[url]", sanitized)
    sanitized = re.sub(r"(?:/[A-Za-z0-9_.-]+){2,}", "[path]", sanitized)
    sanitized = re.sub(
        r"\b(?:original|preview|partitions|migration/thumbnails|knowledge/images)"
        r"/[A-Za-z0-9_./-]+",
        "[object-key]",
        sanitized,
    )
    sanitized = sanitized.splitlines()[0]
    return sanitized[:1000]


def _public_overwrite_snapshot(
    snapshot: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not snapshot:
        return snapshot
    return {
        "unit_key": snapshot.get("unit_key"),
        "matched_by": list(snapshot.get("matched_by") or []),
        "target_files": [
            {
                "id": item.get("record", {}).get("id"),
                "knowledge_id": item.get("record", {}).get("knowledge_id"),
                "file_name": item.get("record", {}).get("file_name"),
                "file_level_path": item.get("record", {}).get("file_level_path"),
                "md5": item.get("record", {}).get("md5"),
                "reference_document_id": item.get("record", {}).get(
                    "reference_document_id"
                ),
                "document_id": (item.get("version") or {}).get(
                    "document_id"
                ),
                "version_id": (item.get("version") or {}).get("version_id"),
                "version_no": (item.get("version") or {}).get("version_no"),
                "is_primary": (item.get("version") or {}).get("is_primary"),
            }
            for item in snapshot.get("target_files") or []
        ],
    }


@dataclass(frozen=True)
class NormalizedBatchInput:
    selections: list[dict[str, Any]]
    source_spaces: list[MigrationSpaceRecord]
    target_space: MigrationSpaceRecord
    target_folder_name: str | None
    target_path: str


class KnowledgeMigrationService:
    def __init__(
        self,
        *,
        repository: KnowledgeMigrationRepository,
        source_repository: KnowledgeMigrationSourceRepository,
        dispatcher: KnowledgeMigrationTaskDispatcher | None = None,
    ):
        self.repository = repository
        self.source_repository = source_repository
        self.dispatcher = dispatcher or CeleryKnowledgeMigrationTaskDispatcher()

    @staticmethod
    def _batch_response(batch: KnowledgeMigrationBatch) -> MigrationBatchResponse:
        return MigrationBatchResponse(
            batch_no=batch.batch_no,
            request_id=batch.request_id,
            operator_id=batch.operator_id,
            operator_name=batch.operator_name,
            source_selection=batch.source_selection_snapshot,
            source_spaces=batch.source_spaces_snapshot,
            target_space_id=batch.target_space_id,
            target_space_name=batch.target_space_name,
            target_folder_id=batch.target_folder_id,
            target_folder_name=batch.target_folder_name,
            target_path=batch.target_path_snapshot,
            conflict_strategy=batch.conflict_strategy,
            preserve_structure=batch.preserve_structure,
            status=batch.status,
            current_stage=batch.current_stage,
            round_no=batch.round_no,
            scanned_count=batch.scanned_count,
            total_count=batch.total_count,
            executable_count=batch.executable_count,
            completed_count=batch.completed_count,
            succeeded_count=batch.succeeded_count,
            skipped_count=batch.skipped_count,
            failed_count=batch.failed_count,
            unprocessed_count=batch.unprocessed_count,
            overwrite_target_count=batch.overwrite_target_count,
            last_error_code=batch.last_error_code,
            last_error_summary=sanitize_error_summary(batch.last_error_summary),
            confirmed_by=batch.confirmed_by,
            confirmed_at=batch.confirmed_at,
            abandoned_by=batch.abandoned_by,
            abandoned_at=batch.abandoned_at,
            create_time=batch.create_time,
            started_at=batch.started_at,
            finished_at=batch.finished_at,
        )

    async def list_spaces(
        self,
        login_user: Any,
        *,
        keyword: str | None,
        space_level: str | None,
        page: int,
        page_size: int,
    ) -> MigrationPageResponse:
        require_system_admin(login_user)
        rows, total = await self.source_repository.list_spaces(
            keyword=keyword.strip() if keyword else None,
            level=space_level,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return MigrationPageResponse(
            data=[
                MigrationSpaceResponse(
                    id=int(row.space.id),
                    name=row.space.name,
                    level=row.level,
                    owner_valid=row.owner_id > 0,
                    selectable=row.owner_id > 0,
                ).model_dump()
                for row in rows
            ],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def list_children(
        self,
        login_user: Any,
        *,
        space_id: int,
        parent_id: int | None,
        cursor: str | None,
        page_size: int,
        purpose: str,
    ) -> dict[str, Any]:
        require_system_admin(login_user)
        spaces = await self.source_repository.find_spaces_by_ids({space_id})
        if not spaces:
            raise KnowledgeMigrationCandidateInvalidError(msg="knowledge space is not migratable")
        rows = await self.source_repository.list_children(
            space_id=space_id,
            parent_id=parent_id,
            after=_decode_cursor(cursor),
            limit=page_size + 1,
            folders_only=purpose == "target",
        )
        page_rows = rows[:page_size]
        data = []
        for row in page_rows:
            item = row.file
            is_folder = item.file_type == FileType.DIR.value
            unavailable_reason = None
            selectable = is_folder or (
                item.status == KnowledgeFileStatus.SUCCESS.value
                and item.entry_type
                not in {
                    KnowledgeFileEntryType.PUBLISH.value,
                    KnowledgeFileEntryType.SHARE.value,
                    KnowledgeFileEntryType.PROJECTION_TOMBSTONE.value,
                }
                and (
                    item.entry_type != KnowledgeFileEntryType.MANAGER.value
                    or item.entry_status == KnowledgeFileEntryStatus.ACTIVE.value
                )
            )
            if not selectable:
                unavailable_reason = "当前记录不是可迁移的 SUCCESS 物理文件"
            data.append(
                MigrationChildResponse(
                    id=int(item.id),
                    name=item.file_name,
                    node_type="folder" if is_folder else "file",
                    selectable=selectable,
                    unavailable_reason=unavailable_reason,
                    has_children=row.has_children,
                    status=item.status,
                ).model_dump()
            )
        has_more = len(rows) > page_size
        return {
            "data": data,
            "page_size": page_size,
            "has_more": has_more,
            "next_cursor": (
                _encode_cursor(page_rows[-1].file.file_name, int(page_rows[-1].file.id))
                if has_more and page_rows
                else None
            ),
        }

    async def _normalize_create(
        self,
        request: MigrationBatchCreateRequest,
    ) -> NormalizedBatchInput:
        source_space_ids = {selection.space_id for selection in request.source_selections}
        if request.target_space_id in source_space_ids:
            raise KnowledgeMigrationInvalidRequestError(
                msg="target knowledge space cannot also be a source"
            )
        all_spaces = await self.source_repository.find_spaces_by_ids(
            source_space_ids | {request.target_space_id}
        )
        spaces_by_id = {int(row.space.id): row for row in all_spaces}
        if set(spaces_by_id) != source_space_ids | {request.target_space_id}:
            raise KnowledgeMigrationCandidateInvalidError(
                msg="one or more knowledge spaces are not migratable"
            )
        if any(spaces_by_id[space_id].owner_id <= 0 for space_id in spaces_by_id):
            raise KnowledgeMigrationCandidateInvalidError(msg="knowledge space owner is invalid")

        normalized_inputs: list[MigrationSelection] = []
        nodes_by_space: dict[int, dict[int, Any]] = {}
        for selection in request.source_selections:
            requested_ids = {node.node_id for node in selection.nodes}
            records = await self.source_repository.find_nodes(
                space_id=selection.space_id,
                node_ids=requested_ids,
            )
            if len(records) != len(requested_ids):
                raise KnowledgeMigrationCandidateInvalidError(
                    msg=f"source nodes do not belong to space {selection.space_id}"
                )
            records_by_id = {int(item.id): item for item in records}
            nodes_by_space.setdefault(selection.space_id, {}).update(
                records_by_id
            )
            normalized_nodes = []
            for node in selection.nodes:
                record = records_by_id[node.node_id]
                actual_type = "folder" if record.file_type == FileType.DIR.value else "file"
                if actual_type != node.node_type:
                    raise KnowledgeMigrationCandidateInvalidError(
                        msg=f"source node type mismatch: {node.node_id}"
                    )
                ancestors = tuple(
                    int(part)
                    for part in (record.file_level_path or "").split("/")
                    if part.isdigit()
                )
                normalized_nodes.append(
                    MigrationNode(
                        node_type=node.node_type,
                        node_id=node.node_id,
                        ancestor_folder_ids=ancestors,
                    )
                )
            normalized_inputs.append(
                MigrationSelection(selection.space_id, tuple(normalized_nodes))
            )
        normalized = normalize_selections(normalized_inputs)
        if not normalized:
            raise KnowledgeMigrationInvalidRequestError(msg="source selection is empty")

        snapshots: list[dict[str, Any]] = []
        for selection in normalized:
            records_by_id = nodes_by_space[selection.space_id]
            snapshots.append(
                {
                    "space_id": selection.space_id,
                    "nodes": [
                        {
                            "node_type": node.node_type,
                            "node_id": node.node_id,
                            "name": records_by_id[node.node_id].file_name,
                            "file_level_path": records_by_id[node.node_id].file_level_path or "",
                        }
                        for node in selection.nodes
                    ],
                }
            )

        target_folder_name = None
        target_path = "/"
        if request.target_folder_id is not None:
            target_nodes = await self.source_repository.find_nodes(
                space_id=request.target_space_id,
                node_ids={request.target_folder_id},
            )
            if (
                len(target_nodes) != 1
                or target_nodes[0].file_type != FileType.DIR.value
            ):
                raise KnowledgeMigrationCandidateInvalidError(msg="target folder is invalid")
            target_folder = target_nodes[0]
            target_folder_name = target_folder.file_name
            target_path = f"{target_folder.file_level_path or ''}/{target_folder.id}"

        return NormalizedBatchInput(
            selections=snapshots,
            source_spaces=[spaces_by_id[space_id] for space_id in sorted(source_space_ids)],
            target_space=spaces_by_id[request.target_space_id],
            target_folder_name=target_folder_name,
            target_path=target_path,
        )

    async def create_batch(
        self,
        login_user: Any,
        request: MigrationBatchCreateRequest,
    ) -> MigrationBatchResponse:
        require_system_admin(login_user)
        normalized = await self._normalize_create(request)
        target = normalized.target_space
        batch = KnowledgeMigrationBatch(
            batch_no=str(uuid4()),
            request_id=request.request_id,
            operator_id=int(login_user.user_id),
            operator_name=str(getattr(login_user, "user_name", "") or login_user.user_id),
            source_selection_snapshot=normalized.selections,
            source_spaces_snapshot=[
                {
                    "id": int(row.space.id),
                    "name": row.space.name,
                    "level": row.level,
                    "model": row.space.model,
                }
                for row in normalized.source_spaces
            ],
            target_space_id=int(target.space.id),
            target_space_name=target.space.name,
            target_space_level=target.level,
            target_folder_id=request.target_folder_id,
            target_folder_name=normalized.target_folder_name,
            target_path_snapshot=normalized.target_path,
            conflict_strategy=request.conflict_strategy,
            preserve_structure=request.preserve_structure,
        )
        saved, created = await self.repository.create_batch_idempotent(batch)
        await self.repository.commit()
        if created:
            try:
                task_id = self.dispatcher.dispatch_preflight(int(saved.id))
                if task_id:
                    saved.preflight_task_id = task_id
                    await self.repository.commit()
            except Exception as exc:
                saved.last_error_code = "preflight_dispatch_failed"
                saved.last_error_summary = sanitize_error_summary(str(exc))
                await self.repository.commit()
        return self._batch_response(saved)

    async def list_batches(
        self,
        login_user: Any,
        *,
        page: int,
        page_size: int,
        status_filter: str | None,
    ) -> MigrationPageResponse:
        require_system_admin(login_user)
        result = await self.repository.list_batches(
            page=page,
            page_size=page_size,
            status=status_filter,
        )
        return MigrationPageResponse(
            data=[self._batch_response(item).model_dump() for item in result.items],
            total=result.total,
            page=result.page,
            page_size=result.page_size,
        )

    async def _get_batch(self, batch_no: str) -> KnowledgeMigrationBatch:
        batch = await self.repository.find_batch_by_no(batch_no)
        if batch is None:
            raise KnowledgeMigrationNotFoundError()
        return batch

    async def get_batch(self, login_user: Any, batch_no: str) -> MigrationBatchResponse:
        require_system_admin(login_user)
        return self._batch_response(await self._get_batch(batch_no))

    async def list_units(
        self,
        login_user: Any,
        batch_no: str,
        *,
        page: int,
        page_size: int,
        status_filter: str | None,
    ) -> MigrationPageResponse:
        require_system_admin(login_user)
        batch = await self._get_batch(batch_no)
        result = await self.repository.list_units(
            int(batch.id),
            page=page,
            page_size=page_size,
            status=status_filter,
        )
        items = []
        for unit in result.items:
            files = await self.repository.list_files(int(unit.id))
            items.append(
                MigrationUnitResponse(
                    id=int(unit.id),
                    unit_key=unit.unit_key,
                    unit_type=unit.unit_type,
                    source_document_id=unit.source_document_id,
                    target_document_id=unit.target_document_id,
                    source_space_id=unit.source_space_id,
                    source_space_name=unit.source_space_name,
                    source_path=unit.source_path_snapshot,
                    planned_target_path=unit.planned_target_path_snapshot,
                    status=unit.status,
                    checkpoint=unit.checkpoint,
                    reason_code=unit.reason_code,
                    summary=sanitize_error_summary(unit.summary),
                    overwrite_unit_key=unit.overwrite_unit_key,
                    overwrite_snapshot=_public_overwrite_snapshot(
                        unit.overwrite_snapshot
                    ),
                    folder_mapping=unit.folder_mapping_snapshot or [],
                    attempt_count=unit.attempt_count,
                    files=[
                        MigrationFileResponse(
                            id=int(file_row.id),
                            source_file_id=file_row.source_file_id,
                            source_document_id=file_row.source_document_id,
                            source_version_id=file_row.source_version_id,
                            source_file_name=file_row.source_file_name,
                            source_space_id=file_row.source_space_id,
                            source_space_name=file_row.source_space_name,
                            source_path=file_row.source_path_snapshot,
                            source_version_no=file_row.source_version_no,
                            is_primary=file_row.is_primary,
                            target_file_id=file_row.target_file_id,
                            target_space_id=file_row.target_space_id,
                            target_space_name=file_row.target_space_name,
                            target_path=file_row.target_path_snapshot,
                            target_file_name=file_row.target_file_name,
                            status=file_row.status,
                            checkpoint=file_row.checkpoint,
                            reason_code=file_row.reason_code,
                            summary=sanitize_error_summary(file_row.summary),
                        )
                        for file_row in files
                    ],
                ).model_dump()
            )
        return MigrationPageResponse(
            data=items,
            total=result.total,
            page=result.page,
            page_size=result.page_size,
        )

    async def list_attempts(
        self,
        login_user: Any,
        batch_no: str,
        *,
        page: int,
        page_size: int,
    ) -> MigrationPageResponse:
        require_system_admin(login_user)
        batch = await self._get_batch(batch_no)
        result = await self.repository.list_attempts(
            int(batch.id),
            page=page,
            page_size=page_size,
        )
        return MigrationPageResponse(
            data=[
                MigrationAttemptResponse(
                    id=int(item.id),
                    unit_id=item.unit_id,
                    round_no=item.round_no,
                    attempt_no=item.attempt_no,
                    start_checkpoint=item.start_checkpoint,
                    end_checkpoint=item.end_checkpoint,
                    result=item.result,
                    reason_code=item.reason_code,
                    error_summary=sanitize_error_summary(item.error_summary),
                    started_at=item.started_at,
                    finished_at=item.finished_at,
                ).model_dump()
                for item in result.items
            ],
            total=result.total,
            page=result.page,
            page_size=result.page_size,
        )

    async def confirm_overwrite(
        self,
        login_user: Any,
        batch_no: str,
    ) -> MigrationBatchResponse:
        require_system_admin(login_user)
        batch = await self._get_batch(batch_no)
        if batch.status == KnowledgeMigrationBatchStatus.QUEUED.value and batch.confirmed_at:
            return self._batch_response(batch)
        now = datetime.now()
        changed = await self.repository.compare_and_set_batch_status(
            int(batch.id),
            {KnowledgeMigrationBatchStatus.AWAITING_CONFIRMATION.value},
            KnowledgeMigrationBatchStatus.QUEUED.value,
            confirmed_by=int(login_user.user_id),
            confirmed_at=now,
            queued_at=now,
        )
        if not changed:
            raise KnowledgeMigrationStateConflictError()
        await self.repository.commit()
        try:
            task_id = self.dispatcher.dispatch_execution(
                int(batch.id),
                batch.round_no,
            )
            if task_id:
                batch.execution_task_id = task_id
                await self.repository.commit()
        except Exception as exc:
            batch.last_error_code = "execution_dispatch_failed"
            batch.last_error_summary = sanitize_error_summary(str(exc))
            await self.repository.commit()
        return self._batch_response(await self._get_batch(batch_no))

    async def abandon(
        self,
        login_user: Any,
        batch_no: str,
    ) -> MigrationBatchResponse:
        require_system_admin(login_user)
        batch = await self._get_batch(batch_no)
        if batch.status == KnowledgeMigrationBatchStatus.ABANDONED.value:
            return self._batch_response(batch)
        now = datetime.now()
        changed = await self.repository.compare_and_set_batch_status(
            int(batch.id),
            {KnowledgeMigrationBatchStatus.AWAITING_CONFIRMATION.value},
            KnowledgeMigrationBatchStatus.ABANDONED.value,
            abandoned_by=int(login_user.user_id),
            abandoned_at=now,
            finished_at=now,
        )
        if not changed:
            raise KnowledgeMigrationStateConflictError()
        await self.repository.commit()
        return self._batch_response(await self._get_batch(batch_no))

    async def retry(
        self,
        login_user: Any,
        batch_no: str,
    ) -> MigrationBatchResponse:
        require_system_admin(login_user)
        batch = await self._get_batch(batch_no)
        retried = await self.repository.retry_batch(int(batch.id), queued_at=datetime.now())
        if retried is None:
            raise KnowledgeMigrationStateConflictError()
        await self.repository.commit()
        try:
            task_id = self.dispatcher.dispatch_execution(
                int(retried.id),
                retried.round_no,
            )
            if task_id:
                retried.execution_task_id = task_id
                await self.repository.commit()
        except Exception as exc:
            retried.last_error_code = "execution_dispatch_failed"
            retried.last_error_summary = sanitize_error_summary(str(exc))
            await self.repository.commit()
        return self._batch_response(retried)

    async def soft_delete(self, login_user: Any, batch_no: str) -> dict[str, bool]:
        require_system_admin(login_user)
        batch = await self._get_batch(batch_no)
        changed = await self.repository.soft_delete_batch(
            int(batch.id),
            deleted_by=int(login_user.user_id),
            deleted_at=datetime.now(),
        )
        if not changed:
            raise KnowledgeMigrationStateConflictError()
        await self.repository.commit()
        return {"deleted": True}
