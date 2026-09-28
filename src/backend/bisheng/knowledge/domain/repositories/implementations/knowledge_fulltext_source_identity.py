"""全文普通消费与对账共用的关系校验，不猜测或修写数据库关联。"""

import hashlib
import json
from collections import defaultdict
from typing import Any

from bisheng.knowledge.domain.contracts.fulltext_reconcile import ReconcileSourceRelationError
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import FileType


def relation_error(row: Any, code: str, *, extra: Any = None) -> ReconcileSourceRelationError:
    file, knowledge, _, document, version, owner, _ = row[:7]
    content_file = row[7] if len(row) > 7 else None
    fields = (
        (
            file,
            (
                "id",
                "tenant_id",
                "knowledge_id",
                "reference_document_id",
                "status",
                "deleted_at",
                "entry_type",
                "entry_status",
            ),
        ),
        (knowledge, ("id", "tenant_id", "type")),
        (document, ("id", "tenant_id", "knowledge_id", "primary_version_id", "lifecycle_status", "content_generation")),
        (version, ("id", "document_id", "knowledge_file_id", "is_primary")),
        (owner, ("id", "tenant_id", "knowledge_id", "primary_version_id", "lifecycle_status", "content_generation")),
        (content_file, ("id", "tenant_id", "knowledge_id", "deleted_at", "file_type")),
    )
    payload = [[getattr(obj, name, None) for name in names] for obj, names in fields]
    fingerprint = hashlib.sha256(json.dumps([code, payload, extra], default=str, sort_keys=True).encode()).hexdigest()
    # 只有业务状态明确处于处理中，才允许把缺少关联当成暂态。
    retryable = (
        str(file.status).upper() in {"1", "5", "WAITING", "PROCESSING", "REBUILDING"}
        or file.entry_status == "preparing"
    )
    return ReconcileSourceRelationError(code, fingerprint, retryable=retryable)


def independently_deleted(file: Any) -> bool:
    return (
        file.deleted_at is not None
        or file.file_type != FileType.FILE.value
        or (file.reference_document_id is not None and file.entry_status in {"deleting", "invalid"})
    )


def group_source_rows(rows: list) -> dict[int, list]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[int(row[0].id)].append(row)
    return dict(grouped)


def unique_source_row(rows: list) -> Any:
    if len(rows) > 1 and not independently_deleted(rows[0][0]):
        errors = [relation_error(row, "ambiguous_relations") for row in rows]
        # 结果顺序变化不能被误判为源关系发生变化，否则跨轮次预算会被重置。
        fingerprint = hashlib.sha256("|".join(sorted(error.fingerprint for error in errors)).encode()).hexdigest()
        raise ReconcileSourceRelationError("ambiguous_relations", fingerprint, retryable=errors[0].retryable)
    return rows[0]


def canonical_identity(row: Any) -> int | None:
    file, knowledge, _, referenced, version, owner, _ = row[:7]
    if independently_deleted(file):
        return None
    if knowledge is None:
        raise relation_error(row, "knowledge_missing")
    if int(knowledge.tenant_id or 1) != int(file.tenant_id or 1):
        raise relation_error(row, "knowledge_tenant_mismatch")
    logical = file.reference_document_id is not None
    document = referenced if logical else owner
    shared = knowledge.type == KnowledgeTypeEnum.SPACE.value
    if logical and referenced is None:
        raise relation_error(row, "document_missing")
    if logical and referenced.primary_version_id is None:
        raise relation_error(row, "primary_version_unset")
    if version is None:
        if logical or shared:
            raise relation_error(row, "primary_version_missing" if logical else "physical_version_missing")
        return None
    if document is None:
        raise relation_error(row, "version_document_missing")
    if int(document.tenant_id or 1) != int(file.tenant_id or 1):
        raise relation_error(row, "document_tenant_mismatch")
    if int(version.document_id) != int(document.id):
        raise relation_error(row, "version_document_mismatch")
    if not logical and int(document.knowledge_id) != int(file.knowledge_id):
        raise relation_error(row, "physical_space_mismatch")
    if document.primary_version_id is None:
        raise relation_error(row, "primary_version_unset")
    if bool(version.is_primary) != (document.primary_version_id == version.id):
        raise relation_error(row, "primary_version_mismatch")
    if logical:
        content_file = row[7]
        if content_file is None or content_file.deleted_at is not None or content_file.file_type != FileType.FILE.value:
            raise relation_error(row, "content_file_missing")
        if (
            int(content_file.tenant_id or 1) != int(document.tenant_id or 1)
            or content_file.knowledge_id != document.knowledge_id
        ):
            raise relation_error(row, "content_file_identity_mismatch")
    return int(document.id)
