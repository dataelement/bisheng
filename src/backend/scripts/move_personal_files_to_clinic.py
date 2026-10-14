#!/usr/bin/env python3
# ruff: noqa: RUF001, RUF002, RUF003
"""按上传人的主组织，将个人库文件原地迁入科室库，找不到时兜底部门库。

在 src/backend 下运行：
  .venv/bin/python scripts/move_personal_files_to_clinic.py --tenant-id 1 --folder-path 'A/B'
  .venv/bin/python scripts/move_personal_files_to_clinic.py --tenant-id 1 --folder-path 'A/B' --operator-id 1 --apply

省略 --folder-path 扫描个人库全部文件。完整路径匹配、包含子目录；普通模式保留原完整路径。
依次查找原始上传人科室库、当前上传人科室库；均失败再查原始上传人部门库、当前上传人部门库。
只从唯一主组织沿父级寻找最近 org_level=office 或 dept，不使用兼任组织。
默认只读预览；--apply 创建缺失目录、移动归属并同步权限和共享索引，不重新解析。
支持解析失败、等待、超时等静止文件，保留解析状态，不补建缺失分块。
加 --api-sync-only 仅选择接口同步文件，只取文件直接所在目录名；根目录文件迁入目标库根目录。
只支持共享存储；正式执行必须处于停止相关写入的维护窗口。
失败逐项记录，--recover-report 修复中断项，不撤销成功迁移。
目标库所有者失效时，可显式加 --use-operator-as-file-owner，使用操作人作为文件权限所有者。
加 --rename-conflicts 时，同名且 MD5 非空不同的主文件改名迁移；同内容仍跳过，不覆盖目标。
加 --overwrite-same-content 时，相同 MD5 的独立单版本目标进入回收站，源文件原地迁入。
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
from collections.abc import Iterable, Mapping
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager, suppress
from datetime import datetime, timedelta
from numbers import Integral, Real
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
    parser.add_argument("--api-sync-only", action="store_true", help="仅迁移接口同步文件，目标仅保留文件直接所在目录名")
    parser.add_argument(
        "--rename-conflicts", action="store_true", help="同名但 MD5 非空不同的文件改名迁移，同内容或缺少 MD5 仍跳过"
    )
    parser.add_argument(
        "--overwrite-same-content",
        action="store_true",
        help="仅覆盖同目录 MD5 相同的独立单版本文件：旧目标进入回收站，源文件原地迁入；不永久删除",
    )
    parser.add_argument(
        "--allow-failed-projection",
        action="store_true",
        help="显式允许仅有管理入口、解析成功但共享投影失败的静止文件迁移，保留失败状态",
    )
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


def validate_parse_state(row: Any) -> None:
    if row.status in {1, 4}:
        label = "正在解析" if row.status == 1 else "正在重建"
        raise SkipFile("parsing_busy", f"文件{label}（status={row.status}），待任务结束后再迁移")
    if row.status not in {None, 2, 3, 5, 6, 7}:
        raise SkipFile("unknown_parse_status", f"未知解析状态（status={row.status}）")


def allows_failed_projection(unit: dict[str, Any], manager: Any, entries: list[Any]) -> bool:
    # 单独管理入口的静止失败可以迁移归属，不放宽已有发布/共享图谱的完整性要求。
    return bool(
        unit.get("allow_failed_projection")
        and manager.status == 2
        and manager.projection_status == "failed"
        and len(entries) == 1
        and entries[0].id == manager.id
    )


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
        department_spaces = {
            int(row.space_id): int(row.owner_id)
            for row in snapshot["scopes"]
            if row.level == "department" and row.owner_type == "department" and row.space_id in self.spaces
        }
        self.department_targets: dict[int, set[int]] = defaultdict(set)
        for row in snapshot["bindings"]:
            if row.space_id in clinics:
                self.targets[int(row.department_id)].add(int(row.space_id))
            if department_spaces.get(int(row.space_id)) == int(row.department_id):
                self.department_targets[int(row.department_id)].add(int(row.space_id))

    def resolve(self, file: Any) -> dict[str, Any]:
        candidates: list[tuple[int, str]] = []
        for uploader, origin in ((file.original_uploader_id, "original_uploader_id"), (file.user_id, "user_id")):
            if uploader and all(int(uploader) != previous[0] for previous in candidates):
                candidates.append((int(uploader), origin))
        if not candidates:
            raise SkipFile("missing_uploader", "原始上传人和当前上传人均缺失")
        failures: dict[tuple[int, str, str], tuple[SkipFile, str]] = {}
        for department_fallback in (False, True):
            label = "部门库" if department_fallback else "科室库"
            for uploader, origin in candidates:
                try:
                    return self._resolve_uploader(uploader, origin, department_fallback=department_fallback)
                except SkipFile as exc:
                    # 用户或组织的同一失败不因尝试不同库类型而重复记录。
                    key = (uploader, exc.code, str(exc))
                    user_label = "原始上传人" if origin == "original_uploader_id" else "当前上传人"
                    failures.setdefault(key, (exc, f"{user_label}{label}匹配失败：{exc}"))
        first_error = next(iter(failures.values()))[0]
        reason = str(first_error) if len(failures) == 1 else "；".join(message for _, message in failures.values())
        raise SkipFile(first_error.code, reason) from first_error

    def _resolve_uploader(self, uploader: int, origin: str, *, department_fallback: bool = False) -> dict[str, Any]:
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
            if department.org_level == ("dept" if department_fallback else "office"):
                target_map = self.department_targets if department_fallback else self.targets
                targets = sorted(target_map.get(department_id, set()))
                if not targets:
                    if department_fallback:
                        raise SkipFile("missing_department_space", "最近部门未绑定有效部门库")
                    raise SkipFile("missing_clinic", "最近科室未绑定有效科室库")
                return {
                    "uploader_id": int(uploader),
                    "uploader_source": origin,
                    "primary_department_id": departments[0],
                    "office_id": None if department_fallback else department_id,
                    "target_space_id": targets[0],
                    **({"department_id": department_id} if department_fallback else {}),
                }
            department_id = department.parent_id
        if department_fallback:
            raise SkipFile("missing_department_label", "主组织及其父级没有部门标签")
        raise SkipFile("missing_office", "主组织及其父级没有科室标签")


def is_api_sync_file(row: Any) -> bool:
    """与页面和现有维护脚本的“接口同步”来源判定保持一致。"""
    metadata = getattr(row, "user_metadata", None)
    return isinstance(metadata, dict) and bool(
        metadata.get("filelib_sync_endpoint") or metadata.get("external_file_id")
    )


def build_plan(
    snapshot: dict[str, Any], tenant_id: int, requested: tuple[str, ...] = (), *, api_sync_only: bool = False
) -> dict[str, Any]:
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
        if api_sync_only and not is_api_sync_file(row):
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
            destination_parts = parts[-1:] if api_sync_only else parts
            if api_sync_only:
                entry["target_folder_parts"] = list(destination_parts)
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
            validate_parse_state(row)
            entry.update(routing.resolve(row))
            unversioned = (
                not documents[row.id]
                and row.status != 2
                and not getattr(row, "reference_document_id", None)
                and row.entry_type in {None, ""}
            )
            if len(documents[row.id]) != 1 and not unversioned:
                raise SkipFile("invalid_version_chain", "缺少唯一规范文档版本链")
            # 负值仅作报告内的单元键，不创建虚构的数据库文档。
            entry["document_id"] = -int(row.id) if unversioned else next(iter(documents[row.id]))
            if unversioned:
                entry["unversioned"] = True
            parent_path, missing = "", False
            for name in destination_parts:
                matches = by_location.get((entry["target_space_id"], parent_path, name), []) if not missing else []
                if len(matches) > 1 or (matches and matches[0].file_type != 0):
                    raise SkipFile("target_folder_conflict", "目标路径存在重名目录或同名文件")
                if matches:
                    folder = matches[0]
                    if folder_parts_for(folder, by_id) != destination_parts[: folder.level]:
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
                tuple(selected[i].get("target_folder_parts", selected[i]["folder_parts"])),
                selected[i]["space_id"],
                selected[i]["source_path"],
            )
            for i in present
        }
        if present and (not ids <= selected.keys() or len(routes) != 1):
            reason = (
                "版本链包含非接口同步文件，整条版本链未迁移"
                if api_sync_only and any(i in by_id and not is_api_sync_file(by_id[i]) for i in ids)
                else "版本链不完整、跨来源范围或迁移目标不一致"
            )
            for file_id in sorted(present):
                skipped.append(
                    {
                        **selected.pop(file_id),
                        "reason_code": "incomplete_version_chain",
                        "reason": reason,
                    }
                )
    groups: dict[tuple, dict[str, Any]] = {}
    for entry in selected.values():
        key = entry["target_space_id"], tuple(entry.get("target_folder_parts", entry["folder_parts"]))
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
        "api_sync_only": api_sync_only,
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


def persisted_datetime_matches(actual: str | None, recorded: str | None) -> bool:
    """仅兼容旧报告的微秒被数据库截断或舍入为整秒，其他变化仍拒绝。"""
    if actual == recorded:
        return True
    if not actual or not recorded:
        return False
    current, expected = datetime.fromisoformat(actual), datetime.fromisoformat(recorded)
    floor = expected.replace(microsecond=0)
    rounded = floor + timedelta(seconds=int(expected.microsecond >= 500_000))
    return current.microsecond == 0 and expected.microsecond != 0 and current in {floor, rounded}


def overwrite_identity_matches(
    record: dict[str, Any], document: Any, versions: list[Any], file: Any, entries: list[Any], *, in_target: bool
) -> bool:
    expected = record["after_identity"] if in_target else record["before_identity"]
    if identity_fingerprint(document or file, versions, [file], entries) == expected:
        return True
    if not in_target:
        return False
    recorded = record["recycle_item"]["deleted_at"]
    actual = file.model_dump(mode="json")["deleted_at"]
    if not persisted_datetime_matches(actual, recorded):
        return False
    # 不放宽指纹字段：还原报告中的时间精度后，完整身份仍必须匹配。
    shadow = file.model_copy(update={"deleted_at": datetime.fromisoformat(recorded)})
    shadow_entries = [shadow if entry.id == file.id else entry for entry in entries]
    if identity_fingerprint(document or shadow, versions, [shadow], shadow_entries) == expected:
        return True
    before = record["before_file"]
    if (
        before.get("entry_type") == "manager"
        and file.entry_status == "invalid"
        and document is not None
        and document.lifecycle_status == "recycled"
        and file.projection_status == "ready"
        and file.projection_lease_owner is None
        and file.projection_lease_until is None
        and file.desired_entry_generation == int(before["desired_entry_generation"]) + 1
        and file.applied_entry_generation == file.desired_entry_generation
        and file.applied_content_generation == file.desired_content_generation
    ):
        # 同一回收代次的后台清理完成可与迁移并行；仅归一化 pending -> ready。
        shadow.projection_status = "pending"
        return identity_fingerprint(document, versions, [shadow], shadow_entries) == expected
    return False


def recovery_identity_fingerprint(
    unit: dict[str, Any], document: Any, versions: list[Any], files: list[Any], entries: list[Any]
) -> str:
    # 相似候选清理可把提示位从 1 清为 0；仅还原该位用于旧报告身份核对。
    before_files = {row["id"]: row for row in unit.get("before", {}).get("files", [])}

    def normalize_similarity(row: Any) -> Any:
        if before_files.get(row.id, {}).get("similar_status") == 1 and row.similar_status == 0:
            return row.model_copy(update={"similar_status": 1})
        return row

    file_ids = {file.id for file in files}
    files = [normalize_similarity(file) for file in files]
    entries = [normalize_similarity(entry) if entry.id in file_ids else entry for entry in entries]
    if document.id in file_ids and "similar_status" in type(document).model_fields:
        document = normalize_similarity(document)
    rename = unit.get("rename")
    if not rename:
        return identity_fingerprint(document, versions, files, entries)
    file = next((f for f in files if f.id == rename["file_id"]), None)
    before = next((f for f in unit["before"]["files"] if f["id"] == rename["file_id"]), None)
    if file is None or before is None or before["file_name"] != rename["old_name"]:
        raise ValueError("改名文件与恢复报告不一致")
    expected_name = rename["new_name"] if file.knowledge_id == unit["target_space_id"] else rename["old_name"]
    if file.file_name != expected_name:
        raise ValueError("文件名发生本次迁移之外的变化，拒绝恢复")

    # 仅还原报告记录且已逐项核对的改名，其他文件名和内容仍参与完整指纹校验。
    def original_name(row):
        return row.model_copy(update={"file_name": rename["old_name"]}) if row.id == file.id else row

    return identity_fingerprint(
        original_name(document) if unit.get("unversioned") else document,
        versions,
        [original_name(f) for f in files],
        [original_name(e) for e in entries],
    )


def migration_filename(file_name: str, file_id: int, attempt: int = 1) -> str:
    suffix = Path(file_name).suffix
    stem = file_name[: -len(suffix)] if suffix else file_name
    marker = f"_迁移_{file_id}" + (f"_{attempt}" if attempt > 1 else "")
    available = 200 - len(marker) - len(suffix)
    if available < 1:
        raise SkipFile("target_file_conflict", "文件扩展名过长，无法生成安全的迁移文件名")
    return f"{stem[:available]}{marker}{suffix}"


def plain_index_value(value: Any) -> Any:
    """把 SDK 的数组和数字转换成可落盘的数据, 不丢弃未知字段。"""
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        return float(value)
    if isinstance(value, Mapping):
        return {str(key): plain_index_value(item) for key, item in value.items()}
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        return [plain_index_value(item) for item in value]
    raise TypeError(f"恢复报告不支持索引字段类型：{type(value).__name__}")


def validate_overwrite_subset(before: list[dict[str, Any]], current: list[dict[str, Any]]) -> None:
    def payload(row):
        values = {key: value for key, value in row.items() if not key.startswith("_") and key != "pk"}
        # 恢复报告会把稀疏向量的整数键转为字符串, 用相同 JSON 形态比较。
        return plain_index_value(values)

    original = {int(row["chunk_index"]): payload(row) for row in before}
    if any(payload(row) != original.get(int(row["chunk_index"])) for row in current):
        raise ValueError("被覆盖目标的共享内容或元数据已变化，拒绝清理或恢复")


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
        len(primary) != 1
        or primary[0].id != document.primary_version_id
        or primary[0].knowledge_file_id not in {f.id for f in files}
    ):
        raise SkipFile("invalid_primary_version", "规范文档缺少唯一有效主版本或主版本文件")
    primary_file = next(f for f in files if f.id == primary[0].knowledge_file_id)
    if managers:
        if len(managers) != 1 or managers[0].id != primary_file.id:
            raise SkipFile("invalid_primary_version", "规范文档管理入口与主版本文件不一致")
        anchor = managers[0]
    else:
        # 只接纳尚未激活入口的未解析原始版本，不把失效入口当成普通文件迁移。
        if any(
            f.status == 2
            or f.entry_type not in {None, ""}
            or f.entry_status not in {None, ""}
            or f.reference_document_id not in {None, document.id}
            for f in files
        ) or any(e.id not in {f.id for f in files} for e in entries):
            raise SkipFile("missing_manager", "缺少管理入口，且存在已解析版本或异常文档入口/引用")
        anchor = primary_file
    for entry in entries:
        if not managers:
            continue
        incomplete = (managers[0].status != 2 and entry.status != 2) or allows_failed_projection(
            unit, managers[0], entries
        )
        if (
            entry.entry_status != "active"
            or entry.deleted_at is not None
            or entry.projection_status not in ({None, "pending", "failed", "ready"} if incomplete else {"ready"})
            or entry.projection_lease_owner
            or entry.projection_lease_until
            or entry.desired_content_generation != document.content_generation
            or (not incomplete and entry.applied_content_generation != document.content_generation)
            or (not incomplete and entry.applied_entry_generation != entry.desired_entry_generation)
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
        document.knowledge_id != anchor.knowledge_id
        or (document.file_level_path or "") != (anchor.file_level_path or "")
        or document.level != anchor.level
    ):
        raise SkipFile("document_location_mismatch", "文档和主版本文件归属不一致")
    if any(f.deleted_at is not None or f.file_type != 1 for f in files):
        raise SkipFile("file_not_ready", "版本文件已删除或类型异常")
    for file in [*files, *entries]:
        validate_parse_state(file)
        if file.projection_lease_owner or file.projection_lease_until or file.projection_status == "processing":
            raise SkipFile("projection_busy", "版本文件存在执行中的投影任务")
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
    observed: dict[str, list[dict[str, Any]]],
    unit: dict[str, Any],
    document: Any,
    primary: Any,
    model_id: str,
    *,
    allow_incomplete: bool = False,
) -> dict[str, str]:
    fingerprints = {}
    texts = {}
    for side, rows in observed.items():
        if not rows and not allow_incomplete:
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
    if not allow_incomplete and texts["es"] != texts["milvus"]:
        raise ValueError("ES 与 Milvus 分块不完整或内容不一致")
    if any(texts["es"][i] != texts["milvus"][i] for i in texts["es"].keys() & texts["milvus"].keys()):
        raise ValueError("ES 与 Milvus 已有分块内容不一致")
    return fingerprints


def validate_unversioned(unit: dict[str, Any], files: list[Any], folder: Any, spaces: list[Any]) -> None:
    if len(files) != 1 or len(unit["files"]) != 1:
        raise SkipFile("source_changed", "原始文件不存在或迁移单元异常")
    file, expected = files[0], unit["files"][0]
    if any(int(row.tenant_id or 1) != unit["tenant_id"] for row in [*files, *spaces, *([folder] if folder else [])]):
        raise SkipFile("tenant_mismatch", "文件、目录或知识库不属于指定租户")
    validate_parse_state(file)
    if (
        file.status == 2
        or file.deleted_at is not None
        or file.file_type != 1
        or file.reference_document_id
        or file.entry_type
        or file.entry_status
    ):
        raise SkipFile("source_changed", "原始文件已解析成功、删除或已建立文档入口，请重新预览")
    if file.projection_lease_owner or file.projection_lease_until or file.projection_status == "processing":
        raise SkipFile("projection_busy", "原始文件存在执行中的投影任务")
    if unit["folder_parts"]:
        if (
            folder is None
            or folder.deleted_at is not None
            or folder.file_type != 0
            or folder.knowledge_id != unit["target_space_id"]
            or folder.level != len(unit["folder_parts"]) - 1
        ):
            raise SkipFile("target_folder_changed", "目标目录已变化")
    elif folder is not None:
        raise SkipFile("target_folder_changed", "预期目标为根目录")
    source = (
        file.knowledge_id == expected["space_id"]
        and (file.file_level_path or "") == expected["source_path"]
        and file.level == expected["source_level"]
    )
    target = (
        file.knowledge_id == unit["target_space_id"]
        and (file.file_level_path or "") == target_path(folder)
        and file.level == len(unit["folder_parts"])
    )
    if not source and not (unit.get("before") and target):
        raise SkipFile("source_changed", "原始文件归属或目录已变化")
    old = unit["before"]["files"][0] if unit.get("before") else expected
    uploader = (old["original_uploader_id"] or old["user_id"]) if target else old["original_uploader_id"]
    if file.user_id != old["user_id"] or file.original_uploader_id != uploader:
        raise SkipFile("uploader_changed", "上传人已变化")
    if unit.get("before"):
        origin = (old["original_knowledge_id"] or old["knowledge_id"]) if target else old["original_knowledge_id"]
        if file.original_knowledge_id != origin:
            raise SkipFile("original_space_changed", "原始知识库已变化，拒绝恢复")


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
                int(uploader) for f in selected_files for uploader in (f.original_uploader_id, f.user_id) if uploader
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
        from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
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
                raise ValueError("目标知识库不可用")
            scopes = list(
                (await session.exec(select(KnowledgeSpaceScope).where(KnowledgeSpaceScope.space_id == target.id))).all()
            )
            if len(scopes) != 1:
                raise ValueError("目标知识库范围已变化")
            scope = scopes[0]
            department_ids = {entry.get("department_id") for entry in unit["files"]}
            if department_ids == {None}:
                if scope.level not in {"team", "team_ks"} or scope.owner_type != "user":
                    raise ValueError("目标科室库范围已变化")
            else:
                if (
                    len(department_ids) != 1
                    or None in department_ids
                    or scope.level != "department"
                    or scope.owner_type != "department"
                    or scope.owner_id not in department_ids
                ):
                    raise ValueError("目标部门库范围已变化")
                bindings = await rows(DepartmentKnowledgeSpace, DepartmentKnowledgeSpace.space_id == target.id)
                if len(bindings) != 1 or bindings[0].department_id != scope.owner_id:
                    raise ValueError("目标部门库绑定已变化")
            owner = await self.resolve_file_owner(session, target, unit)
            document = None
            if unit.get("unversioned"):
                ids = [f["file_id"] for f in unit["files"]]
                versions = await rows(
                    KnowledgeDocumentVersion, col(KnowledgeDocumentVersion.knowledge_file_id).in_(ids)
                )
                if versions:
                    raise ValueError("原始文件已生成版本链，请重新预览")
                entries = []
            else:
                documents = await rows(KnowledgeDocument, KnowledgeDocument.id == unit["document_id"])
                if len(documents) != 1:
                    raise ValueError("文档不存在")
                document = documents[0]
                versions = await rows(KnowledgeDocumentVersion, KnowledgeDocumentVersion.document_id == document.id)
                ids = sorted(int(v.knowledge_file_id) for v in versions)
                if ids != sorted(f["file_id"] for f in unit["files"]):
                    raise ValueError("版本链发生变化或不完整")
                entries = await rows(KnowledgeFile, KnowledgeFile.reference_document_id == document.id)
            files = await rows(KnowledgeFile, col(KnowledgeFile.id).in_(ids))
            folders = await rows(KnowledgeFile, KnowledgeFile.id == unit["folder_id"]) if unit["folder_id"] else []
            folder = folders[0] if len(folders) == 1 else None
            if unit.get("unversioned"):
                validate_unversioned(unit, files, folder, spaces)
            else:
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
            protected = set(ids) | ({document.id} if document else set())
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
        expected = {f["file_id"]: f for f in unit["files"]}
        for file in files:
            if unit.get("api_sync_only") and not is_api_sync_file(file):
                raise SkipFile("api_sync_source_changed", "文件已不再标记为接口同步来源，请重新预览")
            # 来源完整路径与目标目录各自校验；旧报告沿用已记录的目标，不重新选目录。
            parts = (
                unit["folder_parts"]
                if unit.get("before") and file.knowledge_id == unit["target_space_id"]
                else expected[file.id].get("folder_parts", unit["folder_parts"])
            )
            if folder_parts_for(file, by_id) != tuple(parts):
                raise SkipFile("source_changed", "来源完整目录路径已变化")
        # 恢复以报告和数据库已提交状态为准，不根据新的组织关系重新选目标。
        if unit.get("before"):
            return
        user_ids = {int(uploader) for f in files for uploader in (f.original_uploader_id, f.user_id) if uploader}
        snapshot = await self.routing_snapshot(session, user_ids)
        routing = Routing(snapshot)
        personal = {
            s.space_id
            for s in snapshot["scopes"]
            if s.level == "personal" and s.owner_type == "user" and s.space_id in routing.spaces
        }
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

    async def prepare_conflict_rename(
        self, session: Any, unit: dict[str, Any], file: Any, files: list[Any], folder: Any
    ) -> None:
        from sqlmodel import col, func, or_, select

        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

        destination = select(KnowledgeFile).where(
            KnowledgeFile.knowledge_id == unit["target_space_id"],
            KnowledgeFile.file_level_path == target_path(folder)
            if folder
            else or_(KnowledgeFile.file_level_path == "", KnowledgeFile.file_level_path.is_(None)),
            KnowledgeFile.deleted_at.is_(None),
            col(KnowledgeFile.id).notin_([f.id for f in files]),
        )
        md5 = normalize(file.md5).lower()
        conflicts = list(
            (
                await session.exec(
                    destination.where(
                        or_(
                            KnowledgeFile.file_name == file.file_name,
                            func.lower(KnowledgeFile.md5) == md5 if md5 else False,
                        )
                    ).with_for_update()
                )
            ).all()
        )
        if not conflicts:
            return
        unit["conflict_ids"] = [f.id for f in conflicts]
        same = [f for f in conflicts if md5 and normalize(f.md5).lower() == md5]
        if same and unit.get("overwrite_same_content"):
            if len(same) != 1:
                raise SkipFile("overwrite_target_ambiguous", "同内容目标不唯一，不能自动覆盖")
            unit["overwrite_ids"] = [f.id for f in same]
            conflicts = [f for f in conflicts if f.id not in unit["overwrite_ids"]]
            if not conflicts:
                return
        if (
            not unit.get("rename_conflicts")
            or not md5
            or any(not normalize(f.md5) or normalize(f.md5).lower() == md5 for f in conflicts)
        ):
            raise SkipFile("target_file_conflict", "目标目录存在同名或相同内容文件；未开启改名、内容相同或缺少 MD5")
        for attempt in range(1, 101):
            name = migration_filename(file.file_name, file.id, attempt)
            if (
                await session.exec(
                    destination.where(
                        KnowledgeFile.file_name == name,
                        col(KnowledgeFile.id).notin_(unit.get("overwrite_ids", [])),
                    )
                )
            ).first() is None:
                unit["rename"] = {"file_id": file.id, "old_name": file.file_name, "new_name": name}
                return
        raise SkipFile("target_file_conflict", "迁移改名连续 100 个候选名称被占用，暂缓处理")

    async def overwrite_graph(self, session: Any, file_id: int):
        from sqlmodel import select

        from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
        from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile

        file = (await session.exec(select(KnowledgeFile).where(KnowledgeFile.id == file_id).with_for_update())).one()
        links = list(
            (
                await session.exec(
                    select(KnowledgeDocumentVersion)
                    .where(
                        KnowledgeDocumentVersion.knowledge_file_id == file_id,
                    )
                    .with_for_update()
                )
            ).all()
        )
        if len(links) > 1:
            raise SkipFile("overwrite_target_invalid", "覆盖目标属于多个版本链")
        document, versions, entries = None, [], []
        if links:
            document = (
                await session.exec(
                    select(KnowledgeDocument)
                    .where(
                        KnowledgeDocument.id == links[0].document_id,
                    )
                    .with_for_update()
                )
            ).one()
            versions = list(
                (
                    await session.exec(
                        select(KnowledgeDocumentVersion)
                        .where(
                            KnowledgeDocumentVersion.document_id == document.id,
                        )
                        .order_by(KnowledgeDocumentVersion.id)
                        .with_for_update()
                    )
                ).all()
            )
            entries = list(
                (
                    await session.exec(
                        select(KnowledgeFile)
                        .where(
                            KnowledgeFile.reference_document_id == document.id,
                        )
                        .order_by(KnowledgeFile.id)
                        .with_for_update()
                    )
                ).all()
            )
        return file, document, versions, entries

    async def prepare_overwrites(self, session: Any, unit: dict[str, Any], *, recover: bool, in_target: bool):
        from sqlmodel import col, or_, select

        from bisheng.approval.domain.models.approval_instance import ApprovalInstance
        from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
        from bisheng.knowledge.domain.models.knowledge_recycle_item import KnowledgeRecycleItem

        graphs = []
        records = unit.get("overwrites", []) if recover else [{"file_id": fid} for fid in unit.get("overwrite_ids", [])]
        for record in records:
            file, document, versions, entries = await self.overwrite_graph(session, record["file_id"])
            identity = identity_fingerprint(document or file, versions, [file], entries)
            items = list(
                (
                    await session.exec(
                        select(KnowledgeRecycleItem)
                        .where(
                            KnowledgeRecycleItem.file_id == file.id,
                        )
                        .with_for_update()
                    )
                ).all()
            )
            if recover:
                if not overwrite_identity_matches(record, document, versions, file, entries, in_target=in_target):
                    raise ValueError("被覆盖目标的内容、版本或回收状态已变化，拒绝恢复")
                if (in_target and (len(items) != 1 or items[0].id != record.get("recycle_item_id"))) or (
                    not in_target and items
                ):
                    raise ValueError("被覆盖目标的回收条目已变化，拒绝恢复")
                if in_target:
                    actual = items[0].model_dump(mode="json", exclude={"update_time"})
                    expected = {key: value for key, value in record["recycle_item"].items() if key != "update_time"}
                    # 旧版 flush 未读回服务端默认 create_time, 报告可能缺少该字段。
                    if "create_time" not in expected:
                        actual.pop("create_time", None)
                    for key in ("deleted_at", "expire_at"):
                        if persisted_datetime_matches(actual.get(key), expected.get(key)):
                            actual[key] = expected[key]
                    if actual != expected:
                        raise ValueError("被覆盖目标的回收快照已变化，拒绝恢复")
            else:
                validate_parse_state(file)
                if (
                    file.id in {f["file_id"] for f in unit["files"]}
                    or file.file_type != 1
                    or file.deleted_at is not None
                    or int(file.tenant_id or 1) != unit["tenant_id"]
                    or file.knowledge_id != unit["target_space_id"]
                    or file.predecessor_logic_file_id
                    or file.share_source_file_id
                    or file.entry_type not in {None, "", "manager"}
                    or file.entry_status not in {None, "", "active"}
                    or ((file.entry_type == "manager") != (file.entry_status == "active"))
                    or file.projection_lease_owner
                    or file.projection_lease_until
                    or file.projection_status == "processing"
                    or any(e.id != file.id for e in entries)
                    or items
                ):
                    raise SkipFile("overwrite_target_protected", "覆盖目标有发布、共享、引用或执行中的任务，暂缓覆盖")
                if document:
                    if (
                        document.id == unit["document_id"]
                        or document.lifecycle_status != "active"
                        or document.predecessor_logic_file_id
                        or document.tenant_id != unit["tenant_id"]
                        or document.knowledge_id != file.knowledge_id
                        or (document.file_level_path or "") != (file.file_level_path or "")
                        or document.level != file.level
                        or len(versions) != 1
                        or not versions[0].is_primary
                        or document.primary_version_id != versions[0].id
                        or versions[0].knowledge_file_id != file.id
                        or file.reference_document_id not in {None, document.id}
                        or (file.entry_type == "manager" and (not entries or file.reference_document_id != document.id))
                        or (file.status == 2 and file.entry_type != "manager")
                    ):
                        raise SkipFile("overwrite_target_protected", "覆盖目标不是独立完整的单版本文档")
                    if file.entry_type == "manager":
                        incomplete_projection = file.status != 2 or allows_failed_projection(unit, file, entries)
                        if (
                            file.desired_content_generation != document.content_generation
                            or file.projection_status
                            not in ({None, "pending", "failed", "ready"} if incomplete_projection else {"ready"})
                            or (
                                not incomplete_projection
                                and file.applied_content_generation != document.content_generation
                            )
                            or (
                                not incomplete_projection
                                and file.applied_entry_generation != file.desired_entry_generation
                            )
                        ):
                            raise SkipFile("overwrite_target_protected", "覆盖目标的投影状态或代次不一致")
                elif file.reference_document_id or file.entry_type or file.entry_status or file.status == 2:
                    raise SkipFile("overwrite_target_protected", "无版本链覆盖目标已解析或存在文档入口")
                references = (
                    await session.exec(
                        select(KnowledgeFile.id).where(
                            or_(
                                KnowledgeFile.predecessor_logic_file_id == file.id,
                                KnowledgeFile.share_source_file_id == file.id,
                            )
                        )
                    )
                ).first()
                predecessors = (
                    await session.exec(
                        select(KnowledgeDocument.id).where(
                            KnowledgeDocument.predecessor_logic_file_id == file.id,
                        )
                    )
                ).first()
                if references is not None or predecessors is not None:
                    raise SkipFile("overwrite_target_protected", "覆盖目标被其他文档或文件作为前序引用")
                approvals = (
                    await session.exec(
                        select(ApprovalInstance).where(
                            col(ApprovalInstance.status).in_(["pending", "exception", "execute_failed"]),
                        )
                    )
                ).all()
                protected = {str(file.id)} | ({str(document.id)} if document else set())
                if any(
                    str(a.business_resource_id or "").split(":", 1)[0] in protected
                    and ("file" in a.business_resource_type or "file" in a.scenario_code)
                    for a in approvals
                ):
                    raise SkipFile("overwrite_target_protected", "覆盖目标存在未结束的审批")
                record.update(
                    before_identity=identity,
                    before_document=document.model_dump(mode="json") if document else None,
                    before_file=file.model_dump(mode="json"),
                )
            if document:
                observed = {
                    side: plain_index_value((await self.store.read(side, [document.id])).get(document.id, []))
                    for side in ("es", "milvus")
                }
                if file.entry_type != "manager" and any(observed.values()):
                    raise SkipFile("overwrite_target_protected", "覆盖目标缺少管理入口但有共享内容")
                incomplete = (
                    file.status != 2 or file.entry_type != "manager" or allows_failed_projection(unit, file, entries)
                )
                fingerprints = validate_chunks(
                    observed,
                    unit,
                    document,
                    versions[0],
                    self.store.embedding_model_id,
                    allow_incomplete=True if recover else incomplete,
                )
                if recover:
                    for side, rows in observed.items():
                        validate_overwrite_subset(record["rows"][side], rows)
                if not recover:
                    active_ids = tuple(sorted({e.knowledge_id for e in entries if e.entry_status == "active"}))
                    if any(
                        tuple(sorted(set(r.get("knowledge_ids", [])))) != active_ids
                        for rows in observed.values()
                        for r in rows
                    ):
                        raise SkipFile("overwrite_target_index_drift", "被覆盖目标索引归属与有效入口不一致，暂缓覆盖")
                    # 回收最后一个入口需要清理投影; 写前保留原分块和向量, 回滚时只恢复缺失行。
                    record.update(
                        chunks=fingerprints,
                        before_knowledge_ids=list(active_ids),
                        rows=observed,
                        allow_incomplete=incomplete,
                    )
            else:
                observed = {}
            graphs.append((record, file, document, versions, entries, observed))
        if not recover:
            unit["overwrites"] = records
        return graphs

    async def recycle_overwrites(self, session: Any, unit: dict[str, Any], graphs: list[Any], checkpoint: Any):
        from bisheng.knowledge.domain.models.knowledge_recycle_item import KnowledgeRecycleItem
        from bisheng.knowledge.domain.repositories.implementations.knowledge_document_recycle_repository_impl import (
            KnowledgeDocumentRecycleRepositoryImpl,
        )

        if graphs and self.operator_id is None:
            raise ValueError("尚未校验覆盖操作人")
        repository = KnowledgeDocumentRecycleRepositoryImpl(session)
        for record, file, document, versions, entries, _observed in graphs:
            days, spaces, scopes, folders = await repository.snapshot_context([file])
            now = datetime.now().replace(microsecond=0)
            parts = [int(part) for part in (file.file_level_path or "").split("/") if part]
            item = KnowledgeRecycleItem(
                tenant_id=unit["tenant_id"],
                file_id=file.id,
                knowledge_id=file.knowledge_id,
                file_type=1,
                is_list_entry=True,
                display_name=file.file_name,
                file_encoding=file.file_encoding,
                file_subcategory_code=file.file_subcategory_code,
                file_size=file.file_size,
                md5=file.md5,
                space_level=scopes.get(file.knowledge_id),
                original_knowledge_id=file.knowledge_id,
                original_parent_id=parts[-1] if parts else None,
                original_path="/"
                + "/".join(
                    [spaces[file.knowledge_id].name, *[folders[pid].file_name for pid in parts], file.file_name]
                ),
                original_file_level_path=file.file_level_path or "",
                original_path_fingerprint=hashlib.sha256((file.file_level_path or "").encode()).hexdigest()[:32],
                deleted_by=self.operator_id,
                deleted_by_name="migration",
                deleted_at=now,
                expire_at=now + timedelta(days=days),
                recycle_batch_id=uuid4().hex,
                recycle_root_id=file.id,
                document_id=document.id if document else None,
                version_file_ids=[file.id] if document else None,
            )
            session.add(item)
            file.deleted_at = now
            if file.entry_type == "manager":
                file.entry_status = "invalid"
                file.desired_entry_generation += 1
                file.projection_status = "pending"
            session.add(file)
            if document:
                document.lifecycle_status = "recycled"
                session.add(document)
            await session.flush()
            # 快照使用持久化后的字段，避免数据库精度或默认值造成写后误报。
            await session.refresh(file)
            await session.refresh(item)
            if document:
                await session.refresh(document)
            record["recycle_item_id"] = item.id
            record["recycle_item"] = item.model_dump(mode="json")
            record["after_identity"] = identity_fingerprint(document or file, versions, [file], entries)
        checkpoint()

    async def sync_overwrites(self, unit: dict[str, Any], graphs: list[Any], *, in_target: bool):
        for record, _file, document, versions, _entries, _observed in graphs:
            if document is None:
                continue
            current = {
                side: plain_index_value((await self.store.read(side, [document.id])).get(document.id, []))
                for side in ("es", "milvus")
            }
            incomplete = record["allow_incomplete"]
            validate_chunks(current, unit, document, versions[0], self.store.embedding_model_id, allow_incomplete=True)
            for side, rows in current.items():
                validate_overwrite_subset(record["rows"][side], rows)
                await self.update_overwrite_content(side, record["rows"][side], rows, remove=in_target)
            for attempt in range(3):
                actual = {
                    side: plain_index_value((await self.store.read(side, [document.id])).get(document.id, []))
                    for side in ("es", "milvus")
                }
                for side, rows in actual.items():
                    validate_overwrite_subset(record["rows"][side], rows)
                confirmed = (
                    not any(actual.values())
                    if in_target
                    else validate_chunks(
                        actual, unit, document, versions[0], self.store.embedding_model_id, allow_incomplete=True
                    )
                    == record["chunks"]
                )
                if confirmed or attempt == 2:
                    break
                action = "删除" if in_target else "恢复"
                log_progress(f"被覆盖文档 {document.id} 的索引{action}尚未读回确认，第 {attempt + 1}/2 次等待后复核")
                await asyncio.sleep(attempt + 1)
            if in_target and any(actual.values()):
                counts = {side: len(rows) for side, rows in actual.items()}
                raise RuntimeError(f"被覆盖目标的索引写后校验失败：文档 {document.id}，残留 {counts}")
            if not in_target:
                if not confirmed:
                    raise RuntimeError("被覆盖目标的分块恢复读回校验失败")
                for side, rows in actual.items():
                    validate_overwrite_subset(record["rows"][side], rows)
                if (
                    validate_chunks(
                        actual, unit, document, versions[0], self.store.embedding_model_id, allow_incomplete=incomplete
                    )
                    != record["chunks"]
                ):
                    raise RuntimeError("被覆盖目标的分块恢复读回校验失败")

    async def update_overwrite_content(self, side: str, before: list[Any], current: list[Any], *, remove: bool):
        present = {int(row["chunk_index"]) for row in current}
        missing = [row for row in before if int(row["chunk_index"]) not in present]
        if not (current if remove else missing):
            return
        await self.store._check()
        if side == "es":
            client = await self.store._es()
            for row in current if remove else missing:
                await self.store._check()
                options = {"index": self.store.snapshot.index_name, "id": row["_id"], "refresh": "wait_for"}
                if row.get("_routing") is not None:
                    options["routing"] = row["_routing"]
                if remove:
                    await asyncio.to_thread(
                        client.delete, **options, if_seq_no=row["_seq_no"], if_primary_term=row["_primary_term"]
                    )
                else:
                    source = {
                        "text": row["text"],
                        "metadata": {
                            key: value for key, value in row.items() if key != "text" and not key.startswith("_")
                        },
                    }
                    await asyncio.to_thread(client.index, **options, document=source, op_type="create")
        else:
            writer = await self.store._writer()
            rows = current if remove else missing
            for offset in range(0, len(rows), 500):
                await self.store._check()
                batch = rows[offset : offset + 500]
                if remove:
                    await asyncio.to_thread(
                        writer.collection.delete, expr=f"pk in {[int(row['pk']) for row in batch]}", timeout=30
                    )
                else:
                    values = [{key: value for key, value in row.items() if key != "pk"} for row in batch]
                    for value in values:
                        if isinstance(value.get("sparse_vector"), dict):
                            value["sparse_vector"] = {
                                int(key): weight for key, weight in value["sparse_vector"].items()
                            }
                    result = await asyncio.to_thread(writer.collection.insert, values, timeout=30)
                    if int(result.insert_count) != len(values):
                        raise RuntimeError("被覆盖目标的向量恢复写入不完整")

    async def move_unversioned(self, unit: dict[str, Any], checkpoint: Any, *, recover: bool = False) -> None:
        async with self.locked_document(unit) as (session, _, _, files, _, folder, target, owner):
            file = files[0]
            fid = str(file.id)
            in_target = file.knowledge_id == target.id
            identity = (
                recovery_identity_fingerprint(unit, file, [], files, [])
                if recover
                else identity_fingerprint(file, [], files, [])
            )
            if recover:
                if identity != unit["before"]["identity"] or int(owner.user_id) != unit["target_owner_id"]:
                    raise ValueError("原始文件内容、状态或权限所有者已变化，拒绝恢复")
                allowed = unit["before"]["permissions"][fid] + unit["desired_permissions"][fid]
                if any(row not in allowed for row in await self.read_permissions(file.id)):
                    raise ValueError("文件权限存在本次迁移之外的修改，拒绝覆盖")
            else:
                if unit.get("before") or in_target:
                    raise ValueError("文件已迁入或存在未完成记录，请核对报告")
                await self.prepare_conflict_rename(session, unit, file, files, folder)
                overwrite_graphs = await self.prepare_overwrites(session, unit, recover=False, in_target=False)
                unit["target_owner_id"] = int(owner.user_id)
                unit["before"] = {
                    "identity": identity,
                    "files": [file.model_dump(mode="json")],
                    "permissions": {fid: await self.read_permissions(file.id)},
                }
                unit["desired_permissions"] = {
                    fid: [
                        {"user": f"user:{owner.user_id}", "relation": "owner", "object": f"knowledge_file:{file.id}"},
                        {
                            "user": f"folder:{folder.id}" if folder else f"knowledge_space:{target.id}",
                            "relation": "parent",
                            "object": f"knowledge_file:{file.id}",
                        },
                    ]
                }
                unit["status"] = "prepared"
                checkpoint()
                await self.recycle_overwrites(session, unit, overwrite_graphs, checkpoint)
                file.original_knowledge_id = file.original_knowledge_id or file.knowledge_id
                file.original_uploader_id = file.original_uploader_id or file.user_id
                file.knowledge_id = target.id
                file.file_level_path, file.level = target_path(folder), len(unit["folder_parts"])
                if unit.get("rename"):
                    file.file_name = unit["rename"]["new_name"]
                session.add(file)
                in_target = True
            if recover:
                overwrite_graphs = await self.prepare_overwrites(session, unit, recover=True, in_target=in_target)
            desired = unit["desired_permissions"] if in_target else unit["before"]["permissions"]
            unit.update(status="syncing", destination="target" if in_target else "source")
            checkpoint()
            await self.replace_permissions(file.id, desired[fid])
            await self.sync_overwrites(unit, overwrite_graphs, in_target=in_target)
            unit["status"] = "committing"
            checkpoint()
            await session.commit()
        await self.refresh_metadata(unit)
        unit["status"] = "succeeded" if in_target else "restored"
        checkpoint()

    async def move_unit(
        self, unit: dict[str, Any], checkpoint: Any, *, recover: bool = False, force_rewrite: bool = False
    ) -> None:
        if unit.get("unversioned"):
            await self.move_unversioned(unit, checkpoint, recover=recover)
            return
        from bisheng.knowledge.domain.contracts.shared_storage_reconcile import DocumentSnapshot, MetadataRepair

        async with self.locked_document(unit) as (session, document, versions, files, entries, folder, target, owner):
            manager = next((e for e in entries if e.entry_type == "manager" and e.entry_status == "active"), None)
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
                try:
                    await self.prepare_conflict_rename(session, unit, primary_file, files, folder)
                except SkipFile as exc:
                    unit.update(
                        status="skipped",
                        reason_code=exc.code,
                        reason=str(exc),
                    )
                    checkpoint()
                    return
            elif recovery_identity_fingerprint(unit, document, versions, files, entries) != unit["before"]["identity"]:
                raise ValueError("文档内容、版本或入口发生变化，拒绝使用旧报告恢复")
            if recover:
                if int(owner.user_id) != unit["target_owner_id"]:
                    raise ValueError("目标库所有者已变化，拒绝使用旧报告恢复")
                for file in files:
                    allowed = unit["before"]["permissions"][str(file.id)] + unit["desired_permissions"][str(file.id)]
                    if any(row not in allowed for row in await self.read_permissions(int(file.id))):
                        raise ValueError("文件权限存在本次迁移之外的修改，拒绝覆盖")
            overwrite_graphs = await self.prepare_overwrites(session, unit, recover=recover, in_target=in_target)
            primary = next(v for v in versions if v.id == document.primary_version_id)
            observed = {
                side: (await self.store.read(side, [document.id])).get(document.id, []) for side in ("es", "milvus")
            }
            if manager is None and any(observed.values()):
                raise SkipFile("content_without_manager", "文档缺少管理入口但已有共享索引内容，需先核对入口与索引归属")
            # 无管理入口时不创建检索成员；两侧必须为空且在提交前再次确认。
            allow_incomplete = (
                manager is None or manager.status != 2 or allows_failed_projection(unit, manager, entries)
            )
            fingerprints = validate_chunks(
                observed, unit, document, primary, self.store.embedding_model_id, allow_incomplete=allow_incomplete
            )
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
                await self.recycle_overwrites(session, unit, overwrite_graphs, checkpoint)
                for file in files:
                    file.original_knowledge_id = file.original_knowledge_id or file.knowledge_id
                    file.original_uploader_id = file.original_uploader_id or file.user_id
                    file.knowledge_id, file.file_level_path, file.level = (
                        target.id,
                        target_path(folder),
                        (folder.level + 1 if folder else 0),
                    )
                    if unit.get("rename") and file.id == unit["rename"]["file_id"]:
                        file.file_name = unit["rename"]["new_name"]
                    session.add(file)
                document.knowledge_id, document.file_level_path, document.level = (
                    target.id,
                    target_path(folder),
                    (folder.level + 1 if folder else 0),
                )
                session.add(document)
                in_target = True
            desired = unit["desired_permissions"] if in_target else unit["before"]["permissions"]
            if manager is not None:
                manager.desired_entry_generation = next_generation
                # 未完成解析的投影不能因迁移变成已应用，保留后续解析/重试所需状态。
                if not allow_incomplete:
                    manager.applied_entry_generation = next_generation
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
            await self.sync_overwrites(unit, overwrite_graphs, in_target=in_target)
            pending_sides = {side for side, rows in observed.items() if rows}
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
                if (
                    validate_chunks(
                        actual,
                        unit,
                        document,
                        primary,
                        self.store.embedding_model_id,
                        allow_incomplete=allow_incomplete,
                    )
                    != fingerprints
                ):
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
                        if unit.get("rename") and file_id == unit["rename"]["file_id"]:
                            values["file_name"] = source.file_name
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

        if unit.get("destination") != "target":
            return
        from elasticsearch import NotFoundError

        for record in unit.get("overwrites", []):
            file_id = record["file_id"]
            async with get_async_db_session() as session:
                file, document, versions, entries = await self.overwrite_graph(session, file_id)
                if not overwrite_identity_matches(record, document, versions, file, entries, in_target=True):
                    raise ValueError("被覆盖目标在提交后发生变化，拒绝清理元数据")
                if await client.indices.exists(index=constants.KNOWLEDGE_FULLTEXT_INDEX_ALIAS):
                    result = await client.mget(index=constants.KNOWLEDGE_FULLTEXT_INDEX_ALIAS, ids=[str(file_id)])
                    docs = result.get("docs", [])
                    if len(docs) != 1 or docs[0].get("error"):
                        raise RuntimeError("被覆盖目标全文索引查询失败")
                    row = docs[0]
                    if row.get("found"):
                        try:
                            await client.delete(
                                index=constants.KNOWLEDGE_FULLTEXT_INDEX_ALIAS,
                                id=str(file_id),
                                if_seq_no=row["_seq_no"],
                                if_primary_term=row["_primary_term"],
                                refresh="wait_for",
                            )
                        except NotFoundError:
                            # 并发清理已删除同一回收文件, 无需重复删除。
                            pass
                    result = await client.mget(index=constants.KNOWLEDGE_FULLTEXT_INDEX_ALIAS, ids=[str(file_id)])
                    docs = result.get("docs", [])
                    if len(docs) != 1 or docs[0].get("found") or docs[0].get("error"):
                        raise RuntimeError("被覆盖目标全文索引清理未确认")
                service = PortalRecommendationProjectionService(
                    source_repository=PortalRecommendationSourceRepositoryImpl(session),
                    projection_repository=PortalRecommendationRepositoryImpl(session),
                )
                if not await service.refresh_file(
                    file_id, projection_version=int(time.time() * 1_000_000), deleted=True
                ):
                    raise RuntimeError("被覆盖目标推荐目录清理未确认")
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
                **({"unversioned": True} if file.get("unversioned") else {}),
                **({"api_sync_only": True} if plan.get("api_sync_only") else {}),
                **({"allow_failed_projection": True} if plan.get("allow_failed_projection") else {}),
                **({"rename_conflicts": True} if plan.get("rename_conflicts") else {}),
                **({"overwrite_same_content": True} if plan.get("overwrite_same_content") else {}),
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
        plan = build_plan(snapshot, args.tenant_id, args.folder_parts, api_sync_only=args.api_sync_only)
        plan["allow_failed_projection"] = args.allow_failed_projection
        plan["rename_conflicts"] = args.rename_conflicts
        plan["overwrite_same_content"] = args.overwrite_same_content
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
                        fresh = build_plan(
                            fresh_snapshot, args.tenant_id, args.folder_parts, api_sync_only=args.api_sync_only
                        )
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
