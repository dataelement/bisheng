"""按当前主版本上传人的唯一主组织补齐文件所属组织。

在 src/backend 执行, 默认只读预览, 不根据发布路径推导组织:
  .venv/bin/python scripts/backfill_knowledge_file_organization.py --tenant-id 1 --output /tmp/org-plan.jsonl
不使用计划文件也可显式写入, 同时保留回退日志:
  .venv/bin/python scripts/backfill_knowledge_file_organization.py --tenant-id 1 --apply --output /tmp/org-write.jsonl
也可选择执行保存的预览计划:
  .venv/bin/python scripts/backfill_knowledge_file_organization.py --plan /tmp/org-plan.jsonl --apply --output /tmp/org-write.jsonl
回退先预览, 确认后再增加 --apply:
  .venv/bin/python scripts/backfill_knowledge_file_organization.py --rollback /tmp/org-write.jsonl --output /tmp/org-rollback.jsonl

正式执行需维护窗口和已完成字段迁移。报告独占创建且权限0600, 已有组织值不覆盖。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import traceback
from collections import Counter
from contextlib import contextmanager
from itertools import islice
from pathlib import Path
from typing import Any

_BACKEND_ROOT = str(Path(__file__).resolve().parents[1])
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlalchemy import or_, update  # noqa: E402
from sqlmodel import select  # noqa: E402
from sqlmodel.ext.asyncio.session import AsyncSession  # noqa: E402

from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id, strict_tenant_filter  # noqa: E402
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum  # noqa: E402
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument  # noqa: E402
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion  # noqa: E402
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile  # noqa: E402
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_organization_repository_impl import (  # noqa: E402
    KnowledgeFileOrganizationRepositoryImpl,
)


class Refuse(ValueError):
    """数据无法安全处理, 跳过整个文档组。"""


class JsonlJournal:
    """写前持久化日志, 不覆盖已有报告。"""

    def __init__(self, path: str | Path):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        self.file = os.fdopen(fd, "w", encoding="utf-8")
        self.lock = asyncio.Lock()
        self.failed: Exception | None = None

    def write(self, value: dict) -> None:
        self.write_many([value])

    def write_many(self, values: list[dict]) -> None:
        if self.failed is not None:
            raise OSError("审计日志已失败, 禁止继续追加") from self.failed
        self.file.writelines(
            json.dumps(value, ensure_ascii=False, sort_keys=True, default=str) + "\n" for value in values
        )
        self.file.flush()
        os.fsync(self.file.fileno())

    async def awrite(self, *values: dict) -> None:
        async with self.lock:
            if self.failed is not None:
                raise OSError("审计日志已失败, 禁止继续追加") from self.failed
            task = asyncio.create_task(asyncio.to_thread(self.write_many, list(values)))
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise
            except Exception as exc:
                self.failed = exc
                raise

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.file.close()


@contextmanager
def tenant_scope(tenant_id: int):
    if tenant_id <= 0:
        raise ValueError("tenant_id必须为正整数")
    # 显式设置脚本租户上下文, 不依赖请求; 未启用租户过滤时仍逐行复核。
    token = set_current_tenant_id(tenant_id)
    try:
        with strict_tenant_filter():
            yield
    finally:
        current_tenant_id.reset(token)


def database_key(session: AsyncSession) -> str:
    url = session.get_bind().url
    identity = (url.drivername, url.host, url.port, url.database)
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def normalize(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str, sort_keys=True))


_FILE_FIELDS = (
    "id",
    "tenant_id",
    "knowledge_id",
    "user_id",
    "file_name",
    "file_type",
    "file_source",
    "md5",
    "reference_document_id",
    "entry_type",
    "entry_status",
    "belonging_organization_id",
    "update_time",
    "deleted_at",
    "desired_content_generation",
    "desired_entry_generation",
    "file_level_path",
    "level",
    "updater_id",
    "updater_name",
    "status",
)


async def file_snapshots(session: AsyncSession, ids: list[int]) -> list[dict]:
    rows = (
        await session.exec(
            select(KnowledgeFile)
            .where(KnowledgeFile.id.in_(ids))
            .order_by(KnowledgeFile.id)
            .execution_options(populate_existing=True)
        )
    ).all()
    return [normalize({key: getattr(row, key) for key in _FILE_FIELDS}) for row in rows]


async def load_group(session: AsyncSession, seed_id: int, tenant_id: int, *, lock: bool) -> dict:
    seed = (
        await session.exec(
            select(KnowledgeFile).where(KnowledgeFile.id == seed_id).execution_options(populate_existing=True)
        )
    ).first()
    if seed is None or seed.tenant_id != tenant_id:
        raise Refuse("file_missing_or_cross_tenant")
    links = (
        await session.exec(
            select(KnowledgeDocumentVersion.document_id).where(KnowledgeDocumentVersion.knowledge_file_id == seed_id)
        )
    ).all()
    document_ids = set(links)
    if seed.reference_document_id is not None:
        document_ids.add(seed.reference_document_id)
    if len(document_ids) > 1:
        raise Refuse("ambiguous_document_identity")
    document_id = next(iter(document_ids), None)
    document_snapshot, versions_snapshot = None, []
    if document_id is None:
        if seed.entry_type is not None or "shougang_portal_publish" in (seed.user_metadata or {}):
            raise Refuse("missing_document_identity")
        statement = select(KnowledgeFile).where(KnowledgeFile.id == seed_id)
        primary_id = seed_id
    else:
        statement = select(KnowledgeDocument).where(KnowledgeDocument.id == document_id)
        if lock:
            statement = statement.with_for_update()
        document = (await session.exec(statement.execution_options(populate_existing=True))).first()
        if document is None or document.tenant_id != tenant_id or document.lifecycle_status != "active":
            raise Refuse("document_missing_invalid_or_cross_tenant")
        version_query = (
            select(KnowledgeDocumentVersion)
            .where(KnowledgeDocumentVersion.document_id == document_id)
            .order_by(KnowledgeDocumentVersion.id)
        )
        if lock:
            version_query = version_query.with_for_update()
        versions = (await session.exec(version_query.execution_options(populate_existing=True))).all()
        primaries = [row for row in versions if row.is_primary]
        if len(primaries) != 1 or primaries[0].id != document.primary_version_id:
            raise Refuse("primary_version_invalid")
        primary_id = primaries[0].knowledge_file_id
        version_ids = [row.knowledge_file_id for row in versions]
        statement = select(KnowledgeFile).where(
            or_(
                KnowledgeFile.id.in_(version_ids),
                KnowledgeFile.reference_document_id == document_id,
            )
        )
        document_snapshot = normalize(
            {
                key: getattr(document, key)
                for key in (
                    "id",
                    "tenant_id",
                    "knowledge_id",
                    "primary_version_id",
                    "content_generation",
                    "lifecycle_status",
                )
            }
        )
        versions_snapshot = [normalize(row.model_dump()) for row in versions]
    if lock:
        statement = statement.with_for_update()
    rows = (await session.exec(statement.order_by(KnowledgeFile.id).execution_options(populate_existing=True))).all()
    if document_id is not None and not set(version_ids).issubset({row.id for row in rows}):
        raise Refuse("physical_version_missing")
    rows = [row for row in rows if row.entry_type != "projection_tombstone" and row.file_source != "favorite_reference"]
    if not rows or seed_id not in {row.id for row in rows}:
        raise Refuse("non_business_file")
    spaces = (
        await session.exec(
            select(Knowledge.id, Knowledge.tenant_id, Knowledge.type).where(
                Knowledge.id.in_({row.knowledge_id for row in rows})
            )
        )
    ).all()
    valid_spaces = {
        row.id for row in spaces if row.tenant_id == tenant_id and row.type == KnowledgeTypeEnum.SPACE.value
    }
    for row in rows:
        if row.tenant_id != tenant_id or row.file_type != 1 or row.knowledge_id not in valid_spaces:
            raise Refuse("group_scope_invalid")
        if row.entry_type is not None and row.entry_type not in {"manager", "publish", "share"}:
            raise Refuse("unknown_entry_type")
        if row.entry_status not in (None, "active"):
            raise Refuse("distribution_in_flight_or_invalid")
    primary = next((row for row in rows if row.id == primary_id), None)
    if primary is None or primary.user_id is None or primary.user_id <= 0:
        raise Refuse("primary_uploader_missing")
    return {
        "seed_id": seed_id,
        "tenant_id": tenant_id,
        "document_id": document_id,
        "group_key": f"document:{document_id}" if document_id is not None else f"file:{seed_id}",
        "primary_file_id": primary_id,
        "uploader_id": primary.user_id,
        "document": document_snapshot,
        "versions": versions_snapshot,
        "rows": await file_snapshots(session, [row.id for row in rows]),
    }


async def candidate(session: AsyncSession, seed_id: int, tenant_id: int, *, lock: bool = False) -> dict:
    group = await load_group(session, seed_id, tenant_id, lock=lock)
    organization_id = await KnowledgeFileOrganizationRepositoryImpl(session).primary_organization(
        group["uploader_id"],
        tenant_id,
    )
    if organization_id is None:
        raise Refuse("uploader_no_unique_valid_primary_organization")
    if any(row["belonging_organization_id"] not in (None, organization_id) for row in group["rows"]):
        raise Refuse("existing_organization_conflict")
    return {
        "type": "candidate",
        **group,
        "organization_id": organization_id,
        "target_ids": [row["id"] for row in group["rows"] if row["belonging_organization_id"] is None],
    }


def header(session: AsyncSession, tenant_id: int, mode: str) -> dict:
    return {
        "type": "header",
        "version": 1,
        "mode": mode,
        "tenant_id": tenant_id,
        "database_key": database_key(session),
        "rule": "current_primary_version_uploader_main_organization",
    }


def validate_parallel(concurrency: int, session_factory, write_batch_size: int = 200) -> None:
    if not 1 <= concurrency <= 16 or not 1 <= write_batch_size <= 500:
        raise ValueError("concurrency必须为1~16, write_batch_size必须为1~500")
    if concurrency > 1 and session_factory is None:
        raise ValueError("并发必须提供独立会话工厂, 不能共享AsyncSession")


async def bounded_results(items, worker, concurrency: int):
    iterator = iter(items)
    while batch := list(islice(iterator, concurrency)):
        pending = asyncio.gather(*(worker(item) for item in batch), return_exceptions=True)
        try:
            results = await asyncio.shield(pending)
        except BaseException:
            results = await pending
            for result in results:
                if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
                    traceback.print_exception(type(result), result, result.__traceback__)
            raise
        failures = [result for result in results if isinstance(result, BaseException)]
        if failures:
            for failure in failures[1:]:
                traceback.print_exception(type(failure), failure, failure.__traceback__)
            raise failures[0]
        yield results


async def isolated(controller: AsyncSession, session_factory, tenant_id: int, worker, item):
    if session_factory is None:
        return await worker(controller, item)
    async with session_factory() as session:
        with tenant_scope(tenant_id):
            if database_key(session) != database_key(controller):
                raise ValueError("并发会话数据库身份与计划不一致")
            return await worker(session, item)


async def unique_seeds(session: AsyncSession, seeds, tenant_id: int, seen: set) -> list[tuple[int, str]]:
    own_seeds = [seed for seed in seeds if seed.tenant_id == tenant_id]
    links = {}
    for start in range(0, len(own_seeds), 500):
        rows = (
            await session.exec(
                select(KnowledgeDocumentVersion.knowledge_file_id, KnowledgeDocumentVersion.document_id).where(
                    KnowledgeDocumentVersion.knowledge_file_id.in_([seed.id for seed in own_seeds[start : start + 500]])
                )
            )
        ).all()
        for row in rows:
            links.setdefault(row.knowledge_file_id, set()).add(row.document_id)
    result = []
    for seed in own_seeds:
        identities = set(links.get(seed.id, set()))
        if seed.reference_document_id is not None:
            identities.add(seed.reference_document_id)
        key = (
            f"document:{next(iter(identities))}"
            if len(identities) == 1
            else f"invalid:{seed.id}"
            if identities
            else f"file:{seed.id}"
        )
        if key not in seen:
            seen.add(key)
            result.append((seed.id, key))
    return result


async def preview(session: AsyncSession, journal: JsonlJournal, **kwargs) -> dict:
    """保留只读预览入口, 与直接执行共用扫描规则。"""
    return await scan(session, journal, apply=False, **kwargs)


async def scan(
    session: AsyncSession,
    journal: JsonlJournal,
    *,
    tenant_id: int,
    space_id: int | None = None,
    file_id: int | None = None,
    batch_size: int = 200,
    limit: int | None = None,
    start_after_id: int = 0,
    concurrency: int = 1,
    session_factory=None,
    apply: bool = False,
    write_batch_size: int = 200,
) -> dict:
    validate_parallel(concurrency, session_factory, write_batch_size)
    if batch_size <= 0 or start_after_id < 0 or (limit is not None and limit <= 0):
        raise ValueError("batch_size/limit必须为正整数, start_after_id不能为负")
    counts = Counter(scanned=0, groups=0, would_update=0, skipped=0, updated=0)
    seen = set()
    with tenant_scope(tenant_id):
        for model, entity_id in ((Knowledge, space_id), (KnowledgeFile, file_id)):
            if entity_id is not None:
                row = await session.get(model, entity_id)
                if row is None or row.tenant_id != tenant_id:
                    raise ValueError("限定范围不存在或不属于指定租户")
        await journal.awrite(
            {
                **header(session, tenant_id, "apply" if apply else "preview"),
                "concurrency": concurrency,
                "write_batch_size": write_batch_size,
            }
        )

        async def resolve(work_session, item):
            seed_id, expected_key = item
            try:
                record = await candidate(work_session, seed_id, tenant_id)
                if record["group_key"] != expected_key:
                    raise Refuse("document_identity_changed_during_scan")
                if apply:
                    # 结束扫描快照后再锁定复核, 避免复用旧事务中的普通读结果。
                    await work_session.rollback()
                    result = await apply_item(
                        work_session,
                        record,
                        journal,
                        tenant_id=tenant_id,
                        rollback=False,
                        apply=True,
                        write_batch_size=write_batch_size,
                    )
                    return {"type": "applied", **result}
                return record
            except Refuse as exc:
                return {"type": "skipped", "seed_id": seed_id, "reason": str(exc)}
            finally:
                await work_session.rollback()

        async def worker(item):
            return await isolated(session, session_factory, tenant_id, resolve, item)

        cursor = start_after_id
        while limit is None or counts["scanned"] < limit:
            size = min(batch_size, limit - counts["scanned"]) if limit is not None else batch_size
            query = (
                select(KnowledgeFile.id, KnowledgeFile.tenant_id, KnowledgeFile.reference_document_id)
                .where(
                    KnowledgeFile.id > cursor,
                    KnowledgeFile.file_type == 1,
                    KnowledgeFile.belonging_organization_id.is_(None),
                    or_(KnowledgeFile.file_source.is_(None), KnowledgeFile.file_source != "favorite_reference"),
                    or_(KnowledgeFile.entry_type.is_(None), KnowledgeFile.entry_type != "projection_tombstone"),
                )
                .order_by(KnowledgeFile.id)
                .limit(size)
            )
            if space_id is not None:
                query = query.where(KnowledgeFile.knowledge_id == space_id)
            if file_id is not None:
                query = query.where(KnowledgeFile.id == file_id)
            seeds = (await session.exec(query)).all()
            if not seeds:
                break
            cursor = seeds[-1].id
            counts["scanned"] += len(seeds)
            jobs = await unique_seeds(session, seeds, tenant_id, seen)
            await session.rollback()
            async for results in bounded_results(jobs, worker, concurrency):
                for record in results:
                    if record["type"] == "skipped":
                        counts["skipped"] += 1
                        continue
                    counts["groups"] += 1
                    if record["type"] == "applied":
                        counts.update({key: record[key] for key in ("updated", "would_update", "skipped")})
                    else:
                        counts["would_update"] += len(record["target_ids"])
                pending = [record for record in results if record["type"] != "applied"]
                if pending:
                    await journal.awrite(*pending)
        result = {**counts, "next_start_after_id": cursor}
        await journal.awrite({"type": "summary", **result})
        return result


def read_records(path: str | Path):
    with open(path, encoding="utf-8") as stream:
        for line in stream:
            if not line.endswith("\n"):
                yield {"type": "incomplete_tail"}
                return
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError("报告记录必须为JSON对象")
            yield record


async def write_values(
    session: AsyncSession, record: dict, value: int | None, expected: int | None, *, batch_size: int = 200
) -> list[dict]:
    for start in range(0, len(record["target_ids"]), batch_size):
        ids = record["target_ids"][start : start + batch_size]
        predicate = (
            KnowledgeFile.belonging_organization_id.is_(None)
            if expected is None
            else KnowledgeFile.belonging_organization_id == expected
        )
        result = await session.exec(
            update(KnowledgeFile)
            .where(KnowledgeFile.id.in_(ids), predicate)
            .values(
                belonging_organization_id=value,
                update_time=KnowledgeFile.update_time,
            )
        )
        if result.rowcount != len(ids):
            raise Refuse("conditional_update_drift")
    after = await file_snapshots(session, [row["id"] for row in record["rows"]])
    expected_values = {
        row["id"]: value if row["id"] in record["target_ids"] else row["belonging_organization_id"]
        for row in record["rows"]
    }
    if {row["id"]: row["belonging_organization_id"] for row in after} != expected_values:
        raise Refuse("readback_mismatch")
    return after


async def apply_item(
    session: AsyncSession,
    item: dict,
    journal: JsonlJournal,
    *,
    tenant_id: int,
    rollback: bool,
    apply: bool,
    write_batch_size: int,
) -> dict:
    counts = Counter(updated=0, would_update=0, skipped=0)
    record = item["candidate"] if rollback else item
    key = record["group_key"]
    try:
        if record["tenant_id"] != tenant_id or not record["target_ids"]:
            raise Refuse("invalid_candidate_scope")
        if rollback:
            current = await load_group(session, record["seed_id"], tenant_id, lock=True)
            if (
                current["rows"] != item["after"]
                or current["document"] != record["document"]
                or current["versions"] != record["versions"]
            ):
                raise Refuse("rollback_state_changed")
        elif await candidate(session, record["seed_id"], tenant_id, lock=True) != record:
            raise Refuse("plan_state_changed")
        counts["would_update"] += len(record["target_ids"])
        if not apply:
            await journal.awrite({"type": "would_rollback", "group_key": key, "file_ids": record["target_ids"]})
            await session.rollback()
            return dict(counts)
        await journal.awrite({"type": "intent", "candidate": record, "rollback": rollback})
        after = await write_values(
            session,
            record,
            None if rollback else record["organization_id"],
            record["organization_id"] if rollback else None,
            batch_size=write_batch_size,
        )
        await journal.awrite({"type": "prepared", "candidate": record, "after": after})
        await session.commit()
        await journal.awrite({"type": "committed", "candidate": record, "after": after})
        counts["updated"] += len(record["target_ids"])
    except Refuse as exc:
        await session.rollback()
        counts["skipped"] += 1
        await journal.awrite({"type": "skipped", "group_key": key, "reason": str(exc)})
    except BaseException:
        await session.rollback()
        raise
    return dict(counts)


async def apply_plan(
    session: AsyncSession,
    path: str | Path,
    journal: JsonlJournal,
    *,
    rollback: bool = False,
    apply: bool = True,
    concurrency: int = 1,
    session_factory=None,
    write_batch_size: int = 200,
) -> dict:
    validate_parallel(concurrency, session_factory, write_batch_size)
    records = read_records(path)
    source_header = next(records, {})
    tenant_id = source_header.get("tenant_id", 0)
    if (
        source_header.get("type") != "header"
        or source_header.get("version") != 1
        or source_header.get("mode") != ("apply" if rollback else "preview")
        or source_header.get("database_key") != database_key(session)
    ):
        raise ValueError("报告版本、模式或数据库身份不匹配")
    if not rollback:
        last = None
        keys = set()
        for record in read_records(path):
            if record.get("type") == "incomplete_tail":
                raise ValueError("预览计划不完整, 请重新生成")
            if record.get("type") == "candidate":
                key = record["group_key"]
                if key in keys:
                    raise ValueError("计划中存在重复文档, 请重新生成")
                keys.add(key)
            last = record
        if last is None or last.get("type") != "summary":
            raise ValueError("预览计划缺少完整汇总, 请重新生成")
    counts = Counter(updated=0, would_update=0, skipped=0)
    committed_keys, prepared_keys = set(), set()

    def actions():
        for item in records:
            if rollback and item.get("type") == "prepared":
                prepared_keys.add(item["candidate"]["group_key"])
            if item.get("type") != ("committed" if rollback else "candidate"):
                continue
            if rollback:
                key = item["candidate"]["group_key"]
                if key in committed_keys:
                    raise ValueError("写入日志中存在重复文档提交, 请人工核对")
                committed_keys.add(key)
            yield item

    async def execute(work_session, item):
        return await apply_item(
            work_session,
            item,
            journal,
            tenant_id=tenant_id,
            rollback=rollback,
            apply=apply,
            write_batch_size=write_batch_size,
        )

    async def worker(item):
        return await isolated(session, session_factory, tenant_id, execute, item)

    with tenant_scope(tenant_id):
        await session.rollback()
        await journal.awrite(
            {
                **header(
                    session,
                    tenant_id,
                    "rollback" if rollback and apply else "rollback-preview" if rollback else "apply",
                ),
                "concurrency": concurrency,
                "write_batch_size": write_batch_size,
            }
        )
        async for results in bounded_results(actions(), worker, concurrency):
            for result in results:
                counts.update(result)
        if rollback:
            for key in sorted(prepared_keys - committed_keys):
                counts["skipped"] += 1
                await journal.awrite({"type": "skipped", "group_key": key, "reason": "commit_outcome_unknown"})
        await journal.awrite({"type": "summary", **counts})
        return dict(counts)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    result.add_argument("--tenant-id", type=int, help="扫描预览或直接写入时必须指定租户")
    result.add_argument("--space-id", type=int, help="仅选择指定知识库的种子, 扩展到整文档")
    result.add_argument("--file-id", type=int, help="仅选择指定文件种子, 扩展到整文档")
    result.add_argument("--batch-size", type=int, default=200)
    result.add_argument("--concurrency", type=int, default=4, help="文档并发数1~16, 默认4; 1为串行")
    result.add_argument("--write-batch-size", type=int, default=200, help="每条UPDATE的目标文件数1~500, 默认200")
    result.add_argument("--limit", type=int)
    result.add_argument("--start-after-id", type=int, default=0)
    mode = result.add_mutually_exclusive_group()
    mode.add_argument("--plan", type=Path, help="执行已审核的预览计划, 需要--apply")
    mode.add_argument("--rollback", type=Path, help="回退写入日志, 默认只预览")
    result.add_argument("--apply", action="store_true", help="实际写入; 无--plan时按指定租户直接扫描补齐")
    result.add_argument("--output", type=Path, required=True, help="新报告路径, 不允许覆盖")
    return result


async def run(args: argparse.Namespace) -> int:
    from bisheng.core.context.manager import close_app_context
    from bisheng.core.database import get_async_db_session

    try:
        with JsonlJournal(args.output) as journal:
            async with get_async_db_session() as session:
                if args.plan or args.rollback:
                    counts = await apply_plan(
                        session,
                        args.plan or args.rollback,
                        journal,
                        rollback=bool(args.rollback),
                        apply=args.apply,
                        concurrency=args.concurrency,
                        session_factory=get_async_db_session,
                        write_batch_size=args.write_batch_size,
                    )
                else:
                    counts = await scan(
                        session,
                        journal,
                        tenant_id=args.tenant_id,
                        space_id=args.space_id,
                        file_id=args.file_id,
                        batch_size=args.batch_size,
                        limit=args.limit,
                        start_after_id=args.start_after_id,
                        concurrency=args.concurrency,
                        session_factory=get_async_db_session,
                        apply=args.apply,
                        write_batch_size=args.write_batch_size,
                    )
        print(json.dumps(counts, ensure_ascii=False, sort_keys=True))
        return 3 if args.apply and counts["skipped"] else 0
    finally:
        await close_app_context()


def main() -> int:
    cli = parser()
    args = cli.parse_args()
    if not 1 <= args.concurrency <= 16 or not 1 <= args.write_batch_size <= 500:
        cli.error("--concurrency必须为1~16, --write-batch-size必须为1~500")
    if args.plan or args.rollback:
        if (
            args.tenant_id is not None
            or args.space_id is not None
            or args.file_id is not None
            or args.limit is not None
        ):
            cli.error("计划或回退模式不能另改租户、知识库、文件或数量范围")
        if args.start_after_id != 0 or args.batch_size != 200:
            cli.error("计划或回退模式不能另改游标或批大小")
        if args.plan and not args.apply:
            cli.error("执行计划必须显式传入--apply")
    elif args.tenant_id is None or args.tenant_id <= 0:
        cli.error("扫描预览或直接写入必须指定正整数--tenant-id")
    try:
        return asyncio.run(run(args))
    except (ValueError, FileExistsError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"执行失败({type(exc).__name__}), 请保留报告并核对提交结果", file=sys.stderr)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
