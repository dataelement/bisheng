#!/usr/bin/env python3
# ruff: noqa: RUF001, RUF002, RUF003
"""将科室库中入库方式为接口同步的技术诀窍文件，按二级分类迁到同租户公共技术诀窍库。

在 src/backend 下运行：
  .venv/bin/python scripts/move_clinic_knowhow_to_public.py --tenant-id 1
  .venv/bin/python scripts/move_clinic_knowhow_to_public.py --tenant-id 1 --operator-id 1 --apply

默认只读扫描；--apply 创建缺失目录，原地修改文件和文档归属、权限及共享索引元数据。
保留文件/文档/版本 ID、原对象、分块和向量，不重新解析，不调用跨库迁移引擎或 Celery。
正式执行须在停止相关文件写入的维护窗口进行；单项异常记录后继续，失败项可用 --recover-report 恢复。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import sys
import time
import traceback
from collections import defaultdict
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

LABEL = "技术诀窍"


def log_progress(message: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


@asynccontextmanager
async def progress_stage(label: str, *, interval: float = 10):
    started = time.monotonic()
    log_progress(f"开始：{label}")

    async def heartbeat():
        while True:
            await asyncio.sleep(interval)
            log_progress(f"进行中：{label}，已耗时 {time.monotonic() - started:.1f} 秒")

    task = asyncio.create_task(heartbeat())
    try:
        yield
    except BaseException:
        log_progress(f"未完成：{label}，耗时 {time.monotonic() - started:.1f} 秒")
        raise
    else:
        log_progress(f"完成：{label}，耗时 {time.monotonic() - started:.1f} 秒")
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def normalize(value: Any) -> str:
    return str(value or "").replace("\u200b", "").replace("\ufeff", "").strip()


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("必须为正整数")
    return number


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant-id", type=positive_int, help="多租户时必填；单租户默认为 1")
    parser.add_argument("--operator-id", type=positive_int, help="正式执行必填，使用真实全局超级管理员身份")
    parser.add_argument("--apply", action="store_true", help="创建目录并执行迁移；默认只预览")
    parser.add_argument(
        "--force-rewrite", action="store_true", help="以数据库为准覆盖索引归属差异；写后校验失败额外重写最多 2 次"
    )
    parser.add_argument("--recover-report", type=Path, help="修复中断报告中的索引和权限；需要 --apply")
    parser.add_argument("--report-dir", type=Path, default=Path("migration_reports/clinic_knowhow"))
    args = parser.parse_args(argv)
    if args.apply and args.operator_id is None:
        parser.error("--apply 必须指定 --operator-id")
    if args.recover_report and not args.apply:
        parser.error("--recover-report 必须同时指定 --apply")
    return args


@contextmanager
def tenant_context(tenant_id: int):
    from bisheng.core.context.tenant import current_tenant_id, strict_tenant_filter, visible_tenant_ids

    token = current_tenant_id.set(tenant_id)
    visible = visible_tenant_ids.set(frozenset({tenant_id}))
    try:
        with strict_tenant_filter():
            yield
    finally:
        visible_tenant_ids.reset(visible)
        current_tenant_id.reset(token)


def classification(config: Any) -> tuple[str, dict[str, str]]:
    items = getattr(getattr(config, "portal", None), "document_types", None) or []
    matches = [item for item in items if normalize(item.label) == LABEL]
    if len(matches) != 1:
        raise ValueError("门户一级分类“技术诀窍”缺失或重名")
    parent = matches[0]
    code = normalize(parent.code).upper()
    if not code or sum(normalize(item.code).upper() == code for item in items) != 1:
        raise ValueError("技术诀窍一级分类编码为空或重复")
    children: dict[str, str] = {}
    for child in parent.children or []:
        child_code, label = normalize(child.code).upper(), normalize(child.label)
        if not child_code or not label or child_code in children:
            raise ValueError("技术诀窍二级分类编码或名称为空，或编码重复")
        if label in {".", ".."} or "/" in label or "\\" in label:
            raise ValueError(f"二级分类名称不能直接作为目录：{label!r}")
        children[child_code] = label
    if not children or len(set(children.values())) != len(children):
        raise ValueError("技术诀窍二级分类为空或存在同名分类，无法唯一映射目录")
    return code, children


def clinic_ids(spaces: list[Any], scopes: list[Any], bindings: list[Any], departments: list[Any]) -> set[int]:
    valid_departments = {int(row.id) for row in departments if row.status == "active"}
    bound = {int(row.space_id) for row in bindings if int(row.department_id) in valid_departments}
    existing = {int(row.id) for row in spaces}
    return {
        int(row.space_id)
        for row in scopes
        if row.level in {"team", "team_ks"} and row.owner_type == "user" and int(row.space_id) in existing & bound
    }


def build_plan(snapshot: dict[str, Any], tenant_id: int) -> dict[str, Any]:
    from bisheng.knowledge.domain.constants import parse_shougang_file_encoding_codes

    code, children = classification(snapshot["config"])
    spaces = {int(row.id): row for row in snapshot["spaces"]}
    sources = clinic_ids(list(spaces.values()), snapshot["scopes"], snapshot["bindings"], snapshot["departments"])
    public_ids = {int(row.space_id) for row in snapshot["scopes"] if row.level == "public"}
    targets = [row for row in spaces.values() if int(row.id) in public_ids and normalize(row.name) == LABEL]
    if len(targets) != 1:
        raise ValueError("同租户公共“技术诀窍”库缺失或重名；脚本不自动创建知识库")
    target = targets[0]
    folders: dict[str, list[Any]] = defaultdict(list)
    for row in snapshot["files"]:
        if row.knowledge_id == target.id and row.deleted_at is None and row.file_type == 0 and not row.file_level_path:
            folders[normalize(row.file_name)].append(row)
    selected, skipped = {}, []
    for row in sorted(snapshot["files"], key=lambda item: (item.knowledge_id, item.id)):
        if row.knowledge_id not in sources or row.file_type != 1 or row.deleted_at is not None:
            continue
        parent, _ = parse_shougang_file_encoding_codes(row)
        if normalize(parent).upper() != code:
            continue
        # 与页面“入库方式=接口同步”保持同一口径。
        metadata = row.user_metadata if isinstance(row.user_metadata, dict) else {}
        if not (metadata.get("filelib_sync_endpoint") or metadata.get("external_file_id")):
            continue
        child = normalize(row.file_subcategory_code).upper()
        reason = None
        if row.entry_type not in {None, "", "manager"} or (
            row.entry_type == "manager" and row.entry_status != "active"
        ):
            reason = "非有效原文件入口"
        elif row.status != 2:
            reason = "文件尚未解析成功"
        elif child not in children:
            reason = "二级分类缺失或不属于技术诀窍"
        elif len(folders[children[child]]) > 1:
            reason = "目标根目录存在多个同名目录"
        entry = {
            "file_id": int(row.id),
            "space_id": int(row.knowledge_id),
            "file_name": row.file_name,
            "subcategory_code": child,
            "folder_name": children.get(child),
        }
        if reason:
            skipped.append({**entry, "reason": reason})
        else:
            selected[int(row.id)] = entry
    # 整条版本链必须在候选内且指向同一分类，禁止将一个文档拆到多个目录。
    chains: dict[int, set[int]] = defaultdict(set)
    for version in snapshot["versions"]:
        chains[int(version.document_id)].add(int(version.knowledge_file_id))
    for ids in chains.values():
        present = ids & selected.keys()
        if present and (
            not ids <= selected.keys() or len({selected[file_id]["subcategory_code"] for file_id in present}) != 1
        ):
            for file_id in sorted(present):
                skipped.append({**selected.pop(file_id), "reason": "版本链不完整、跨来源范围或分类不一致"})
    groups: dict[str, dict[str, Any]] = {}
    for entry in selected.values():
        label = entry["folder_name"]
        folder = folders[label][0] if folders[label] else None
        group = groups.setdefault(
            label,
            {
                "folder_name": label,
                "folder_id": int(folder.id) if folder else None,
                "create_folder": folder is None,
                "files": [],
                "status": "candidate",
            },
        )
        group["files"].append(entry)
    return {
        "tenant_id": tenant_id,
        "category_code": code,
        "ingest_method": "接口同步",
        "target_space_id": int(target.id),
        "source_spaces": [{"id": key, "name": spaces[key].name} for key in sorted(sources)],
        "candidate_files": len(selected),
        "skipped": skipped,
        "groups": list(groups.values()),
        "note": "仅迁移版本链完整且共享索引就绪的文档；保留内容和 ID，正式执行逐文档核验冲突、归属及权限。",
    }


def identity_fingerprint(document: Any, versions: list[Any], files: list[Any], entries: list[Any]) -> str:
    movable = {f.id for f in files}
    ignored = {
        "knowledge_id",
        "file_level_path",
        "level",
        "update_time",
        "desired_entry_generation",
        "applied_entry_generation",
        "original_knowledge_id",
        "original_uploader_id",
    }
    data = {
        "document": document.model_dump(mode="json", exclude=ignored),
        "versions": [v.model_dump(mode="json") for v in versions],
        "files": [f.model_dump(mode="json", exclude=ignored) for f in files],
        "entries": [e.model_dump(mode="json", exclude=ignored if e.id in movable else set()) for e in entries],
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate_document(
    unit: dict[str, Any],
    document: Any,
    versions: list[Any],
    files: list[Any],
    entries: list[Any],
    folder: Any,
    spaces: list[Any],
) -> None:
    from bisheng.knowledge.domain.constants import parse_shougang_file_encoding_codes

    tenant_id = unit["tenant_id"]
    if any(int(row.tenant_id or 1) != tenant_id for row in [document, *files, *entries, *spaces]):
        raise ValueError("文档、文件或知识库不属于指定租户")
    if document.lifecycle_status != "active" or len(files) != len(unit["files"]):
        raise ValueError("文档状态或版本文件异常")
    if (
        folder is None
        or folder.tenant_id != tenant_id
        or folder.deleted_at is not None
        or folder.file_type != 0
        or folder.knowledge_id != unit["target_space_id"]
        or folder.file_level_path
        or normalize(folder.file_name) != unit["folder_name"]
    ):
        raise ValueError("目标目录已变化")
    managers = [e for e in entries if e.entry_type == "manager" and e.entry_status == "active" and e.deleted_at is None]
    primary = [v for v in versions if v.is_primary]
    if (
        len(managers) != 1
        or len(primary) != 1
        or primary[0].id != document.primary_version_id
        or primary[0].knowledge_file_id != managers[0].id
        or managers[0].id not in {f.id for f in files}
    ):
        raise ValueError("规范文档主版本或管理入口异常")
    for entry in entries:
        if (
            entry.entry_status != "active"
            or entry.deleted_at is not None
            or entry.projection_status != "ready"
            or entry.projection_lease_owner
            or entry.projection_lease_until
            or entry.desired_content_generation != document.content_generation
            or entry.applied_content_generation != document.content_generation
            or entry.applied_entry_generation != entry.desired_entry_generation
        ):
            raise ValueError("存在未完成或不一致的共享投影，停止迁移；不触发重解析")
    expected = {f["file_id"]: f for f in unit["files"]}
    source = all(f.knowledge_id == expected[f.id]["space_id"] for f in files)
    target = all(f.knowledge_id == unit["target_space_id"] and f.file_level_path == f"/{folder.id}" for f in files)
    if not source and not (unit.get("before") and target):
        raise ValueError("版本文件归属已变化")
    if source and (
        document.knowledge_id != managers[0].knowledge_id or document.file_level_path != managers[0].file_level_path
    ):
        raise ValueError("文档和管理入口归属不一致")
    if target and (document.knowledge_id != unit["target_space_id"] or document.file_level_path != f"/{folder.id}"):
        raise ValueError("目标文档和文件归属不一致")
    if source and unit.get("before"):
        before = {f["id"]: f for f in unit["before"]["files"]}
        if any(f.file_level_path != before[f.id]["file_level_path"] or f.level != before[f.id]["level"] for f in files):
            raise ValueError("来源目录已变化，拒绝恢复")
    if unit.get("before"):
        before = {f["id"]: f for f in unit["before"]["files"]}
        for file in files:
            old = before[file.id]
            expected_origins = {
                "original_knowledge_id": (old["original_knowledge_id"] or old["knowledge_id"])
                if target
                else old["original_knowledge_id"],
                "original_uploader_id": (old["original_uploader_id"] or old["user_id"])
                if target
                else old["original_uploader_id"],
            }
            if any(getattr(file, key) != value for key, value in expected_origins.items()):
                raise ValueError("原始上传归属已变化，拒绝恢复")
    for file in files:
        metadata = file.user_metadata if isinstance(file.user_metadata, dict) else {}
        parent, _ = parse_shougang_file_encoding_codes(file)
        if (
            file.deleted_at is not None
            or file.file_type != 1
            or file.status != 2
            or normalize(parent).upper() != unit["category_code"]
            or normalize(file.file_subcategory_code).upper() != expected[file.id]["subcategory_code"]
            or not (metadata.get("filelib_sync_endpoint") or metadata.get("external_file_id"))
        ):
            raise ValueError("文件分类、入库方式或状态已变化")


def validate_chunks(
    observed: dict[str, list[dict[str, Any]]], unit: dict[str, Any], document: Any, primary: Any, model_id: str
) -> dict[str, str]:
    fingerprints = {}
    texts = {}
    for side, rows in observed.items():
        if not rows:
            raise ValueError(f"{side} 缺少已有内容；停止迁移，不重新解析")
        chunks = {}
        for row in rows:
            # 租户由集合路由隔离；旧共享 schema 的 tenant_id 固定为 1，不用于归属判断。
            identity = {
                "canonical_document_id": int(document.id),
                "canonical_version_id": int(primary.id),
                "content_file_id": int(primary.knowledge_file_id),
                "content_generation": int(document.content_generation),
            }
            if any(int(row.get(k, -1)) != v for k, v in identity.items()) or str(row.get("embedding_model_id")) != str(
                model_id
            ):
                raise ValueError(f"{side} 共享内容标识不一致")
            chunk_index = int(row["chunk_index"])
            if chunk_index < 0 or not isinstance(row.get("text"), str):
                raise ValueError(f"{side} 分块内容无效")
            payload = {k: row[k] for k in ("text", "vector", "sparse_vector") if k in row}
            if side == "milvus" and (not row.get("vector") or any(not math.isfinite(float(v)) for v in row["vector"])):
                raise ValueError("Milvus 缺少有效向量")
            if chunk_index in chunks and chunks[chunk_index] != payload:
                raise ValueError(f"{side} 同一分块存在内容冲突")
            chunks[chunk_index] = payload
        texts[side] = {key: value["text"] for key, value in chunks.items()}
        fingerprints[side] = hashlib.sha256(json.dumps(chunks, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if texts["es"] != texts["milvus"]:
        raise ValueError("ES 与 Milvus 分块不完整或内容不一致")
    return fingerprints


class Backend:
    async def load_snapshot(self, tenant_id: int, *, file_ids: set[int] | None = None) -> dict[str, Any]:
        from sqlmodel import col, or_, select

        from bisheng.core.database import get_async_db_session
        from bisheng.database.models.department import Department
        from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
        from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState, KnowledgeTypeEnum
        from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
        from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope
        from bisheng.shougang_portal_config.domain.services.portal_config_service import ShougangPortalConfigService

        result: dict[str, Any] = {"config": await ShougangPortalConfigService.get_config(tenant_id=tenant_id)}
        async with get_async_db_session() as session:
            for key, model in (
                ("scopes", KnowledgeSpaceScope),
                ("bindings", DepartmentKnowledgeSpace),
                ("departments", Department),
            ):
                result[key] = list((await session.exec(select(model))).all())
            result["spaces"] = list(
                (
                    await session.exec(
                        select(Knowledge).where(
                            Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                            Knowledge.state == KnowledgeState.PUBLISHED.value,
                            Knowledge.is_favorite.is_(False),
                        )
                    )
                ).all()
            )
            ids = clinic_ids(result["spaces"], result["scopes"], result["bindings"], result["departments"])
            public = {int(row.space_id) for row in result["scopes"] if row.level == "public"}
            targets = [
                int(row.id) for row in result["spaces"] if int(row.id) in public and normalize(row.name) == LABEL
            ]
            files = []

            async def read_pages(condition):
                after_id = 0
                while True:
                    page = list(
                        (
                            await session.exec(
                                select(KnowledgeFile)
                                .where(condition, KnowledgeFile.id > after_id, KnowledgeFile.deleted_at.is_(None))
                                .order_by(KnowledgeFile.id)
                                .limit(500)
                            )
                        ).all()
                    )
                    yield page
                    if len(page) < 500:
                        break
                    after_id = int(page[-1].id)

            # 首次按多个库批量分页；复核按已选文件 ID 查找，不再次扫全库。
            selected = sorted(ids if file_ids is None else file_ids)
            column = KnowledgeFile.knowledge_id if file_ids is None else KnowledgeFile.id
            for offset in range(0, len(selected), 400):
                condition = col(column).in_(selected[offset : offset + 400]) & (KnowledgeFile.file_type == 1)
                async for page in read_pages(condition):
                    files.extend(row for row in page if int(row.knowledge_id) in ids)
            # 规划只需要目标根目录，不加载目标库里的全部文件。
            for offset in range(0, len(targets), 400):
                condition = (
                    col(KnowledgeFile.knowledge_id).in_(targets[offset : offset + 400])
                    & (KnowledgeFile.file_type == 0)
                    & or_(KnowledgeFile.file_level_path == "", KnowledgeFile.file_level_path.is_(None))
                )
                async for page in read_pages(condition):
                    files.extend(page)
            result["files"] = files
            document_ids: set[int] = set()
            source_file_ids = [int(row.id) for row in files if row.knowledge_id not in public and row.file_type == 1]
            for offset in range(0, len(source_file_ids), 400):
                rows = (
                    await session.exec(
                        select(KnowledgeDocumentVersion).where(
                            col(KnowledgeDocumentVersion.knowledge_file_id).in_(source_file_ids[offset : offset + 400]),
                        )
                    )
                ).all()
                document_ids.update(int(row.document_id) for row in rows)
            versions = []
            ordered_ids = sorted(document_ids)
            for offset in range(0, len(ordered_ids), 400):
                versions.extend(
                    (
                        await session.exec(
                            select(KnowledgeDocumentVersion).where(
                                col(KnowledgeDocumentVersion.document_id).in_(ordered_ids[offset : offset + 400]),
                            )
                        )
                    ).all()
                )
            result["versions"] = versions
        return result

    async def operator(self, user_id: int, tenant_id: int) -> Any:
        from bisheng.common.dependencies.user_deps import UserPayload
        from bisheng.core.context.tenant import bypass_tenant_filter
        from bisheng.user.domain.models.user import UserDao

        with bypass_tenant_filter():
            user = await UserDao.aget_user(user_id)
        if user is None or user.delete:
            raise ValueError("执行账号不存在或已禁用")
        actor = await UserPayload.init_login_user(user.user_id, user.user_name, tenant_id=tenant_id)
        if not actor.is_global_super:
            raise ValueError("正式执行必须使用真实全局超级管理员")
        return actor

    async def ensure_folder(self, actor: Any, target_id: int, name: str) -> int:
        from sqlmodel import or_, select

        from bisheng.core.database import get_async_db_session
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
        from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

        async with get_async_db_session() as session:
            rows = (
                await session.exec(
                    select(KnowledgeFile).where(
                        KnowledgeFile.knowledge_id == target_id,
                        KnowledgeFile.file_type == 0,
                        KnowledgeFile.deleted_at.is_(None),
                        or_(KnowledgeFile.file_level_path == "", KnowledgeFile.file_level_path.is_(None)),
                    )
                )
            ).all()
        matches = [row for row in rows if normalize(row.file_name) == name]
        if len(matches) > 1:
            raise ValueError(f"目标同名目录不唯一：{name}")
        if matches:
            return int(matches[0].id)
        folder = await KnowledgeSpaceService(request=None, login_user=actor).add_folder(target_id, name)
        return int(folder.id)

    @asynccontextmanager
    async def locked_document(self, unit: dict[str, Any]):
        from sqlmodel import col, select

        from bisheng.core.database import get_async_db_session
        from bisheng.knowledge.domain.models.knowledge import Knowledge
        from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
        from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
        from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope
        from bisheng.user.domain.models.user import User

        async with get_async_db_session() as session:

            async def rows(model, clause):
                return list(
                    (await session.exec(select(model).where(clause).order_by(model.id).with_for_update())).all()
                )

            spaces = await rows(
                Knowledge,
                col(Knowledge.id).in_(sorted({f["space_id"] for f in unit["files"]} | {unit["target_space_id"]})),
            )
            target = next((s for s in spaces if s.id == unit["target_space_id"]), None)
            if target is None or target.type != 3 or target.state != 1 or target.is_favorite:
                raise ValueError("目标公共知识库不可用")
            scopes = list(
                (await session.exec(select(KnowledgeSpaceScope).where(KnowledgeSpaceScope.space_id == target.id))).all()
            )
            if len(scopes) != 1 or scopes[0].level != "public" or normalize(target.name) != LABEL:
                raise ValueError("目标公共库范围已变化")
            owner = await session.get(User, target.user_id)
            if owner is None or owner.delete:
                raise ValueError("目标知识库所有者不存在或已禁用")
            documents = await rows(KnowledgeDocument, KnowledgeDocument.id == unit["document_id"])
            if len(documents) != 1:
                raise ValueError("文档不存在")
            document = documents[0]
            versions = await rows(KnowledgeDocumentVersion, KnowledgeDocumentVersion.document_id == document.id)
            ids = sorted(int(v.knowledge_file_id) for v in versions)
            if ids != sorted(f["file_id"] for f in unit["files"]):
                raise ValueError("版本链发生变化或不完整")
            files = await rows(KnowledgeFile, col(KnowledgeFile.id).in_(ids))
            entries = await rows(KnowledgeFile, KnowledgeFile.reference_document_id == document.id)
            folders = await rows(KnowledgeFile, KnowledgeFile.id == unit["folder_id"])
            folder = folders[0] if len(folders) == 1 else None
            validate_document(unit, document, versions, files, entries, folder, spaces)
            from bisheng.approval.domain.models.approval_instance import ApprovalInstance

            approvals = (
                await session.exec(
                    select(ApprovalInstance).where(
                        col(ApprovalInstance.status).in_(["pending", "exception", "execute_failed"])
                    )
                )
            ).all()
            protected = set(ids) | {document.id}
            if any(
                str(a.business_resource_id or "").split(":", 1)[0] in {str(i) for i in protected}
                and ("file" in a.business_resource_type or "file" in a.scenario_code)
                for a in approvals
            ):
                raise ValueError("文档存在未结束的文件审批")
            yield session, document, versions, files, entries, folder, target, owner

    async def read_permissions(self, file_id: int) -> list[dict[str, str]]:
        from bisheng.permission.domain.services.permission_service import PermissionService

        fga = await PermissionService._aget_fga()
        if fga is None:
            raise RuntimeError("OpenFGA 不可用")
        rows = await fga.read_tuples(object=f"knowledge_file:{file_id}")
        return [{key: str(row[key]) for key in ("user", "relation", "object")} for row in rows or []]

    async def replace_permissions(self, file_id: int, desired: list[dict[str, str]]) -> None:
        from bisheng.permission.domain.schemas.tuple_operation import TupleOperation
        from bisheng.permission.domain.services.permission_service import PermissionService

        current = await self.read_permissions(file_id)
        changes = [TupleOperation(action="delete", **row) for row in current if row not in desired]
        changes += [TupleOperation(action="write", **row) for row in desired if row not in current]
        # 报告负责恢复，禁止旧权限写入进入后台重试队列后反向覆盖恢复结果。
        await PermissionService.batch_write_tuples(
            changes,
            raise_on_failure=True,
            stop_on_failure=True,
            record_failures=False,
        )
        if sorted(await self.read_permissions(file_id), key=str) != sorted(desired, key=str):
            raise RuntimeError(f"文件 {file_id} 权限写入未确认")

    async def move_unit(
        self, unit: dict[str, Any], checkpoint: Any, *, recover: bool = False, force_rewrite: bool = False
    ) -> None:
        from sqlmodel import col, or_, select

        from bisheng.knowledge.domain.contracts.shared_storage_reconcile import DocumentSnapshot, MetadataRepair
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

        async with self.locked_document(unit) as (session, document, versions, files, entries, folder, target, owner):
            manager = next(e for e in entries if e.entry_type == "manager" and e.entry_status == "active")
            active = [
                e
                for e in entries
                if e.entry_type in {"manager", "publish", "share"}
                and e.entry_status == "active"
                and e.deleted_at is None
            ]
            in_target = all(f.knowledge_id == target.id and f.file_level_path == f"/{folder.id}" for f in files)
            if not recover:
                if unit.get("before") or in_target:
                    raise ValueError("文件已迁入或存在未完成记录，请核对报告")
                primary = next(v for v in versions if v.id == document.primary_version_id)
                primary_file = next(f for f in files if f.id == primary.knowledge_file_id)
                conflicts = list(
                    (
                        await session.exec(
                            select(KnowledgeFile).where(
                                KnowledgeFile.knowledge_id == target.id,
                                KnowledgeFile.file_level_path == f"/{folder.id}",
                                KnowledgeFile.deleted_at.is_(None),
                                or_(
                                    KnowledgeFile.file_name == primary_file.file_name,
                                    KnowledgeFile.md5 == primary_file.md5 if primary_file.md5 else False,
                                ),
                                col(KnowledgeFile.id).notin_([f.id for f in files]),
                            )
                        )
                    ).all()
                )
                if conflicts:
                    unit.update(
                        status="skipped",
                        reason="目标目录存在同名或相同内容文件",
                        conflict_ids=[f.id for f in conflicts],
                    )
                    checkpoint()
                    return
            elif identity_fingerprint(document, versions, files, entries) != unit["before"]["identity"]:
                raise ValueError("文档内容、版本或入口发生变化，拒绝使用旧报告恢复")
            if recover:
                if int(owner.user_id) != unit["target_owner_id"]:
                    raise ValueError("目标库所有者已变化，拒绝使用旧报告恢复")
                for file in files:
                    allowed = unit["before"]["permissions"][str(file.id)] + unit["desired_permissions"][str(file.id)]
                    if any(row not in allowed for row in await self.read_permissions(int(file.id))):
                        raise ValueError("文件权限存在本次迁移之外的修改，拒绝覆盖")
            primary = next(v for v in versions if v.id == document.primary_version_id)
            observed = {
                side: (await self.store.read(side, [document.id])).get(document.id, []) for side in ("es", "milvus")
            }
            fingerprints = validate_chunks(observed, unit, document, primary, self.store.embedding_model_id)
            if recover and fingerprints != unit["before"]["chunks"]:
                raise ValueError("共享分块或向量已变化，拒绝恢复")
            old_ids = tuple(sorted({int(e.knowledge_id) for e in active}))
            if not recover:
                drift_count = 0
                drift_samples = []
                for side, rows in observed.items():
                    for row in rows:
                        value = row.get("knowledge_ids")
                        valid_ids = isinstance(value, (list, tuple)) and all(type(i) is int for i in value)
                        if valid_ids and tuple(sorted(set(value))) == old_ids:
                            continue
                        drift_count += 1
                        if len(drift_samples) < 10:
                            drift_samples.append(
                                {"side": side, "chunk_index": row.get("chunk_index"), "actual": repr(value)[:500]}
                            )
                if drift_count:
                    unit["initial_index_drift"] = {
                        "database_knowledge_ids": list(old_ids),
                        "mismatch_count": drift_count,
                        "samples": drift_samples,
                    }
                    checkpoint()
                    if not force_rewrite:
                        raise ValueError("共享索引归属与数据库不一致；可使用 --force-rewrite 按数据库有效入口重写归属")
                    log_progress(
                        f"文档 {document.id} 存在 {drift_count} 处旧索引归属差异，"
                        f"以数据库有效入口 {list(old_ids)} 为准计算迁移后归属并重写"
                    )
            next_generation = 1 + max(
                [int(document.content_generation)]
                + [int(e.desired_entry_generation) for e in active]
                + [int(row.get("membership_generation", 0)) for rows in observed.values() for row in rows]
            )
            if not recover:
                unit["target_owner_id"] = int(owner.user_id)
                unit["before"] = {
                    "identity": identity_fingerprint(document, versions, files, entries),
                    "document": document.model_dump(mode="json"),
                    "files": [f.model_dump(mode="json") for f in files],
                    "chunks": fingerprints,
                    "permissions": {str(f.id): await self.read_permissions(f.id) for f in files},
                }
                unit["desired_permissions"] = {
                    str(f.id): [
                        {"user": f"user:{owner.user_id}", "relation": "owner", "object": f"knowledge_file:{f.id}"},
                        {"user": f"folder:{folder.id}", "relation": "parent", "object": f"knowledge_file:{f.id}"},
                    ]
                    for f in files
                }
                unit["status"] = "prepared"
                checkpoint()  # 首次外部写入前必须落盘。
                for file in files:
                    file.original_knowledge_id = file.original_knowledge_id or file.knowledge_id
                    file.original_uploader_id = file.original_uploader_id or file.user_id
                    file.knowledge_id, file.file_level_path, file.level = target.id, f"/{folder.id}", 1
                    session.add(file)
                document.knowledge_id, document.file_level_path, document.level = target.id, f"/{folder.id}", 1
                session.add(document)
                in_target = True
            desired = unit["desired_permissions"] if in_target else unit["before"]["permissions"]
            manager.desired_entry_generation = manager.applied_entry_generation = next_generation
            session.add(manager)
            await session.flush()
            ids = tuple(sorted({int(e.knowledge_id) for e in active}))
            snapshot = DocumentSnapshot(
                document_id=int(document.id),
                tenant_id=unit["tenant_id"],
                generation=int(document.content_generation),
                knowledge_ids=ids,
                membership_generation=next_generation,
            )
            unit.update(status="syncing", destination="target" if in_target else "source", rewrite_attempts=0)
            checkpoint()
            for file in files:
                await self.replace_permissions(int(file.id), desired[str(file.id)])
            pending_sides = {"es", "milvus"}
            max_rewrites = 2 if force_rewrite else 0
            for attempt in range(max_rewrites + 1):
                for side in sorted(pending_sides):
                    # 每次以最初读取的内容为基准，适配器会重新读取并核对，不能覆盖期间发生的内容变化。
                    result = await self.store.repair(side, [MetadataRepair(snapshot, observed[side])])
                    if document.id not in result or result[document.id] is not None:
                        raise RuntimeError(f"{side} 归属同步失败：{result}")
                actual = {
                    side: (await self.store.read(side, [document.id])).get(document.id, []) for side in ("es", "milvus")
                }
                if validate_chunks(actual, unit, document, primary, self.store.embedding_model_id) != fingerprints:
                    raise RuntimeError("同步后分块或向量发生变化")
                mismatches = 0
                samples = []
                pending_sides = set()
                for side, rows in actual.items():
                    for row in rows:
                        for key, expected in snapshot.expected_metadata.items():
                            value = row.get(key)
                            if value == expected:
                                continue
                            pending_sides.add(side)
                            mismatches += 1
                            if len(samples) < 10:
                                # 只记录归属字段，限制长度，避免错误报告携带正文或向量。
                                samples.append(
                                    {
                                        "side": side,
                                        "chunk_index": row.get("chunk_index"),
                                        "field": key,
                                        "expected": repr(expected)[:500],
                                        "expected_type": type(expected).__name__,
                                        "actual": repr(value)[:500],
                                        "actual_type": type(value).__name__,
                                        "missing": key not in row,
                                    }
                                )
                if not mismatches:
                    break
                unit["index_verification"] = {"mismatch_count": mismatches, "samples": samples}
                checkpoint()
                if attempt < max_rewrites:
                    unit["rewrite_attempts"] = attempt + 1
                    unit.setdefault("rewrite_history", []).append(
                        {
                            "attempt": attempt + 1,
                            "time": datetime.now().isoformat(),
                            "destination": unit["destination"],
                            "sides": sorted(pending_sides),
                            "mismatch_count": mismatches,
                            "samples": samples,
                        }
                    )
                    checkpoint()
                    log_progress(
                        f"文档 {document.id} 归属校验不一致，强制重写 {','.join(sorted(pending_sides))} "
                        f"第 {attempt + 1}/{max_rewrites} 次，随后重新校验"
                    )
                    continue
                first = samples[0]
                raise RuntimeError(
                    f"共享索引归属写入未确认：{first['side']}，文档 {document.id}，"
                    f"分块 {first['chunk_index']}，字段 {first['field']}，"
                    f"预期 {first['expected']} ({first['expected_type']})，"
                    f"实际 {first['actual']} ({first['actual_type']})，字段缺失={first['missing']}；"
                    f"共 {mismatches} 处不一致，详情见报告 index_verification"
                )
            unit.pop("index_verification", None)
            unit["status"] = "committing"
            checkpoint()
            await session.commit()
        # 数据库已提交后刷新可重建的目录搜索与推荐元数据，异常仍保留恢复入口。
        await self.refresh_metadata(unit)
        unit["status"] = "succeeded" if in_target else "restored"
        checkpoint()

    async def refresh_metadata(self, unit: dict[str, Any]) -> None:
        from bisheng.core.database import get_async_db_session
        from bisheng.core.search.elasticsearch.manager import get_es_connection
        from bisheng.knowledge.domain import knowledge_fulltext_constants as constants
        from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_source_repository_impl import (
            KnowledgeFulltextSourceRepositoryImpl,
        )
        from bisheng.knowledge.domain.repositories.implementations.portal_recommendation_repository_impl import (
            PortalRecommendationRepositoryImpl,
        )
        from bisheng.knowledge.domain.repositories.implementations.portal_recommendation_source_repository_impl import (
            PortalRecommendationSourceRepositoryImpl,
        )
        from bisheng.knowledge.domain.services.portal_recommendation_projection_service import (
            PortalRecommendationProjectionService,
        )

        client = await get_es_connection()
        for entry in unit["files"]:
            file_id = entry["file_id"]
            async with get_async_db_session() as session:
                source = await KnowledgeFulltextSourceRepositoryImpl(session).get_current_snapshot(file_id)
                if source is None:
                    raise RuntimeError(f"迁移文件 {file_id} 不存在")
                # 全文正文沿用原值；只刷新影响目录、库和权限过滤的元数据。
                if await client.indices.exists(index=constants.KNOWLEDGE_FULLTEXT_INDEX_ALIAS):
                    result = await client.mget(index=constants.KNOWLEDGE_FULLTEXT_INDEX_ALIAS, ids=[str(file_id)])
                    docs = result.get("docs", [])
                    if len(docs) != 1 or docs[0].get("error"):
                        raise RuntimeError("全文索引查询失败")
                    row = docs[0]
                    if row.get("found"):
                        values = {
                            key: getattr(source, key)
                            for key in (
                                "knowledge_id",
                                "knowledge_name",
                                "knowledge_level",
                                "knowledge_business_domain_codes",
                                "folder_path",
                                "source_path",
                            )
                        }
                        await client.update(
                            index=constants.KNOWLEDGE_FULLTEXT_INDEX_ALIAS,
                            id=str(file_id),
                            doc=values,
                            if_seq_no=row["_seq_no"],
                            if_primary_term=row["_primary_term"],
                            refresh="wait_for",
                        )
                service = PortalRecommendationProjectionService(
                    source_repository=PortalRecommendationSourceRepositoryImpl(session),
                    projection_repository=PortalRecommendationRepositoryImpl(session),
                )
                if not await service.refresh_file(file_id, projection_version=int(time.time() * 1_000_000)):
                    raise RuntimeError("推荐目录元数据刷新未确认")
                await session.commit()

    @asynccontextmanager
    async def shared_storage(self, tenant_id: int):
        from bisheng.knowledge.rag.shared_space_storage import (
            load_tenant_routing_snapshot,
            require_initialized_shared_routing,
        )
        from bisheng.knowledge.rag.shared_storage_reconcile import SharedStorageReconcileAdapter

        async def without_maintenance_lock():
            # 适配器要求提供回调；本脚本不再获取或检查 Redis 维护锁。
            return None

        async with progress_stage("读取共享 ES/Milvus 路由"):
            route = require_initialized_shared_routing(
                tenant_id,
                await asyncio.wait_for(asyncio.to_thread(load_tenant_routing_snapshot, tenant_id), timeout=30),
            )
        self.store = SharedStorageReconcileAdapter(route, guard=without_maintenance_lock)
        try:
            yield
        finally:
            await self.store.close()


class ReportWriteError(RuntimeError):
    """报告不可写时停止，避免继续修改却无法保存错误和恢复信息。"""


def save_report(path: Path, report: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def document_units(snapshot: dict[str, Any], group: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, Any]]:
    by_file = {int(v.knowledge_file_id): int(v.document_id) for v in snapshot["versions"]}
    units: dict[int, dict[str, Any]] = {}
    for file in group["files"]:
        document_id = by_file.get(file["file_id"])
        if document_id is None:
            plan["skipped"].append({**file, "reason": "缺少规范文档版本链，不能仅修改共享索引归属"})
            continue
        unit = units.setdefault(
            document_id,
            {
                "document_id": document_id,
                "files": [],
                "tenant_id": plan["tenant_id"],
                "target_space_id": plan["target_space_id"],
                "folder_id": group["folder_id"],
                "folder_name": group["folder_name"],
                "category_code": plan["category_code"],
                "status": "candidate",
            },
        )
        unit["files"].append(file)
    return list(units.values())


async def execute(args: argparse.Namespace, backend: Any, path: Path) -> int:
    if args.recover_report:
        report = json.loads(path.read_text())
        if report.get("execution_mode") != "rehome_shared" or report.get("tenant_id") != args.tenant_id:
            raise ValueError("恢复报告类型或租户不匹配")
    else:
        report = {
            "mode": "apply" if args.apply else "dry-run",
            "execution_mode": "rehome_shared",
            "tenant_id": args.tenant_id,
            "status": "scanning",
            "units": [],
        }

    # 历史错误留在报告中，本次恢复仅汇总本次处理结果。
    run_errors: list[dict[str, Any]] = []
    report["force_rewrite"] = args.force_rewrite

    def checkpoint():
        try:
            save_report(path, report)
        except OSError as exc:
            raise ReportWriteError(f"无法保存执行报告 {path}：{exc}") from exc

    def record_error(scope: str, item: dict[str, Any], exc: Exception):
        failure = {
            "scope": scope,
            "folder_name": item.get("folder_name"),
            "document_id": item.get("document_id"),
            "file_ids": [f["file_id"] for f in item.get("files", [])],
            "stage": report.get("stage"),
            "error": str(exc),
            "error_type": type(exc).__name__,
            "traceback": traceback.format_exc(),
            "time": datetime.now().isoformat(),
        }
        run_errors.append(failure)
        report.setdefault("errors", []).append(failure)
        if scope == "document":
            item.update(
                failed_stage=item.get("status"),
                status="failed",
                error=str(exc),
                needs_recovery=bool(item.get("before")),
            )
        checkpoint()
        log_progress(
            f"失败已记录：目录 {item.get('folder_name', '')}，文档 {item.get('document_id', '-')}，"
            f"{type(exc).__name__}: {exc}；继续处理后续项"
        )

    async def process_unit(unit: dict[str, Any], label: str, *, recover: bool = False):
        try:
            async with phase(label):
                options = {}
                if recover:
                    options["recover"] = True
                if args.force_rewrite:
                    options["force_rewrite"] = True
                await backend.move_unit(unit, checkpoint, **options)
        except ReportWriteError:
            raise
        except Exception as exc:
            record_error("document", unit, exc)
        else:
            unit.pop("error", None)
            unit.pop("failed_stage", None)
            unit["needs_recovery"] = False
            checkpoint()

    def finish(success_status: str) -> int:
        report["status"] = "completed_with_errors" if run_errors else success_status
        report["summary"] = {
            "succeeded_documents": sum(u["status"] == "succeeded" for u in report["units"]),
            "restored_documents": sum(u["status"] == "restored" for u in report["units"]),
            "skipped_documents": sum(u["status"] == "skipped" for u in report["units"]),
            "failed_documents": sum(u["status"] == "failed" for u in report["units"]),
            "failed_folders": sum(e["scope"] == "folder" for e in run_errors),
            "needs_recovery": sum(
                bool(u.get("before")) and u["status"] not in {"succeeded", "restored"} for u in report["units"]
            ),
        }
        checkpoint()
        counts = report["summary"]
        log_progress(
            f"处理结束：成功 {counts['succeeded_documents']}，恢复 {counts['restored_documents']}，"
            f"跳过文档 {counts['skipped_documents']}，失败文档 {counts['failed_documents']}，"
            f"失败目录 {counts['failed_folders']}，待恢复 {counts['needs_recovery']}；报告 {path.resolve()}"
        )
        return 2 if run_errors else 0

    @asynccontextmanager
    async def phase(label):
        report["stage"] = label
        checkpoint()
        async with progress_stage(label):
            yield

    try:
        if args.recover_report:
            async with phase("校验恢复操作人"):
                await backend.operator(args.operator_id, args.tenant_id)
            async with AsyncExitStack() as stack:
                async with phase("加载共享存储路由"):
                    await stack.enter_async_context(backend.shared_storage(args.tenant_id))
                for unit in report["units"]:
                    if unit.get("before") and unit["status"] not in {"succeeded", "restored"}:
                        await process_unit(unit, f"恢复文档 {unit['document_id']}", recover=True)
            return finish("recovered")
        async with phase("首次扫描科室库文件"):
            snapshot = await backend.load_snapshot(args.tenant_id)
        plan = build_plan(snapshot, args.tenant_id)
        report["plan"], report["status"] = plan, "planned"
        checkpoint()
        print(
            f"科室库 {len(plan['source_spaces'])} 个，候选文件 {plan['candidate_files']} 个，跳过 {len(plan['skipped'])} 个",
            flush=True,
        )
        if not args.apply:
            return 0
        async with phase("校验操作人身份和权限"):
            actor = await backend.operator(args.operator_id, args.tenant_id)
        report["operator_id"] = args.operator_id
        async with AsyncExitStack() as stack:
            async with phase("加载共享存储路由"):
                await stack.enter_async_context(backend.shared_storage(args.tenant_id))
            for group in plan["groups"]:
                try:
                    async with phase(f"复核目录 {group['folder_name']} 的 {len(group['files'])} 个候选文件及版本链"):
                        fresh_snapshot = await backend.load_snapshot(
                            args.tenant_id, file_ids={f["file_id"] for f in group["files"]}
                        )
                    fresh = build_plan(fresh_snapshot, args.tenant_id)
                    current = next((g for g in fresh["groups"] if g["folder_name"] == group["folder_name"]), None)
                    if (
                        fresh["target_space_id"] != plan["target_space_id"]
                        or current is None
                        or current["files"] != group["files"]
                    ):
                        raise ValueError(f"来源或分类已变化，请重新预览：{group['folder_name']}")
                    async with phase(f"检查或创建目标目录 {group['folder_name']}"):
                        group["folder_id"] = await backend.ensure_folder(
                            actor, plan["target_space_id"], group["folder_name"]
                        )
                    units = document_units(fresh_snapshot, group, plan)
                except ReportWriteError:
                    raise
                except Exception as exc:
                    record_error("folder", group, exc)
                    continue
                report["units"].extend(units)
                checkpoint()
                for index, unit in enumerate(units, start=1):
                    await process_unit(
                        unit, f"目录 {group['folder_name']}：文档 {index}/{len(units)}，ID {unit['document_id']}"
                    )
        return finish(
            "completed_with_skips"
            if plan["skipped"] or any(u["status"] == "skipped" for u in report["units"])
            else "completed"
        )
    except BaseException as exc:
        report["status"] = (
            "needs_recovery"
            if any(u.get("before") and u["status"] not in {"succeeded", "restored"} for u in report["units"])
            else "failed"
        )
        report["error"] = str(exc)
        checkpoint()
        raise


async def run(args: argparse.Namespace) -> int:
    from bisheng.common.services.config_service import settings
    from bisheng.core.context.manager import close_app_context, initialize_app_context

    if args.tenant_id is None:
        if settings.multi_tenant.enabled:
            raise ValueError("多租户部署必须显式指定 --tenant-id")
        args.tenant_id = 1
    args.report_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = args.recover_report or args.report_dir / f"{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}.json"
    print(f"报告：{path.resolve()}", flush=True)
    try:
        await initialize_app_context(config=settings)
        with tenant_context(args.tenant_id):
            return await execute(args, Backend(), path)
    finally:
        await close_app_context()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print(
            "脚本执行已中断；已完成的迁移不会回退，请用 --recover-report 核对并恢复报告中的未完成文档。",
            file=sys.stderr,
        )
        return 130
    except Exception as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
