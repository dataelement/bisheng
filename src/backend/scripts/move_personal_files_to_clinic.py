#!/usr/bin/env python3
# ruff: noqa: RUF001, RUF002, RUF003
"""按上传人的主组织，将个人库文件原地迁入最近科室绑定的首个科室库。

在 src/backend 下运行：
  .venv/bin/python scripts/move_personal_files_to_clinic.py --tenant-id 1 --folder-path 'A/B'
  .venv/bin/python scripts/move_personal_files_to_clinic.py --tenant-id 1 --folder-path 'A/B' --operator-id 1 --apply

省略 --folder-path 扫描个人库全部文件。完整路径匹配、包含子目录，保留原完整路径。
原始上传人缺失时回退当前上传人；只从主组织沿父级寻找 org_level=office。
默认只读预览；--apply 创建缺失目录、移动归属并同步权限和共享索引，不重新解析。
只支持已就绪共享存储；正式执行必须处于停止相关写入的维护窗口。
失败逐项记录，--recover-report 修复中断项，不撤销成功迁移。
目标库所有者失效时，可显式加 --use-operator-as-file-owner，使用操作人作为文件权限所有者。
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

REPORT_KIND = "personal_to_clinic_shared_v1"


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
    parser.add_argument("--folder-path", help="相对个人库根目录的完整路径；省略时扫描全部文件，/ 表示根目录")
    parser.add_argument("--apply", action="store_true", help="创建目录并执行迁移；默认只预览")
    parser.add_argument(
        "--force-rewrite", action="store_true", help="以数据库为准覆盖索引归属差异；写后校验失败额外重写最多 2 次"
    )
    parser.add_argument(
        "--use-operator-as-file-owner",
        action="store_true",
        help="仅在目标库所有者不存在或禁用时，用 --operator-id 作为文件权限所有者；不改上传人和库所有者",
    )
    parser.add_argument("--recover-report", type=Path, help="修复中断报告中的索引和权限；需要 --apply")
    parser.add_argument("--report-dir", type=Path, default=Path("migration_reports/personal_to_clinic"))
    args = parser.parse_args(argv)
    if args.apply and args.operator_id is None:
        parser.error("--apply 必须指定 --operator-id")
    if args.recover_report and not args.apply:
        parser.error("--recover-report 必须同时指定 --apply")
    try:
        args.folder_parts = parse_folder_path(args.folder_path)
    except ValueError as exc:
        parser.error(str(exc))
    if args.recover_report and args.folder_path is not None:
        parser.error("恢复使用报告中的路径，不得同时指定 --folder-path")
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


class SkipFile(ValueError):
    """可解释的不满足迁移条件，不能静默忽略。"""

    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code = code


def parse_folder_path(value: str | None) -> tuple[str, ...]:
    if value is None or value == "/":
        return ()
    parts = tuple(value.strip("/").split("/"))
    if any(not part.strip() or part in {".", ".."} or "\\" in part for part in parts):
        raise ValueError("--folder-path 必须为完整目录路径，不能包含空段、.、.. 或反斜杠")
    return parts


def target_path(folder: Any) -> str:
    return f"{folder.file_level_path or ''}/{folder.id}" if folder else ""


def folder_parts_for(row: Any, files: dict[int, Any]) -> tuple[str, ...]:
    path = row.file_level_path or ""
    try:
        ids = [int(value) for value in path.split("/")[1:]] if path else []
    except ValueError as exc:
        raise SkipFile("invalid_folder_path", "源文件目录路径损坏") from exc
    if path != "".join(f"/{value}" for value in ids) or len(set(ids)) != len(ids) or row.level != len(ids):
        raise SkipFile("invalid_folder_path", "源文件目录路径或层级异常")
    names, prefix = [], ""
    for depth, folder_id in enumerate(ids):
        folder = files.get(folder_id)
        if (
            folder is None
            or folder.file_type != 0
            or folder.deleted_at is not None
            or folder.knowledge_id != row.knowledge_id
            or folder.tenant_id != row.tenant_id
            or (folder.file_level_path or "") != prefix
            or folder.level != depth
            or not folder.file_name
            or folder.file_name in {".", ".."}
            or "/" in folder.file_name
            or "\\" in folder.file_name
        ):
            raise SkipFile("invalid_folder_path", "源目录缺失、跨库或层级不一致")
        names.append(folder.file_name)
        prefix += f"/{folder_id}"
    return tuple(names)


class Routing:
    def __init__(self, snapshot: dict[str, Any]):
        self.spaces = {int(row.id): row for row in snapshot["spaces"]}
        self.users = {int(row.user_id): row for row in snapshot["users"]}
        self.departments = {int(row.id): row for row in snapshot["departments"]}
        self.primary: dict[int, list[int]] = defaultdict(list)
        for row in snapshot["memberships"]:
            if row.is_primary == 1:
                self.primary[int(row.user_id)].append(int(row.department_id))
        clinics = {
            int(row.space_id)
            for row in snapshot["scopes"]
            if row.level in {"team", "team_ks"} and row.owner_type == "user" and row.space_id in self.spaces
        }
        self.targets: dict[int, set[int]] = defaultdict(set)
        for row in snapshot["bindings"]:
            if row.space_id in clinics:
                self.targets[int(row.department_id)].add(int(row.space_id))

    def resolve(self, file: Any) -> dict[str, Any]:
        uploader = file.original_uploader_id or file.user_id
        origin = "original_uploader_id" if file.original_uploader_id else "user_id"
        if not uploader:
            raise SkipFile("missing_uploader", "原始上传人和当前上传人均缺失")
        user = self.users.get(int(uploader))
        if user is None or user.delete:
            raise SkipFile("unavailable_uploader", "上传人不存在或已停用")
        departments = self.primary.get(int(uploader), [])
        if not departments:
            raise SkipFile("missing_primary_department", "上传人没有主组织")
        if len(departments) != 1:
            raise SkipFile("ambiguous_primary_department", "上传人存在多个主组织")
        department_id, visited = departments[0], set()
        while department_id:
            if department_id in visited:
                raise SkipFile("department_cycle", "组织父级关系存在循环")
            visited.add(department_id)
            department = self.departments.get(department_id)
            if department is None or department.status != "active":
                raise SkipFile("unavailable_department", "主组织或父级组织不存在或已停用")
            if department.org_level == "office":
                targets = sorted(self.targets.get(department_id, set()))
                if not targets:
                    raise SkipFile("missing_clinic", "最近科室未绑定有效科室库")
                return {
                    "uploader_id": int(uploader),
                    "uploader_source": origin,
                    "primary_department_id": departments[0],
                    "office_id": department_id,
                    "target_space_id": targets[0],
                }
            department_id = department.parent_id
        raise SkipFile("missing_office", "主组织及其父级没有科室标签")


def build_plan(snapshot: dict[str, Any], tenant_id: int, requested: tuple[str, ...] = ()) -> dict[str, Any]:
    routing = Routing(snapshot)
    spaces = routing.spaces
    sources = {
        int(row.space_id)
        for row in snapshot["scopes"]
        if row.level == "personal" and row.owner_type == "user" and row.space_id in spaces
    }
    by_id = {int(row.id): row for row in snapshot["files"]}
    by_location: dict[tuple[int, str, str], list[Any]] = defaultdict(list)
    for row in snapshot["files"]:
        if row.deleted_at is None:
            by_location[(row.knowledge_id, row.file_level_path or "", row.file_name)].append(row)
    chains: dict[int, set[int]] = defaultdict(set)
    documents: dict[int, set[int]] = defaultdict(set)
    for version in snapshot["versions"]:
        chains[int(version.document_id)].add(int(version.knowledge_file_id))
        documents[int(version.knowledge_file_id)].add(int(version.document_id))
    selected, skipped, matched = {}, [], set()
    for row in sorted(snapshot["files"], key=lambda item: (item.knowledge_id, item.id)):
        if row.knowledge_id not in sources or row.file_type == 0 or row.deleted_at is not None:
            continue
        entry = {
            "file_id": int(row.id),
            "space_id": int(row.knowledge_id),
            "file_name": row.file_name,
            "source_path": row.file_level_path or "",
            "source_level": row.level,
            "original_uploader_id": row.original_uploader_id,
            "user_id": row.user_id,
        }
        try:
            parts = folder_parts_for(row, by_id)
            if parts[: len(requested)] != requested:
                continue
            matched.add(row.knowledge_id)
            entry.update(folder_parts=list(parts), folder_name="/".join(parts))
            prefix = ""
            for folder_id in (row.file_level_path or "").split("/")[1:]:
                folder = by_id[int(folder_id)]
                if len(by_location[(row.knowledge_id, prefix, folder.file_name)]) != 1:
                    raise SkipFile("ambiguous_source_folder", "来源完整路径存在同名目录或文件冲突")
                prefix += f"/{folder_id}"
            if row.file_type != 1:
                raise SkipFile("unsupported_file_type", "不是可迁移的物理文件")
            if row.entry_type not in {None, "", "manager"} or (
                row.entry_type == "manager" and row.entry_status != "active"
            ):
                raise SkipFile("not_manager", "非有效原文件入口")
            if row.status != 2:
                raise SkipFile("not_parsed", "文件尚未解析成功")
            entry.update(routing.resolve(row))
            if len(documents[row.id]) != 1:
                raise SkipFile("invalid_version_chain", "缺少唯一规范文档版本链")
            entry["document_id"] = next(iter(documents[row.id]))
            parent_path, missing = "", False
            for name in parts:
                matches = by_location.get((entry["target_space_id"], parent_path, name), []) if not missing else []
                if len(matches) > 1 or (matches and matches[0].file_type != 0):
                    raise SkipFile("target_folder_conflict", "目标路径存在重名目录或同名文件")
                if matches:
                    folder = matches[0]
                    if folder_parts_for(folder, by_id) != parts[: folder.level]:
                        raise SkipFile("target_folder_conflict", "目标目录结构异常")
                    parent_path = target_path(folder)
                else:
                    missing = True
            selected[row.id] = entry
        except SkipFile as exc:
            skipped.append({**entry, "reason_code": exc.code, "reason": str(exc)})
    for ids in chains.values():
        present = ids & selected.keys()
        routes = {
            (
                selected[i]["target_space_id"],
                tuple(selected[i]["folder_parts"]),
                selected[i]["space_id"],
                selected[i]["source_path"],
            )
            for i in present
        }
        if present and (not ids <= selected.keys() or len(routes) != 1):
            for file_id in sorted(present):
                skipped.append(
                    {
                        **selected.pop(file_id),
                        "reason_code": "incomplete_version_chain",
                        "reason": "版本链不完整、跨来源范围或迁移目标不一致",
                    }
                )
    groups: dict[tuple, dict[str, Any]] = {}
    for entry in selected.values():
        key = entry["target_space_id"], tuple(entry["folder_parts"])
        group = groups.setdefault(
            key,
            {
                "target_space_id": key[0],
                "folder_parts": list(key[1]),
                "folder_name": "/".join(key[1]),
                "folder_id": None,
                "files": [],
                "status": "candidate",
            },
        )
        group["files"].append(entry)
    return {
        "tenant_id": tenant_id,
        "requested_path": "/".join(requested),
        "source_spaces": [{"id": sid, "name": spaces[sid].name} for sid in sorted(sources)],
        "candidate_files": len(selected),
        "skipped": skipped,
        "groups": list(groups.values()),
        "spaces_without_matching_files": sorted(sources - matched),
        "note": "默认只读；正式执行复核版本、投影、索引和权限；未通过的文件逐项记录。",
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
    if any(int(row.tenant_id or 1) != unit["tenant_id"] for row in [document, *files, *entries, *spaces]):
        raise SkipFile("tenant_mismatch", "文档、文件或知识库不属于指定租户")
    if document.lifecycle_status != "active" or len(files) != len(unit["files"]):
        raise SkipFile("invalid_document", "文档状态或版本文件异常")
    if unit["folder_parts"]:
        if (
            folder is None
            or folder.tenant_id != unit["tenant_id"]
            or folder.deleted_at is not None
            or folder.file_type != 0
            or folder.knowledge_id != unit["target_space_id"]
            or folder.file_name != unit["folder_parts"][-1]
            or folder.level != len(unit["folder_parts"]) - 1
        ):
            raise SkipFile("target_folder_changed", "目标目录已变化")
    elif folder is not None:
        raise SkipFile("target_folder_changed", "预期目标为根目录")
    managers = [e for e in entries if e.entry_type == "manager" and e.entry_status == "active" and e.deleted_at is None]
    primary = [v for v in versions if v.is_primary]
    if (
        len(managers) != 1
        or len(primary) != 1
        or primary[0].id != document.primary_version_id
        or primary[0].knowledge_file_id != managers[0].id
        or managers[0].id not in {f.id for f in files}
    ):
        raise SkipFile("invalid_primary_version", "规范文档主版本或管理入口异常")
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
            raise SkipFile("projection_not_ready", "存在未完成或不一致的共享投影")
    expected = {f["file_id"]: f for f in unit["files"]}
    source = all(
        f.knowledge_id == expected[f.id]["space_id"]
        and (f.file_level_path or "") == expected[f.id]["source_path"]
        and f.level == expected[f.id]["source_level"]
        for f in files
    )
    target = all(
        f.knowledge_id == unit["target_space_id"]
        and (f.file_level_path or "") == target_path(folder)
        and f.level == len(unit["folder_parts"])
        for f in files
    )
    if not source and not (unit.get("before") and target):
        raise SkipFile("source_changed", "版本文件归属或来源目录已变化")
    if (
        document.knowledge_id != managers[0].knowledge_id
        or (document.file_level_path or "") != (managers[0].file_level_path or "")
        or document.level != managers[0].level
    ):
        raise SkipFile("document_location_mismatch", "文档和管理入口归属不一致")
    if any(f.deleted_at is not None or f.file_type != 1 or f.status != 2 for f in files):
        raise SkipFile("file_not_ready", "版本文件已删除、类型异常或未解析成功")
    before = {f["id"]: f for f in unit["before"]["files"]} if unit.get("before") else {}
    for file in files:
        old = before.get(file.id, expected[file.id])
        expected_uploader = (old["original_uploader_id"] or old["user_id"]) if target else old["original_uploader_id"]
        if file.original_uploader_id != expected_uploader or file.user_id != old["user_id"]:
            raise SkipFile("uploader_changed", "上传人已变化")
        if before:
            original_space = (
                (old["original_knowledge_id"] or old["knowledge_id"]) if target else old["original_knowledge_id"]
            )
            if file.original_knowledge_id != original_space:
                raise SkipFile("original_space_changed", "原始知识库已变化，拒绝恢复")


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
    def __init__(self) -> None:
        self.operator_id: int | None = None
        self.use_operator_as_file_owner = False

    async def routing_snapshot(
        self, session: Any, user_ids: set[int], *, include_catalog: bool = True
    ) -> dict[str, Any]:
        from sqlmodel import col, select

        from bisheng.database.models.department import Department, UserDepartment
        from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
        from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState, KnowledgeTypeEnum
        from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope
        from bisheng.user.domain.models.user import User

        result = {}
        for key, model in (
            ("scopes", KnowledgeSpaceScope),
            ("bindings", DepartmentKnowledgeSpace),
            ("departments", Department),
        ):
            if include_catalog:
                result[key] = list((await session.exec(select(model))).all())
        if include_catalog:
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
        result["memberships"], result["users"] = [], []
        ordered = sorted(user_ids)
        for offset in range(0, len(ordered), 400):
            batch = ordered[offset : offset + 400]
            result["memberships"].extend(
                (await session.exec(select(UserDepartment).where(col(UserDepartment.user_id).in_(batch)))).all()
            )
            result["users"].extend((await session.exec(select(User).where(col(User.user_id).in_(batch)))).all())
        return result

    async def load_snapshot(self, tenant_id: int, *, file_ids: set[int] | None = None) -> dict[str, Any]:
        from sqlmodel import col, select

        from bisheng.core.database import get_async_db_session
        from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

        async with get_async_db_session() as session:
            result = await self.routing_snapshot(session, set())
            existing = {s.id for s in result["spaces"]}
            sources = {
                s.space_id
                for s in result["scopes"]
                if s.level == "personal" and s.owner_type == "user" and s.space_id in existing
            }
            files = []

            async def pages(condition):
                after_id = 0
                while True:
                    page = list(
                        (
                            await session.exec(
                                select(KnowledgeFile)
                                .where(
                                    condition,
                                    KnowledgeFile.deleted_at.is_(None),
                                    KnowledgeFile.id > after_id,
                                )
                                .order_by(KnowledgeFile.id)
                                .limit(500)
                            )
                        ).all()
                    )
                    files.extend(page)
                    if len(page) < 500:
                        return
                    after_id = page[-1].id

            ordered = sorted(sources if file_ids is None else file_ids)
            column = KnowledgeFile.knowledge_id if file_ids is None else KnowledgeFile.id
            for offset in range(0, len(ordered), 400):
                await pages(col(column).in_(ordered[offset : offset + 400]) & (KnowledgeFile.file_type != 0))
            selected_files = [f for f in files if f.knowledge_id in sources]
            files = selected_files.copy()
            user_ids = {
                int(f.original_uploader_id or f.user_id) for f in selected_files if f.original_uploader_id or f.user_id
            }
            result.update(await self.routing_snapshot(session, user_ids, include_catalog=False))
            routing, targets = Routing(result), set()
            for file in selected_files:
                try:
                    targets.add(routing.resolve(file)["target_space_id"])
                except SkipFile:
                    # 只用于缩小目录查询；具体不符合原因由 build_plan 逐文件写入报告。
                    continue
            relevant_sources = sources if file_ids is None else {f.knowledge_id for f in selected_files}
            ordered = sorted(relevant_sources | targets)
            for offset in range(0, len(ordered), 400):
                await pages(
                    col(KnowledgeFile.knowledge_id).in_(ordered[offset : offset + 400]) & (KnowledgeFile.file_type == 0)
                )
            result["files"] = files
            document_ids = set()
            ordered = sorted(f.id for f in selected_files)
            for offset in range(0, len(ordered), 400):
                rows = (
                    await session.exec(
                        select(KnowledgeDocumentVersion).where(
                            col(KnowledgeDocumentVersion.knowledge_file_id).in_(ordered[offset : offset + 400])
                        )
                    )
                ).all()
                document_ids.update(int(v.document_id) for v in rows)
            versions = []
            ordered = sorted(document_ids)
            for offset in range(0, len(ordered), 400):
                versions.extend(
                    (
                        await session.exec(
                            select(KnowledgeDocumentVersion).where(
                                col(KnowledgeDocumentVersion.document_id).in_(ordered[offset : offset + 400])
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

    async def ensure_folder(
        self, actor: Any, target_id: int, parts: list[str], group: dict[str, Any], checkpoint: Any
    ) -> int | None:
        from sqlmodel import or_, select

        from bisheng.core.database import get_async_db_session
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
        from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

        parent, path = None, ""
        for depth, name in enumerate(parts):
            async with get_async_db_session() as session:
                condition = (
                    KnowledgeFile.file_level_path == path
                    if path
                    else or_(KnowledgeFile.file_level_path == "", KnowledgeFile.file_level_path.is_(None))
                )
                rows = list(
                    (
                        await session.exec(
                            select(KnowledgeFile).where(
                                KnowledgeFile.knowledge_id == target_id,
                                condition,
                                KnowledgeFile.file_name == name,
                                KnowledgeFile.deleted_at.is_(None),
                            )
                        )
                    ).all()
                )
            if len(rows) > 1 or (rows and (rows[0].file_type != 0 or rows[0].level != depth)):
                raise SkipFile("target_folder_conflict", f"目标目录冲突：{'/'.join(parts[: depth + 1])}")
            if rows:
                folder = rows[0]
            else:
                event = {"parent_id": parent, "name": name, "status": "creating"}
                group.setdefault("created_folders", []).append(event)
                checkpoint()
                folder = await KnowledgeSpaceService(request=None, login_user=actor).add_folder(target_id, name, parent)
                event.update(folder_id=int(folder.id), status="created")
                checkpoint()
            if (
                folder.knowledge_id != target_id
                or folder.tenant_id != actor.tenant_id
                or (folder.file_level_path or "") != path
                or folder.level != depth
            ):
                raise ValueError("新建或复用目录归属与预期不符")
            parent, path = int(folder.id), target_path(folder)
        return parent

    async def resolve_file_owner(self, session: Any, target: Any, unit: dict[str, Any]) -> Any:
        from bisheng.user.domain.models.user import User

        fallback = unit.get("owner_fallback") if unit.get("before") else None
        if fallback:
            # 恢复沿用首次迁移记录，不因更换操作人或原账号重新启用而改写授权。
            if target.user_id != fallback["original_owner_id"]:
                raise ValueError("目标库所有者已变化，拒绝使用旧报告恢复")
            owner = await session.get(User, fallback["operator_id"])
            if owner is None or owner.delete:
                raise ValueError("报告中记录的文件权限所有者不存在或已禁用，拒绝恢复")
            return owner

        owner = await session.get(User, target.user_id) if target.user_id else None
        if owner is not None and not owner.delete:
            if not unit.get("before"):
                unit.pop("owner_fallback", None)
            return owner
        # 旧恢复报告不能借助新开关重新选择所有者，避免改变当时已写入的权限。
        if unit.get("before") or not self.use_operator_as_file_owner:
            raise ValueError("目标知识库所有者不存在或已禁用")
        if self.operator_id is None:
            raise ValueError("尚未校验操作人，不能接管文件权限")
        operator = await session.get(User, self.operator_id)
        if operator is None or operator.delete:
            raise ValueError("操作人不存在或已禁用，不能接管文件权限")
        unit["owner_fallback"] = {"original_owner_id": target.user_id, "operator_id": int(operator.user_id)}
        log_progress(
            f"目标库 {target.id} 所有者失效，文档 {unit['document_id']} 的文件权限所有者使用操作人 {operator.user_id}"
        )
        return operator

    @asynccontextmanager
    async def locked_document(self, unit: dict[str, Any]):
        from sqlmodel import col, select

        from bisheng.core.database import get_async_db_session
        from bisheng.knowledge.domain.models.knowledge import Knowledge
        from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
        from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
        from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope

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
                raise ValueError("目标科室知识库不可用")
            scopes = list(
                (await session.exec(select(KnowledgeSpaceScope).where(KnowledgeSpaceScope.space_id == target.id))).all()
            )
            if len(scopes) != 1 or scopes[0].level not in {"team", "team_ks"} or scopes[0].owner_type != "user":
                raise ValueError("目标科室库范围已变化")
            owner = await self.resolve_file_owner(session, target, unit)
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
            folders = await rows(KnowledgeFile, KnowledgeFile.id == unit["folder_id"]) if unit["folder_id"] else []
            folder = folders[0] if len(folders) == 1 else None
            validate_document(unit, document, versions, files, entries, folder, spaces)
            await self.validate_route(session, unit, files, folder)
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

    async def validate_route(self, session: Any, unit: dict[str, Any], files: list[Any], folder: Any) -> None:
        from sqlmodel import col, select

        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

        required_ids = {
            int(part)
            for row in [*files, *([folder] if folder else [])]
            for part in (row.file_level_path or "").split("/")[1:]
        }
        directories = [folder] if folder else []
        ordered = sorted(required_ids)
        for offset in range(0, len(ordered), 400):
            directories.extend(
                (
                    await session.exec(
                        select(KnowledgeFile)
                        .where(
                            col(KnowledgeFile.id).in_(ordered[offset : offset + 400]),
                        )
                        .with_for_update()
                    )
                ).all()
            )
        by_id = {row.id: row for row in directories}
        if folder and (*folder_parts_for(folder, by_id), folder.file_name) != tuple(unit["folder_parts"]):
            raise SkipFile("target_folder_changed", "目标完整目录路径已变化")
        for file in files:
            if folder_parts_for(file, by_id) != tuple(unit["folder_parts"]):
                raise SkipFile("source_changed", "来源完整目录路径已变化")
        # 恢复以报告和数据库已提交状态为准，不根据新的组织关系重新选目标。
        if unit.get("before"):
            return
        snapshot = await self.routing_snapshot(session, {int(f.original_uploader_id or f.user_id) for f in files})
        routing = Routing(snapshot)
        personal = {
            s.space_id
            for s in snapshot["scopes"]
            if s.level == "personal" and s.owner_type == "user" and s.space_id in routing.spaces
        }
        expected = {f["file_id"]: f for f in unit["files"]}
        for file in files:
            if file.knowledge_id not in personal:
                raise SkipFile("source_changed", "来源不再是有效个人知识库")
            route = routing.resolve(file)
            if any(value != expected[file.id][key] for key, value in route.items()):
                raise SkipFile("route_changed", "上传人主组织、科室或科室库绑定已变化")

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
            in_target = all(f.knowledge_id == target.id and f.file_level_path == target_path(folder) for f in files)
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
                                (KnowledgeFile.file_level_path == target_path(folder))
                                if folder
                                else or_(KnowledgeFile.file_level_path == "", KnowledgeFile.file_level_path.is_(None)),
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
                        reason_code="target_file_conflict",
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
                        {
                            "user": (f"folder:{folder.id}" if folder else f"knowledge_space:{target.id}"),
                            "relation": "parent",
                            "object": f"knowledge_file:{f.id}",
                        },
                    ]
                    for f in files
                }
                unit["status"] = "prepared"
                checkpoint()  # 首次外部写入前必须落盘。
                for file in files:
                    file.original_knowledge_id = file.original_knowledge_id or file.knowledge_id
                    file.original_uploader_id = file.original_uploader_id or file.user_id
                    file.knowledge_id, file.file_level_path, file.level = (
                        target.id,
                        target_path(folder),
                        (folder.level + 1 if folder else 0),
                    )
                    session.add(file)
                document.knowledge_id, document.file_level_path, document.level = (
                    target.id,
                    target_path(folder),
                    (folder.level + 1 if folder else 0),
                )
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


def save_report(path: Path, report: Any) -> None:
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


def unmigrated_files(report: dict[str, Any]) -> list[dict[str, Any]]:
    """只投影已匹配但未完成迁移的文件，不暴露计划和恢复快照。"""
    result = {row["file_id"]: dict(row) for row in report.get("not_migrated", [])}

    def add(file: dict[str, Any], reason: str) -> None:
        result[file["file_id"]] = {
            "file_id": file["file_id"],
            "file_name": file["file_name"],
            "source_space_id": file["space_id"],
            "source_folder": "/".join(file["folder_parts"]) if "folder_parts" in file else file.get("source_path", ""),
            "reason": (reason.splitlines() or ["执行未完成"])[0][:500],
        }

    requested = tuple(report.get("folder_parts", []))
    plan = report.get("plan", {})
    for file in plan.get("skipped", []):
        # 路径损坏且无法确认匹配时，不把它当成指定目录下的文件。
        if requested and tuple(file.get("folder_parts", []))[: len(requested)] != requested:
            continue
        add(file, file["reason"])
    units = {file["file_id"]: unit for unit in report.get("units", []) for file in unit["files"]}
    candidates = {file["file_id"]: file for group in plan.get("groups", []) for file in group["files"]}
    candidates.update({file["file_id"]: file for unit in report.get("units", []) for file in unit["files"]})
    interrupted = report.get("status") in {"failed", "needs_recovery"}
    for file_id, file in candidates.items():
        unit = units.get(file_id, {})
        status = unit.get("status")
        if status == "succeeded":
            result.pop(file_id, None)
        elif status == "skipped":
            specific = next((row["reason"] for row in unit.get("recheck_skips", []) if row["file_id"] == file_id), None)
            add(file, specific or unit.get("reason", "未满足迁移条件"))
        elif status == "restored":
            add(file, "迁移未完成，已恢复至原库")
        elif status == "failed" or interrupted:
            detail = unit.get("error") or report.get("error") or "执行中断"
            prefix = (
                "迁移未完成，需恢复核验"
                if unit.get("before")
                else "未迁移，执行失败"
                if status == "failed"
                else "未迁移，执行中断未处理"
            )
            add(file, f"{prefix}：{detail}")
    return sorted(result.values(), key=lambda row: (row["source_space_id"], row["file_id"]))


def document_units(snapshot: dict[str, Any], group: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, Any]]:
    units: dict[int, dict[str, Any]] = {}
    for file in group["files"]:
        unit = units.setdefault(
            file["document_id"],
            {
                "document_id": file["document_id"],
                "files": [],
                "tenant_id": plan["tenant_id"],
                "target_space_id": group["target_space_id"],
                "folder_id": group["folder_id"],
                "folder_name": group["folder_name"],
                "folder_parts": group["folder_parts"],
                "status": "candidate",
            },
        )
        unit["files"].append(file)
    return list(units.values())


async def execute(args: argparse.Namespace, backend: Any, path: Path) -> int:
    recovery_path = path if args.recover_report else path.parent / "recovery" / path.name
    if args.recover_report:
        report = json.loads(path.read_text())
        if (
            not isinstance(report, dict)
            or report.get("execution_mode") != REPORT_KIND
            or report.get("tenant_id") != args.tenant_id
        ):
            raise ValueError("恢复报告类型或租户不匹配")
        path = (
            path.parent.parent / path.name
            if path.parent.name == "recovery"
            else path.with_name(f"{path.stem}.unmigrated.json")
        )
        # 旧报告中的错误不应把本次尚未处理的文档直接显示为中断。
        report["status"] = "recovering"
    else:
        report = {
            "mode": "apply" if args.apply else "dry-run",
            "execution_mode": "personal_to_clinic_shared_v1",
            "tenant_id": args.tenant_id,
            "folder_parts": list(args.folder_parts),
            "status": "scanning",
            "units": [],
        }

    # 历史错误留在报告中，本次恢复仅汇总本次处理结果。
    run_errors: list[dict[str, Any]] = []
    report["force_rewrite"] = args.force_rewrite

    def checkpoint():
        try:
            rows = unmigrated_files(report)
            if args.apply:
                recovery_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                # 先持久化未完成单元，成功单元不再保存大体积 before 快照。
                save_report(
                    recovery_path,
                    {
                        "execution_mode": REPORT_KIND,
                        "tenant_id": args.tenant_id,
                        "mode": "apply",
                        "folder_parts": report.get("folder_parts", []),
                        "units": [
                            unit
                            for unit in report["units"]
                            if unit.get("before") and unit["status"] not in {"succeeded", "restored"}
                        ],
                        "not_migrated": rows,
                    },
                )
            save_report(path, rows)
        except OSError as exc:
            raise ReportWriteError(f"无法保存执行报告 {path}：{exc}") from exc

    def record_error(scope: str, item: dict[str, Any], exc: Exception):
        failure = {
            "scope": scope,
            "folder_name": item.get("folder_name"),
            "target_space_id": item.get("target_space_id"),
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
        except SkipFile as exc:
            if unit.get("before"):
                record_error("document", unit, exc)
            else:
                unit.update(status="skipped", reason_code=exc.code, reason=str(exc))
                checkpoint()
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
            "planned_skipped_files": len(report.get("plan", {}).get("skipped", [])),
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
        if counts["needs_recovery"]:
            log_progress(f"恢复文件：{recovery_path.resolve()}")
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
                actor = await backend.operator(args.operator_id, args.tenant_id)
                backend.operator_id = int(actor.user_id)
                backend.use_operator_as_file_owner = args.use_operator_as_file_owner
            async with AsyncExitStack() as stack:
                async with phase("加载共享存储路由"):
                    await stack.enter_async_context(backend.shared_storage(args.tenant_id))
                for unit in report["units"]:
                    if unit.get("before") and unit["status"] not in {"succeeded", "restored"}:
                        await process_unit(unit, f"恢复文档 {unit['document_id']}", recover=True)
            return finish("recovered")
        async with phase("扫描全部个人知识库"):
            snapshot = await backend.load_snapshot(args.tenant_id)
        plan = build_plan(snapshot, args.tenant_id, args.folder_parts)
        report["plan"], report["status"] = plan, "planned"
        checkpoint()
        print(
            f"个人库 {len(plan['source_spaces'])} 个，候选文件 {plan['candidate_files']} 个，跳过 {len(plan['skipped'])} 个",
            flush=True,
        )
        if not args.apply:
            return 0
        async with phase("校验操作人身份和权限"):
            actor = await backend.operator(args.operator_id, args.tenant_id)
            backend.operator_id = int(actor.user_id)
            backend.use_operator_as_file_owner = args.use_operator_as_file_owner
        report["operator_id"] = args.operator_id
        async with AsyncExitStack() as stack:
            async with phase("加载共享存储路由"):
                await stack.enter_async_context(backend.shared_storage(args.tenant_id))
            for group in plan["groups"]:
                units = document_units(snapshot, group, plan)
                report["units"].extend(units)
                checkpoint()
                for index, unit in enumerate(units, start=1):
                    try:
                        async with phase(f"复核文档 {unit['document_id']} 的来源路径和组织路由"):
                            fresh_snapshot = await backend.load_snapshot(
                                args.tenant_id, file_ids={f["file_id"] for f in unit["files"]}
                            )
                        fresh = build_plan(fresh_snapshot, args.tenant_id, args.folder_parts)
                        current_files = sorted(
                            [f for g in fresh["groups"] for f in g["files"] if f["document_id"] == unit["document_id"]],
                            key=lambda f: f["file_id"],
                        )
                        if current_files != sorted(unit["files"], key=lambda f: f["file_id"]):
                            unit["recheck_skips"] = fresh["skipped"]
                            raise SkipFile("route_changed", "来源路径、上传人、版本链或组织路由已变化，请重新预览")
                        async with phase(f"检查或创建目标目录 {group['folder_name']}"):
                            group["folder_id"] = await backend.ensure_folder(
                                actor, group["target_space_id"], group["folder_parts"], group, checkpoint
                            )
                        unit["folder_id"] = group["folder_id"]
                        checkpoint()
                    except ReportWriteError:
                        raise
                    except SkipFile as exc:
                        unit.update(status="skipped", reason_code=exc.code, reason=str(exc))
                        checkpoint()
                        continue
                    except Exception as exc:
                        record_error("document", unit, exc)
                        continue
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
