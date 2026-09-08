#!/usr/bin/env python3
# ruff: noqa: RUF001, RUF002, RUF003
r"""按知识库内当前主版本 MD5 去重，保留上传时间最新的文档。

用于门户知识库历史重复数据清理。默认仅扫描并生成 JSONL 报告；显式
--apply 才自动使用系统中有效的超级管理员调用现有知识空间删除业务。普通文档
进入回收站，发布/分享入口遵循分发生命周期，不额外强制清理物理存储。

从 src/backend 执行：
    .venv/bin/python scripts/dedupe_knowledge_space_documents.py
    .venv/bin/python scripts/dedupe_knowledge_space_documents.py --space-id 10
    .venv/bin/python scripts/dedupe_knowledge_space_documents.py \
        --space-id 10 --apply

正式 apply 应在停止上传、版本变更、审批和分发操作的维护窗口运行。
脚本逐项复核，但不提供跨业务会话/外部存储的原子事务或全局写锁。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
import uuid
from collections import defaultdict
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_BACKEND_ROOT = str(Path(__file__).resolve().parent.parent)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

ACTIVE_APPROVALS = frozenset({"pending", "approved", "executing", "exception", "execute_failed"})
LEVELS = ("public", "department", "team", "team_ks", "personal")
FILE_FIELDS = {
    "id",
    "tenant_id",
    "knowledge_id",
    "file_type",
    "file_name",
    "file_level_path",
    "md5",
    "status",
    "create_time",
    "deleted_at",
    "reference_document_id",
    "entry_type",
    "entry_status",
    "approval_instance_id",
    "projection_status",
    "desired_content_generation",
    "applied_content_generation",
    "desired_entry_generation",
    "applied_entry_generation",
}


@dataclass(frozen=True)
class Inventory:
    spaces: tuple[dict, ...]
    scopes: tuple[dict, ...]
    files: tuple[dict, ...]
    documents: tuple[dict, ...]
    versions: tuple[dict, ...]
    approvals: tuple[dict, ...]
    tenant_id: int


@dataclass(frozen=True)
class Candidate:
    entry_id: int
    space_id: int
    space_name: str
    file_name: str
    folder: str | None
    content_id: int
    document_id: int | None
    md5: str
    uploaded_at: str
    entry_type: str
    history_file_ids: tuple[int, ...]
    dependent_entry_ids: tuple[int, ...]
    fingerprint: str

    @property
    def rank(self) -> tuple[str, int, int]:
        return self.uploaded_at, self.content_id, self.entry_id

    @property
    def impact_ids(self) -> set[int]:
        if self.entry_type in {"publish", "share"}:
            return {self.entry_id}
        return {self.entry_id, *self.history_file_ids, *self.dependent_entry_ids}


@dataclass(frozen=True)
class Group:
    keep: Candidate
    remove: tuple[Candidate, ...]


@dataclass(frozen=True)
class Plan:
    candidates: dict[int, Candidate]
    groups: tuple[Group, ...]
    skipped: tuple[dict, ...]


def _stamp(value: datetime | str) -> str:
    date = datetime.fromisoformat(value) if isinstance(value, str) else value
    if date.tzinfo is not None:
        date = date.astimezone(timezone.utc).replace(tzinfo=None)
    return date.isoformat(timespec="microseconds")


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def build_plan(inventory: Inventory, space_ids: set[int] | None = None) -> Plan:
    """只读计算候选；物理历史版本不作为独立文档参与比较。"""
    tenant_id = inventory.tenant_id
    scopes = {s["space_id"]: s for s in inventory.scopes}
    spaces = {
        s["id"]: s
        for s in inventory.spaces
        if s.get("tenant_id") == tenant_id
        and s.get("type") == 3
        and s.get("state") == 1
        and scopes.get(s["id"], {}).get("level") in LEVELS
    }
    if space_ids and not space_ids.issubset(spaces):
        raise ValueError("指定知识库不存在、不属于当前租户、缺少门户层级或不是正常状态")
    files = {f["id"]: f for f in inventory.files}
    documents = {d["id"]: d for d in inventory.documents}
    by_file: dict[int, list[dict]] = defaultdict(list)
    by_document: dict[int, list[dict]] = defaultdict(list)
    entries: dict[int, list[dict]] = defaultdict(list)
    for v in inventory.versions:
        by_file[v["knowledge_file_id"]].append(v)
        by_document[v["document_id"]].append(v)
    for f in inventory.files:
        if f.get("reference_document_id"):
            entries[f["reference_document_id"]].append(f)
    active = [a for a in inventory.approvals if a.get("tenant_id") == tenant_id and a.get("status") in ACTIVE_APPROVALS]
    approval_ids = {a["id"] for a in active}
    locked_documents: set[int] = set()
    locked_files: set[int] = set()
    for a in active:
        resource = str(a.get("business_resource_id", ""))
        if a.get("scenario_code") in {
            "knowledge_space_file_publish_request",
            "knowledge_space_file_share_request",
        }:
            prefix = resource.split(":", 1)[0]
            if prefix.isdigit():
                locked_documents.add(int(prefix))
        elif "file" in str(a.get("business_resource_type", "")) and resource.isdigit():
            locked_files.add(int(resource))

    candidates: dict[int, Candidate] = {}
    skipped: list[dict] = []
    for entry in inventory.files:
        eid, sid = entry["id"], entry["knowledge_id"]
        if space_ids and sid not in space_ids:
            continue
        if entry.get("file_type") != 1:
            continue

        def skip(reason: str, row: dict = entry) -> None:
            skipped.append(
                {
                    "entry_id": row["id"],
                    "space_id": row["knowledge_id"],
                    "file_name": row.get("file_name"),
                    "reason": reason,
                }
            )

        if sid not in spaces or entry.get("tenant_id") != tenant_id:
            skip("space_or_tenant_ineligible")
            continue
        if entry.get("deleted_at") is not None:
            skip("in_recycle_bin")
            continue
        kind = entry.get("entry_type") or "legacy"
        if kind not in {"legacy", "manager", "publish", "share"}:
            skip("unsupported_entry_type")
            continue
        if entry.get("entry_status") not in (None, "active"):
            skip("entry_not_active")
            continue
        if kind in {"publish", "share"} and (
            entry.get("projection_status") != "ready"
            or int(entry.get("applied_content_generation") or 0) < int(entry.get("desired_content_generation") or 0)
            or int(entry.get("applied_entry_generation") or 0) < int(entry.get("desired_entry_generation") or 0)
        ):
            skip("projection_not_ready")
            continue
        file_versions = by_file[eid]
        if len(file_versions) > 1:
            skip("ambiguous_version_link")
            continue
        doc_id = entry.get("reference_document_id")
        if file_versions and not file_versions[0].get("is_primary"):
            skip("historical_version")
            continue
        if doc_id and file_versions and file_versions[0]["document_id"] != doc_id:
            skip("conflicting_document_link")
            continue
        if not doc_id and file_versions:
            v = file_versions[0]
            doc_id = v["document_id"]
            if any(e.get("entry_type") == "manager" and e["id"] != eid for e in entries[doc_id]):
                skip("canonical_content_not_list_entry")
                continue
        document = documents.get(doc_id) if doc_id else None
        chain = sorted(by_document.get(doc_id, []), key=lambda v: v["id"])
        content = entry
        if doc_id:
            primary = [v for v in chain if v.get("is_primary")]
            if (
                not document
                or document.get("tenant_id") != tenant_id
                or document.get("lifecycle_status", "active") != "active"
                or len(primary) != 1
                or primary[0]["id"] != document.get("primary_version_id")
            ):
                skip("invalid_document_or_primary_version")
                continue
            content = files.get(primary[0]["knowledge_file_id"])
            if not content:
                skip("primary_file_missing")
                continue
            if kind in {"legacy", "manager"} and document["knowledge_id"] != sid:
                skip("document_space_mismatch")
                continue
        elif kind in {"publish", "share"}:
            skip("reference_missing")
            continue
        history = [files.get(v["knowledge_file_id"]) for v in chain] or [content]
        related = [entry, *history, *entries.get(doc_id, [])]
        if any(f is None or f.get("tenant_id") != tenant_id for f in related):
            skip("version_or_reference_missing_or_cross_tenant")
            continue
        if doc_id in locked_documents or any(
            f["id"] in locked_files or f.get("approval_instance_id") in approval_ids for f in related
        ):
            skip("approval_in_progress")
            continue
        if (
            entry.get("status") != 2
            or content.get("status") != 2
            or content.get("deleted_at") is not None
            or any(f.get("status") in {1, 4, 5} for f in history)
        ):
            skip("parse_not_success_or_history_inflight")
            continue
        if any(
            f.get("tenant_id") != tenant_id
            or f.get("file_type") != 1
            or (document and f["knowledge_id"] != document["knowledge_id"])
            or f.get("deleted_at") is not None
            for f in history
        ):
            skip("invalid_version_chain")
            continue
        md5 = str(content.get("md5") or "").strip().lower()
        if not md5:
            skip("empty_md5")
            continue
        if content.get("create_time") is None:
            skip("upload_time_missing")
            continue
        dependencies = tuple(
            sorted(
                e["id"]
                for e in entries.get(doc_id, [])
                if e.get("deleted_at") is None and e.get("entry_status") != "invalid"
            )
        )
        # 不把随删除变化的库更新时间和其他引用入口写入内容指纹。
        fingerprint = _digest(
            [
                entry,
                content,
                {k: v for k, v in document.items() if k != "update_time"} if document else None,
                [{k: v for k, v in row.items() if k != "update_time"} for row in chain],
                history,
            ]
        )
        candidates[eid] = Candidate(
            eid,
            sid,
            spaces[sid]["name"],
            entry["file_name"],
            entry.get("file_level_path"),
            content["id"],
            doc_id,
            md5,
            _stamp(content["create_time"]),
            kind,
            tuple(sorted(f["id"] for f in history)),
            dependencies,
            fingerprint,
        )

    buckets: dict[tuple[int, str], list[Candidate]] = defaultdict(list)
    for candidate in candidates.values():
        buckets[candidate.space_id, candidate.md5].append(candidate)
    groups = []
    for key in sorted(buckets):
        ordered = sorted(buckets[key], key=lambda c: c.rank, reverse=True)
        if len(ordered) > 1:
            groups.append(Group(ordered[0], tuple(ordered[1:])))
    return Plan(candidates, tuple(groups), tuple(skipped))


class Report:
    """创建独占报告，落盘失败时禁止继续删除。"""

    def __init__(self, path: Path):
        self.path = path
        self.stream = None

    def __enter__(self) -> Report:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        self.stream = os.fdopen(fd, "w", encoding="utf-8")
        return self

    def emit(self, event: dict) -> None:
        self.stream.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        self.stream.flush()
        os.fsync(self.stream.fileno())

    def __exit__(self, *_: Any) -> None:
        self.stream.close()


async def execute(backend: Any, *, apply: bool, emit: Callable[[dict], None]) -> int:
    plan = await backend.scan()
    keepers = {g.keep.entry_id: g.keep for g in plan.groups}
    protected = {fid for c in keepers.values() for fid in (c.entry_id, c.content_id)}
    blocked = [
        {"entry_id": target.entry_id, "reason": "business_delete_would_affect_keeper"}
        for group in plan.groups
        for target in group.remove
        if target.impact_ids & protected
    ]
    emit(
        {
            "event": "plan",
            "mode": "apply" if apply else "dry_run",
            "groups": [asdict(g) for g in plan.groups],
            "skipped": list(plan.skipped),
            "blocked": blocked,
            "candidate_count": len(plan.candidates),
        }
    )
    if not apply:
        emit({"event": "summary", "groups": len(plan.groups), "delete_count": sum(len(g.remove) for g in plan.groups)})
        return 0
    processed = 0
    incomplete = False
    for group in plan.groups:
        for target in group.remove:
            fresh = await backend.scan(space_ids={group.keep.space_id})
            live_target = fresh.candidates.get(target.entry_id)
            live_keeper = fresh.candidates.get(group.keep.entry_id)
            live_group = next((g for g in fresh.groups if g.keep.entry_id == group.keep.entry_id), None)
            if (
                live_target is None
                or live_keeper is None
                or live_group is None
                or live_target.fingerprint != target.fingerprint
                or live_keeper.fingerprint != group.keep.fingerprint
                or target.entry_id not in {c.entry_id for c in live_group.remove}
            ):
                emit({"event": "stopped", "entry_id": target.entry_id, "reason": "group_changed_rescan_required"})
                return 6
            if live_target.impact_ids & protected:
                emit({"event": "skipped", "entry_id": target.entry_id, "reason": "business_delete_would_affect_keeper"})
                incomplete = True
                continue
            emit({"event": "delete_started", "target": asdict(live_target), "keep": asdict(live_keeper)})
            try:
                outcome = await backend.delete(live_target)
                after = await backend.scan(space_ids={group.keep.space_id})
                if any(
                    after.candidates.get(eid) is None or after.candidates[eid].fingerprint != keep.fingerprint
                    for eid, keep in keepers.items()
                    if keep.space_id == group.keep.space_id
                ):
                    raise RuntimeError("删除后保留项发生变化，停止后续删除")
                if target.entry_id in after.candidates:
                    raise RuntimeError("删除后目标仍为有效候选，停止后续删除")
            except Exception as exc:
                emit(
                    {
                        "event": "failed",
                        "entry_id": target.entry_id,
                        "error": str(exc),
                        "failure_stage": "service_setup" if isinstance(exc, DeletionSetupError) else "delete_or_verify",
                        "note": (
                            "删除服务初始化失败，未调用业务删除"
                            if isinstance(exc, DeletionSetupError)
                            else "业务删除可能已部分生效；核对数据库与异步任务后重新预览"
                        ),
                    }
                )
                return 4
            emit({"event": "delete_result", "entry_id": target.entry_id, "status": outcome})
            processed += 1
    emit(
        {
            "event": "summary",
            "processed": processed,
            "incomplete": incomplete,
            "note": "soft_deleted 表示已进入回收站；pending_cleanup/rolled_back_pending_cleanup 尚待异步清理",
        }
    )
    return 6 if incomplete else 0


async def load_inventory(tenant_id: int, space_ids: set[int] | None = None) -> Inventory:
    """使用租户上下文读取快照；版本表通过文档表限制归属。"""
    from sqlalchemy.orm import load_only
    from sqlmodel import or_, select

    from bisheng.approval.domain.models.approval_instance import ApprovalInstance
    from bisheng.core.database import get_async_db_session
    from bisheng.core.database.tenant_filter import register_tenant_filter_events
    from bisheng.knowledge.domain.models.knowledge import Knowledge
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
    from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope

    # 脚本不经过 FastAPI lifespan；必须显式安装租户过滤事件。
    register_tenant_filter_events()
    selected_spaces = select(Knowledge.id).where(Knowledge.type == 3)
    if space_ids:
        selected_spaces = selected_spaces.where(Knowledge.id.in_(sorted(space_ids)))
    linked_documents = select(KnowledgeFile.reference_document_id).where(
        KnowledgeFile.knowledge_id.in_(selected_spaces), KnowledgeFile.reference_document_id.is_not(None)
    )
    document_scope = or_(
        KnowledgeDocument.knowledge_id.in_(selected_spaces), KnowledgeDocument.id.in_(linked_documents)
    )
    selected_documents = select(KnowledgeDocument.id).where(document_scope)
    history_files = select(KnowledgeDocumentVersion.knowledge_file_id).where(
        KnowledgeDocumentVersion.document_id.in_(selected_documents)
    )
    async with get_async_db_session() as session:

        async def rows(statement: Any, fields: set[str] | None = None) -> tuple[dict, ...]:
            if fields:
                model = statement.column_descriptions[0]["entity"]
                statement = statement.options(load_only(*(getattr(model, field) for field in sorted(fields))))
            result = await session.exec(statement)
            return tuple({key: getattr(r, key) for key in fields} if fields else r.model_dump() for r in result.all())

        spaces = await rows(select(Knowledge).where(Knowledge.type == 3), {"id", "tenant_id", "name", "type", "state"})
        scopes = await rows(select(KnowledgeSpaceScope), {"space_id", "level"})
        files = await rows(
            select(KnowledgeFile).where(
                KnowledgeFile.file_type == 1,
                or_(
                    KnowledgeFile.knowledge_id.in_(selected_spaces),
                    KnowledgeFile.id.in_(history_files),
                    KnowledgeFile.reference_document_id.in_(selected_documents),
                ),
            ),
            FILE_FIELDS,
        )
        documents = await rows(select(KnowledgeDocument).where(document_scope))
        # 版本表自身没有 tenant_id，不能依赖 JOIN 的自动租户过滤。
        # 同时查文件关联，保证损坏/跨租户版本链不会被误当成无版本的普通文件。
        version_rows: dict[int, dict] = {}
        for column, identifiers in (
            (KnowledgeDocumentVersion.document_id, [d["id"] for d in documents]),
            (KnowledgeDocumentVersion.knowledge_file_id, [f["id"] for f in files]),
        ):
            for offset in range(0, len(identifiers), 500):
                batch = await rows(
                    select(KnowledgeDocumentVersion).where(column.in_(identifiers[offset : offset + 500]))
                )
                version_rows.update((v["id"], v) for v in batch)
        versions = tuple(version_rows.values())
        approvals = await rows(
            select(ApprovalInstance).where(ApprovalInstance.status.in_(ACTIVE_APPROVALS)),
            {"id", "tenant_id", "status", "scenario_code", "business_resource_type", "business_resource_id"},
        )
    return Inventory(spaces, scopes, files, documents, versions, approvals, tenant_id)


class DeletionSetupError(RuntimeError):
    """业务删除尚未调用时的服务装配错误。"""


def build_delete_service(session: Any, actor: Any) -> Any:
    """脚本自行装配现有删除服务，避免依赖部署中缺失的新工厂函数。"""
    from fastapi import Request

    from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
        KnowledgeDocumentRepositoryImpl,
    )
    from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
        KnowledgeDocumentVersionRepositoryImpl,
    )
    from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
        KnowledgeFileRepositoryImpl,
    )
    from bisheng.knowledge.domain.services.knowledge_document_distribution_service import (
        KnowledgeDocumentDistributionService,
    )
    from bisheng.knowledge.domain.services.knowledge_document_permission_activation_service import (
        KnowledgeDocumentPermissionActivationService,
    )
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

    service = KnowledgeSpaceService(
        request=Request({"type": "http", "headers": [], "method": "DELETE", "path": "/"}),
        login_user=actor,
    )
    service.knowledge_file_repo = KnowledgeFileRepositoryImpl(session)
    service.doc_repo = KnowledgeDocumentRepositoryImpl(session)
    service.version_repo = KnowledgeDocumentVersionRepositoryImpl(session)
    service.document_distribution_service = KnowledgeDocumentDistributionService(
        session=session,
        document_repository=service.doc_repo,
        version_repository=service.version_repo,
        file_repository=service.knowledge_file_repo,
        permission_activation_service=KnowledgeDocumentPermissionActivationService(
            file_repository=service.knowledge_file_repo,
        ),
    )
    return service


class Backend:
    def __init__(self, tenant_id: int, space_ids: set[int], actor: Any = None):
        self.tenant_id, self.space_ids, self.actor = tenant_id, space_ids, actor

    async def scan(self, space_ids: set[int] | None = None) -> Plan:
        selected = space_ids or self.space_ids
        if self.space_ids and not selected.issubset(self.space_ids):
            raise ValueError("复核范围超出用户指定知识库")
        return build_plan(await load_inventory(self.tenant_id, selected), selected)

    async def delete(self, target: Candidate) -> str:
        from bisheng.core.database import get_async_db_session
        from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

        if self.actor is None or self.actor.tenant_id != self.tenant_id:
            raise ValueError("删除必须使用当前租户的真实操作用户")
        async with get_async_db_session() as session:
            try:
                service = build_delete_service(session, self.actor)
            except (ImportError, AttributeError, TypeError) as exc:
                raise DeletionSetupError(f"删除服务初始化失败：{exc}") from exc
            await service.delete_file(target.entry_id)
        async with get_async_db_session() as session:
            row = await session.get(KnowledgeFile, target.entry_id)
            if row is None:
                return "removed"
            if row.deleted_at is not None:
                return "soft_deleted"
            if (
                target.entry_type == "manager"
                and row.entry_type == "manager"
                and row.knowledge_id != target.space_id
                and row.entry_status == "active"
                and row.reference_document_id == target.document_id
                and row.tenant_id == self.tenant_id
            ):
                document = await session.get(KnowledgeDocument, target.document_id)
                if (
                    document is not None
                    and document.tenant_id == self.tenant_id
                    and document.knowledge_id == row.knowledge_id
                    and document.lifecycle_status == "active"
                ):
                    return "rolled_back_pending_cleanup"
            if target.entry_type in {"manager", "publish", "share"} and row.entry_status in {
                "preparing",
                "deleting",
                "invalid",
            }:
                return "pending_cleanup"
            raise RuntimeError("业务删除返回后未观察到删除状态")


@contextmanager
def tenant_context(tenant_id: int):
    from bisheng.core.context.tenant import (
        current_tenant_id,
        set_current_tenant_id,
        set_visible_tenant_ids,
        strict_tenant_filter,
        visible_tenant_ids,
    )

    token = set_current_tenant_id(tenant_id)
    visible = set_visible_tenant_ids(frozenset({tenant_id}))
    try:
        with strict_tenant_filter():
            yield
    finally:
        visible_tenant_ids.reset(visible)
        current_tenant_id.reset(token)


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("必须为正整数")
    return number


async def resolve_operator(tenant_id: int) -> Any:
    """选择真实有效的全局超级管理员，不创建账号或修改授权。"""
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.core.openfga.manager import aget_fga_client
    from bisheng.database.constants import AdminRole
    from bisheng.user.domain.models.user import UserDao
    from bisheng.user.domain.models.user_role import UserRoleDao

    # 全局管理员可能位于根租户，仅身份查询跨租户，文档处理仍受目标租户限制。
    with bypass_tenant_filter():
        roles = await UserRoleDao.aget_roles_user([AdminRole])
        candidate_ids = {int(role.user_id) for role in roles}
        try:
            fga = await aget_fga_client()
            if fga is not None:
                tuples = await fga.read_tuples(relation="super_admin", object="system:global")
                for item in tuples:
                    key = item.get("key", item)
                    subject = str(key.get("user", ""))
                    if (
                        key.get("relation") == "super_admin"
                        and key.get("object") == "system:global"
                        and subject.startswith("user:")
                        and subject[5:].isdigit()
                    ):
                        candidate_ids.add(int(subject[5:]))
        except Exception as exc:
            # 与现有登录逻辑一致：FGA 不可用时仍可验证兼容管理员角色。
            logging.getLogger(__name__).warning("超级管理员授权查询失败，将核对兼容管理员角色：%s", exc)
        for user_id in sorted(candidate_ids):
            user = await UserDao.aget_user(user_id)
            if user is None or user.delete:
                continue
            actor = await UserPayload.init_login_user(user.user_id, user.user_name, tenant_id=tenant_id)
            if actor.is_global_super:
                return actor
    raise ValueError("未找到可用的真实超级管理员，未执行删除")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="调用现有业务执行删除；默认仅预览")
    parser.add_argument("--tenant-id", type=positive_int, help="多租户部署必填；单租户默认为 1")
    parser.add_argument("--space-id", type=positive_int, action="append", default=[], help="只处理指定知识库，可重复")
    parser.add_argument("--report-file", type=Path, help="新建 JSONL 报告路径，不覆盖已有文件")
    return parser.parse_args(argv)


async def run(args: argparse.Namespace) -> int:
    from bisheng.common.services.config_service import settings
    from bisheng.core.context.manager import close_app_context, initialize_app_context

    if settings.multi_tenant.enabled and args.tenant_id is None:
        raise ValueError("多租户部署必须显式指定 --tenant-id；每次只处理一个租户")
    tenant_id = args.tenant_id or 1
    if not settings.multi_tenant.enabled and tenant_id != 1:
        raise ValueError("单租户部署只能使用 --tenant-id 1")
    path = args.report_file or Path("migration_reports/knowledge_space_dedup") / f"dedupe-{uuid.uuid4().hex}.jsonl"
    try:
        with Report(path) as report, tenant_context(tenant_id):
            report.emit(
                {
                    "event": "run",
                    "tenant_id": tenant_id,
                    "space_ids": args.space_id,
                    "operator_selection": "auto_global_super_admin" if args.apply else "none",
                    "apply": args.apply,
                }
            )
            actor = None
            if args.apply:
                await initialize_app_context(settings)
                actor = await resolve_operator(tenant_id)
                report.emit(
                    {
                        "event": "operator",
                        "operator_user_id": actor.user_id,
                        "operator_user_name": actor.user_name,
                        "tenant_id": tenant_id,
                        "is_global_super": actor.is_global_super,
                    }
                )
            backend = Backend(tenant_id, set(args.space_id), actor)
            try:
                result = await execute(backend, apply=args.apply, emit=report.emit)
            except Exception as exc:
                report.emit({"event": "aborted", "error": str(exc)})
                raise
            print(f"报告：{path.resolve()}；退出码：{result}")
            return result
    finally:
        await close_app_context()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(run(args))
    except (ValueError, FileExistsError) as exc:
        print(f"预检失败：{exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"执行中断：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
