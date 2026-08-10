"""回填历史知识文件的原始上传人与原始上传知识库。

脚本默认仅扫描并输出报告; 只有显式传入 ``--apply`` 才写数据库。它覆盖所有租户的
SPACE 非目录业务文件(含软删除和 F059 分发入口), 并排除收藏快捷引用。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlalchemy import and_, or_  # noqa: E402
from sqlmodel import col, select, update  # noqa: E402
from sqlmodel.ext.asyncio.session import AsyncSession  # noqa: E402

from bisheng.core.context.manager import close_app_context  # noqa: E402
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.knowledge.domain.models.knowledge import (  # noqa: E402
    Knowledge,
    KnowledgeTypeEnum,
)
from bisheng.knowledge.domain.models.knowledge_document import (  # noqa: E402
    KnowledgeDocument,
)
from bisheng.knowledge.domain.models.knowledge_document_version import (  # noqa: E402
    KnowledgeDocumentVersion,
)
from bisheng.knowledge.domain.models.knowledge_file import (  # noqa: E402
    FileType,
    KnowledgeFile,
    KnowledgeFileEntryType,
)

LEGACY_PUBLISH_METADATA_KEY = "shougang_portal_publish"
FAVORITE_REFERENCE_SOURCE = "favorite_reference"


@dataclass(frozen=True)
class Origin:
    """可确定的原始上传事实。"""

    uploader_id: int
    knowledge_id: int


@dataclass(frozen=True)
class BackfillSample:
    """有限审计样例, 避免报告无限增长。"""

    group_key: str
    file_ids: list[int]
    outcome: str
    reason: str | None = None
    origin: Origin | None = None


@dataclass
class BackfillReport:
    """一次回填扫描的审计统计。"""

    scanned: int = 0
    eligible: int = 0
    processed_groups: int = 0
    would_update: int = 0
    updated: int = 0
    skipped: int = 0
    conflict: int = 0
    broken_chain: int = 0
    unchanged: int = 0
    duplicate_candidates: int = 0
    next_start_after_id: int = 0
    reason_counts: Counter[str] = field(default_factory=Counter)
    samples: list[BackfillSample] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reason_counts"] = dict(sorted(self.reason_counts.items()))
        return payload

    def __str__(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True)


class ResolutionError(Exception):
    """来源不能安全确定时使用的失败关闭异常。"""

    def __init__(self, reason: str, *, conflict: bool = False):
        super().__init__(reason)
        self.reason = reason
        self.conflict = conflict


@dataclass
class ResolvedGroup:
    """一次必须原子复核和写入的文件组。"""

    key: str
    origin: Origin
    rows: list[KnowledgeFile]

    @property
    def target_rows(self) -> list[KnowledgeFile]:
        return [row for row in self.rows if row.original_uploader_id is None or row.original_knowledge_id is None]


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _legacy_publish_metadata(row: KnowledgeFile) -> dict[str, Any] | None:
    metadata = row.user_metadata
    if not isinstance(metadata, dict) or LEGACY_PUBLISH_METADATA_KEY not in metadata:
        return None
    publish = metadata.get(LEGACY_PUBLISH_METADATA_KEY)
    if not isinstance(publish, dict):
        raise ResolutionError("legacy_metadata_invalid")
    return publish


async def _load_space(
    session: AsyncSession,
    knowledge_id: int,
    *,
    tenant_id: int,
) -> Knowledge:
    space = await session.get(Knowledge, knowledge_id)
    if space is None:
        raise ResolutionError("knowledge_missing")
    if int(space.type) != KnowledgeTypeEnum.SPACE.value:
        raise ResolutionError("knowledge_not_space")
    if int(space.tenant_id or 0) != tenant_id:
        raise ResolutionError("cross_tenant_knowledge")
    return space


async def _validate_business_row(
    session: AsyncSession,
    row: KnowledgeFile,
    *,
    tenant_id: int,
) -> None:
    if int(row.tenant_id or 0) != tenant_id:
        raise ResolutionError("cross_tenant_file")
    if int(row.file_type) != FileType.FILE.value:
        raise ResolutionError("directory_not_supported")
    if row.file_source == FAVORITE_REFERENCE_SOURCE:
        raise ResolutionError("favorite_reference_excluded")
    await _load_space(session, int(row.knowledge_id), tenant_id=tenant_id)


async def _canonical_id_for_file(session: AsyncSession, row: KnowledgeFile) -> int | None:
    document_ids: set[int] = set()
    if row.reference_document_id is not None:
        document_ids.add(int(row.reference_document_id))
    result = await session.exec(
        select(KnowledgeDocumentVersion.document_id).where(KnowledgeDocumentVersion.knowledge_file_id == row.id)
    )
    document_ids.update(int(value) for value in result.all())
    if len(document_ids) > 1:
        raise ResolutionError("canonical_relation_ambiguous")
    return next(iter(document_ids), None)


async def _canonical_rows(
    session: AsyncSession,
    document_id: int,
    *,
    lock: bool,
) -> tuple[KnowledgeDocument, list[KnowledgeDocumentVersion], list[KnowledgeFile]]:
    document_stmt = select(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
    if lock:
        document_stmt = document_stmt.with_for_update()
    document = (await session.exec(document_stmt)).first()
    if document is None:
        raise ResolutionError("canonical_document_missing")

    versions_stmt = (
        select(KnowledgeDocumentVersion)
        .where(KnowledgeDocumentVersion.document_id == document_id)
        .order_by(KnowledgeDocumentVersion.version_no, KnowledgeDocumentVersion.id)
    )
    if lock:
        versions_stmt = versions_stmt.with_for_update()
    versions = list((await session.exec(versions_stmt)).all())
    version_file_ids = {int(version.knowledge_file_id) for version in versions}
    entry_ids = {
        int(value)
        for value in (
            await session.exec(select(KnowledgeFile.id).where(KnowledgeFile.reference_document_id == document_id))
        ).all()
    }
    file_ids = sorted(version_file_ids | entry_ids)
    if not file_ids:
        raise ResolutionError("canonical_group_empty")
    files_stmt = select(KnowledgeFile).where(col(KnowledgeFile.id).in_(file_ids)).order_by(KnowledgeFile.id)
    if lock:
        files_stmt = files_stmt.with_for_update()
    rows = list((await session.exec(files_stmt)).all())
    if {int(row.id) for row in rows} != set(file_ids):
        raise ResolutionError("canonical_file_missing")
    return document, versions, rows


async def _infer_canonical_origin(
    session: AsyncSession,
    document: KnowledgeDocument,
    versions: list[KnowledgeDocumentVersion],
    rows_by_id: dict[int, KnowledgeFile],
) -> Origin:
    tenant_id = int(document.tenant_id or 0)
    predecessor_id = document.predecessor_logic_file_id
    if predecessor_id is not None:
        # 历史目标版本合并与“多版本文档再发布”在旧字段上无法区分; 前者应保留
        # 目标文档来源, 后者应取 publish 根链, 因此没有既有原始事实时必须跳过。
        if len(versions) > 1:
            raise ResolutionError("canonical_merged_origin_ambiguous")
        visited: set[int] = set()
        root: KnowledgeFile | None = None
        while predecessor_id is not None:
            current_id = int(predecessor_id)
            if current_id in visited:
                raise ResolutionError("canonical_predecessor_cycle")
            visited.add(current_id)
            root = rows_by_id.get(current_id)
            if root is None:
                root = await session.get(KnowledgeFile, current_id)
            if root is None:
                raise ResolutionError("canonical_predecessor_missing")
            if int(root.tenant_id or 0) != tenant_id:
                raise ResolutionError("canonical_predecessor_cross_tenant")
            if root.reference_document_id != document.id:
                raise ResolutionError("canonical_predecessor_document_mismatch")
            if root.entry_type != KnowledgeFileEntryType.PUBLISH.value:
                raise ResolutionError("canonical_predecessor_not_publish")
            predecessor_id = root.predecessor_logic_file_id
        if root is None or root.user_id is None:
            raise ResolutionError("original_uploader_missing")
        await _load_space(session, int(root.knowledge_id), tenant_id=tenant_id)
        return Origin(int(root.user_id), int(root.knowledge_id))

    if not versions:
        raise ResolutionError("canonical_version_missing")
    first_version = versions[0]
    first_file = rows_by_id.get(int(first_version.knowledge_file_id))
    if first_file is None:
        raise ResolutionError("canonical_first_version_missing")
    if first_file.user_id is None:
        raise ResolutionError("original_uploader_missing")
    await _load_space(session, int(first_file.knowledge_id), tenant_id=tenant_id)
    return Origin(int(first_file.user_id), int(first_file.knowledge_id))


def _merge_existing_origin(rows: list[KnowledgeFile], inferred: Origin | None) -> Origin:
    uploader_ids = {int(row.original_uploader_id) for row in rows if row.original_uploader_id is not None}
    knowledge_ids = {int(row.original_knowledge_id) for row in rows if row.original_knowledge_id is not None}
    if len(uploader_ids) > 1 or len(knowledge_ids) > 1:
        raise ResolutionError("existing_origin_conflict", conflict=True)

    uploader_id = next(iter(uploader_ids), inferred.uploader_id if inferred else None)
    knowledge_id = next(iter(knowledge_ids), inferred.knowledge_id if inferred else None)
    if uploader_id is None or knowledge_id is None:
        raise ResolutionError("origin_incomplete")
    if inferred is not None and (uploader_id, knowledge_id) != (
        inferred.uploader_id,
        inferred.knowledge_id,
    ):
        raise ResolutionError("existing_origin_mismatches_chain", conflict=True)
    return Origin(uploader_id, knowledge_id)


async def _resolve_canonical_group(
    session: AsyncSession,
    document_id: int,
    *,
    lock: bool,
) -> ResolvedGroup:
    document, versions, all_rows = await _canonical_rows(session, document_id, lock=lock)
    tenant_id = int(document.tenant_id or 0)
    if tenant_id <= 0:
        raise ResolutionError("canonical_tenant_missing")

    eligible_rows: list[KnowledgeFile] = []
    for row in all_rows:
        if (
            row.file_source == FAVORITE_REFERENCE_SOURCE
            or row.entry_type == KnowledgeFileEntryType.PROJECTION_TOMBSTONE.value
        ):
            continue
        await _validate_business_row(session, row, tenant_id=tenant_id)
        eligible_rows.append(row)
    if not eligible_rows:
        raise ResolutionError("canonical_business_group_empty")
    existing_uploader_ids = {
        int(row.original_uploader_id) for row in eligible_rows if row.original_uploader_id is not None
    }
    existing_knowledge_ids = {
        int(row.original_knowledge_id) for row in eligible_rows if row.original_knowledge_id is not None
    }
    if len(existing_uploader_ids) > 1 or len(existing_knowledge_ids) > 1:
        raise ResolutionError("existing_origin_conflict", conflict=True)
    existing_complete = len(existing_uploader_ids) == 1 and len(existing_knowledge_ids) == 1
    inferred = None
    if not existing_complete:
        inferred = await _infer_canonical_origin(
            session,
            document,
            versions,
            {int(row.id): row for row in all_rows},
        )
    origin = _merge_existing_origin(eligible_rows, inferred)
    await _load_space(session, origin.knowledge_id, tenant_id=tenant_id)
    return ResolvedGroup(f"document:{document_id}", origin, eligible_rows)


async def _resolve_legacy_or_ordinary_origin(
    session: AsyncSession,
    row: KnowledgeFile,
    *,
    lock: bool,
) -> Origin:
    tenant_id = int(row.tenant_id or 0)
    if tenant_id <= 0:
        raise ResolutionError("tenant_missing")
    current = row
    visited: set[int] = set()
    while True:
        current_id = int(current.id)
        if current_id in visited:
            raise ResolutionError("legacy_source_cycle")
        visited.add(current_id)
        await _validate_business_row(session, current, tenant_id=tenant_id)

        metadata = _legacy_publish_metadata(current)
        if metadata is None:
            document_id = await _canonical_id_for_file(session, current)
            if document_id is not None:
                return (await _resolve_canonical_group(session, document_id, lock=lock)).origin
            if current.user_id is None:
                raise ResolutionError("original_uploader_missing")
            inferred = Origin(int(current.user_id), int(current.knowledge_id))
            return _merge_existing_origin([current], inferred)

        source_file_id = _positive_int(metadata.get("source_file_id"))
        if source_file_id is None:
            raise ResolutionError("legacy_source_id_invalid")
        source_stmt = select(KnowledgeFile).where(KnowledgeFile.id == source_file_id)
        if lock:
            source_stmt = source_stmt.with_for_update()
        source = (await session.exec(source_stmt)).first()
        if source is None:
            raise ResolutionError("legacy_source_missing")
        if int(source.tenant_id or 0) != tenant_id:
            raise ResolutionError("legacy_source_cross_tenant")
        expected_space_id = _positive_int(metadata.get("source_space_id"))
        if expected_space_id is not None and expected_space_id != int(source.knowledge_id):
            raise ResolutionError("legacy_source_space_mismatch")
        current = source


async def _resolve_group(
    session: AsyncSession,
    seed: KnowledgeFile,
    *,
    lock: bool,
) -> ResolvedGroup:
    if lock:
        locked_seed = (
            await session.exec(select(KnowledgeFile).where(KnowledgeFile.id == seed.id).with_for_update())
        ).first()
        if locked_seed is None:
            raise ResolutionError("seed_file_missing")
        seed = locked_seed
    document_id = await _canonical_id_for_file(session, seed)
    if document_id is not None:
        return await _resolve_canonical_group(session, document_id, lock=lock)

    await _validate_business_row(session, seed, tenant_id=int(seed.tenant_id or 0))
    inferred = await _resolve_legacy_or_ordinary_origin(session, seed, lock=lock)
    origin = _merge_existing_origin([seed], inferred)
    return ResolvedGroup(f"file:{int(seed.id)}", origin, [seed])


def _candidate_stmt(
    *,
    last_id: int,
    batch_size: int,
    tenant_id: int | None,
    knowledge_id: int | None,
    file_id: int | None,
):
    stmt = (
        select(KnowledgeFile)
        .join(Knowledge, Knowledge.id == KnowledgeFile.knowledge_id)
        .where(
            Knowledge.type == KnowledgeTypeEnum.SPACE.value,
            Knowledge.tenant_id == KnowledgeFile.tenant_id,
            KnowledgeFile.file_type == FileType.FILE.value,
            or_(KnowledgeFile.file_source.is_(None), KnowledgeFile.file_source != FAVORITE_REFERENCE_SOURCE),
            or_(
                KnowledgeFile.entry_type.is_(None),
                KnowledgeFile.entry_type != KnowledgeFileEntryType.PROJECTION_TOMBSTONE.value,
            ),
            or_(
                KnowledgeFile.original_uploader_id.is_(None),
                KnowledgeFile.original_knowledge_id.is_(None),
            ),
            KnowledgeFile.id > last_id,
        )
        .order_by(KnowledgeFile.id)
        .limit(batch_size)
    )
    if tenant_id is not None:
        stmt = stmt.where(KnowledgeFile.tenant_id == tenant_id)
    if knowledge_id is not None:
        stmt = stmt.where(KnowledgeFile.knowledge_id == knowledge_id)
    if file_id is not None:
        stmt = stmt.where(KnowledgeFile.id == file_id)
    return stmt


async def _conditionally_update_group(
    session: AsyncSession,
    group: ResolvedGroup,
) -> int:
    updated = 0
    for row in group.target_rows:
        values: dict[str, int] = {}
        predicates = [KnowledgeFile.id == row.id]
        if row.original_uploader_id is None:
            values["original_uploader_id"] = group.origin.uploader_id
            predicates.append(KnowledgeFile.original_uploader_id.is_(None))
        else:
            predicates.append(KnowledgeFile.original_uploader_id == row.original_uploader_id)
        if row.original_knowledge_id is None:
            values["original_knowledge_id"] = group.origin.knowledge_id
            predicates.append(KnowledgeFile.original_knowledge_id.is_(None))
        else:
            predicates.append(KnowledgeFile.original_knowledge_id == row.original_knowledge_id)
        result = await session.exec(update(KnowledgeFile).where(and_(*predicates)).values(**values))
        if result.rowcount != 1:
            raise ResolutionError("conditional_update_drift", conflict=True)
        updated += 1
    return updated


def _record_failure(
    report: BackfillReport,
    *,
    key: str,
    file_ids: list[int],
    error: ResolutionError,
    sample_limit: int,
) -> None:
    report.skipped += 1
    report.reason_counts[error.reason] += 1
    if error.conflict:
        report.conflict += 1
    else:
        report.broken_chain += 1
    if len(report.samples) < sample_limit:
        report.samples.append(
            BackfillSample(
                group_key=key,
                file_ids=file_ids,
                outcome="skipped",
                reason=error.reason,
            )
        )


async def _backfill_original_origins(
    session: AsyncSession,
    *,
    apply: bool,
    tenant_id: int | None,
    knowledge_id: int | None,
    file_id: int | None,
    limit: int | None,
    start_after_id: int,
    batch_size: int,
    sample_limit: int,
) -> BackfillReport:
    report = BackfillReport(next_start_after_id=start_after_id)
    processed_keys: set[str] = set()
    remaining = limit
    last_id = start_after_id

    while remaining is None or remaining > 0:
        current_batch_size = batch_size if remaining is None else min(batch_size, remaining)
        seeds = list(
            (
                await session.exec(
                    _candidate_stmt(
                        last_id=last_id,
                        batch_size=current_batch_size,
                        tenant_id=tenant_id,
                        knowledge_id=knowledge_id,
                        file_id=file_id,
                    )
                )
            ).all()
        )
        if not seeds:
            break
        report.scanned += len(seeds)
        if remaining is not None:
            remaining -= len(seeds)

        for seed in seeds:
            last_id = max(last_id, int(seed.id))
            report.next_start_after_id = last_id
            provisional_key = f"file:{int(seed.id)}"
            try:
                document_id = await _canonical_id_for_file(session, seed)
                provisional_key = f"document:{document_id}" if document_id is not None else f"file:{int(seed.id)}"
                if provisional_key in processed_keys:
                    report.duplicate_candidates += 1
                    continue
                processed_keys.add(provisional_key)
                report.processed_groups += 1
                preview = await _resolve_group(session, seed, lock=False)
            except ResolutionError as exc:
                _record_failure(
                    report,
                    key=provisional_key,
                    file_ids=[int(seed.id)],
                    error=exc,
                    sample_limit=sample_limit,
                )
                continue

            if not apply:
                targets = preview.target_rows
                report.eligible += len(targets)
                report.would_update += len(targets)
                if not targets:
                    report.unchanged += 1
                if len(report.samples) < sample_limit and targets:
                    report.samples.append(
                        BackfillSample(
                            group_key=preview.key,
                            file_ids=[int(row.id) for row in targets],
                            outcome="would_update",
                            origin=preview.origin,
                        )
                    )
                continue

            try:
                async with session.begin_nested():
                    locked = await _resolve_group(session, seed, lock=True)
                    if locked.key != preview.key or locked.origin != preview.origin:
                        raise ResolutionError("origin_changed_before_write", conflict=True)
                    targets = locked.target_rows
                    report.eligible += len(targets)
                    changed = await _conditionally_update_group(session, locked)
                    report.updated += changed
                    if not changed:
                        report.unchanged += 1
                    if len(report.samples) < sample_limit and changed:
                        report.samples.append(
                            BackfillSample(
                                group_key=locked.key,
                                file_ids=[int(row.id) for row in targets],
                                outcome="updated",
                                origin=locked.origin,
                            )
                        )
            except ResolutionError as exc:
                _record_failure(
                    report,
                    key=preview.key,
                    file_ids=[int(row.id) for row in preview.rows],
                    error=exc,
                    sample_limit=sample_limit,
                )

        if apply:
            await session.commit()
        if file_id is not None:
            break

    return report


async def backfill_original_origins(
    session: AsyncSession,
    *,
    apply: bool = False,
    tenant_id: int | None = None,
    knowledge_id: int | None = None,
    file_id: int | None = None,
    limit: int | None = None,
    start_after_id: int = 0,
    batch_size: int = 200,
    sample_limit: int = 10,
) -> BackfillReport:
    """扫描并可选回填原始来源; 跨租户读取始终显式绕过请求租户过滤。"""
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than 0")
    if limit is not None and limit <= 0:
        raise ValueError("limit must be greater than 0")
    if start_after_id < 0:
        raise ValueError("start_after_id must not be negative")
    for name, value in (("tenant_id", tenant_id), ("knowledge_id", knowledge_id), ("file_id", file_id)):
        if value is not None and value <= 0:
            raise ValueError(f"{name} must be greater than 0")
    if sample_limit < 0:
        raise ValueError("sample_limit must not be negative")

    with bypass_tenant_filter():
        return await _backfill_original_origins(
            session,
            apply=apply,
            tenant_id=tenant_id,
            knowledge_id=knowledge_id,
            file_id=file_id,
            limit=limit,
            start_after_id=start_after_id,
            batch_size=batch_size,
            sample_limit=sample_limit,
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="写入数据库; 默认仅 dry-run")
    parser.add_argument("--tenant-id", type=int, default=None, help="仅选择一个租户")
    parser.add_argument("--knowledge-id", type=int, default=None, help="仅选择一个知识空间")
    parser.add_argument("--file-id", type=int, default=None, help="选择一个文件; canonical 会扩展为整组")
    parser.add_argument("--limit", type=int, default=None, help="最多扫描的候选种子行数")
    parser.add_argument("--start-after-id", type=int, default=0, help="从该 KnowledgeFile ID 之后续跑")
    parser.add_argument("--batch-size", type=int, default=200, help="每批候选种子行数, 默认 200")
    parser.add_argument("--sample-limit", type=int, default=10, help="报告最多保留的样例数, 默认 10")
    return parser


async def _run(args: argparse.Namespace) -> int:
    try:
        async with get_async_db_session() as session:
            report = await backfill_original_origins(
                session,
                apply=args.apply,
                tenant_id=args.tenant_id,
                knowledge_id=args.knowledge_id,
                file_id=args.file_id,
                limit=args.limit,
                start_after_id=args.start_after_id,
                batch_size=args.batch_size,
                sample_limit=args.sample_limit,
            )
        payload = {"mode": "apply" if args.apply else "dry-run", **report.as_dict()}
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        await close_app_context()


def main() -> int:
    """解析 CLI 参数并执行回填。"""
    return asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    sys.exit(main())
