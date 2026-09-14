#!/usr/bin/env python3
"""在 B 的 bisheng-backend 容器内迁入一个知识空间。默认 dry-run。

走 KnowledgeSpaceService 建空间 + PermissionService.authorize 写新 tuple。
不插入 A 的自增 ID, 不拷 A 的 Milvus/ES/OpenFGA。
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

_BACKEND_ROOT = Path("/app")
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from apply_ingest import ingest_files  # noqa: E402
from apply_tags import apply_tags  # noqa: E402


class _FusionRequest:
    headers: dict = {}
    client = SimpleNamespace(host="127.0.0.1")


def _load_user_map(path: Path) -> dict[int, int]:
    out: dict[int, int] = {}
    with path.open(encoding="utf-8") as f:
        filtered = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    for row in csv.DictReader(filtered):
        a_id = int(row["a_user_id"])
        b_raw = (row.get("b_user_id") or "").strip()
        if not b_raw or b_raw == "0":
            continue
        out[a_id] = int(b_raw)
    return out


def _load_dept_map(path: Path | None) -> dict[int, int]:
    if path is None or not path.exists():
        return {}
    out: dict[int, int] = {}
    with path.open(encoding="utf-8") as f:
        filtered = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    for row in csv.DictReader(filtered):
        if row.get("a_dept_pk") and row.get("b_dept_pk"):
            out[int(row["a_dept_pk"])] = int(row["b_dept_pk"])
    return out


ROLE_TO_RELATION = {
    "creator": "owner",
    "admin": "manager",
    "member": "viewer",
}


async def _existing_maps(a_space_id: int) -> tuple[int | None, dict[int, dict]]:
    from sqlalchemy import text

    from bisheng.core.database import get_async_db_session

    b_space_id = None
    files: dict[int, dict] = {}
    async with get_async_db_session() as session:
        space = (
            await session.execute(
                text("SELECT b_space_id FROM fusion_space_map WHERE a_space_id=:aid"),
                {"aid": a_space_id},
            )
        ).first()
        if space and space[0]:
            b_space_id = int(space[0])
        rows = (
            await session.execute(
                text(
                    "SELECT a_file_id, b_file_id, src_object_key, dst_object_key, "
                    "size_bytes, content_sha256 FROM fusion_file_map"
                )
            )
        ).all()
        for row in rows:
            files[int(row[0])] = {
                "b_file_id": int(row[1]) if row[1] else None,
                "src_object_key": row[2],
                "dst_object_key": row[3],
                "size_bytes": row[4],
                "content_sha256": row[5],
            }
    return b_space_id, files


async def _write_maps(
    *,
    batch_no: str,
    a_space_id: int,
    b_space_id: int,
    note: str,
    file_rows: list[dict],
    doc_rows: list[dict],
    exceptions: list[dict],
) -> None:
    from sqlalchemy import text

    from bisheng.core.database import get_async_db_session

    async with get_async_db_session() as session:
        await session.execute(
            text(
                "INSERT INTO fusion_batch (batch_no, phase, status, note) VALUES "
                "(:b,'p5_space','applied',:n) ON DUPLICATE KEY UPDATE status='applied'"
            ),
            {"b": batch_no, "n": note},
        )
        await session.execute(
            text(
                "INSERT INTO fusion_space_map (batch_no,a_space_id,b_space_id,status,note) "
                "VALUES (:b,:a,:s,'hidden',:n) ON DUPLICATE KEY UPDATE "
                "b_space_id=VALUES(b_space_id), status='hidden', note=VALUES(note)"
            ),
            {"b": batch_no, "a": a_space_id, "s": b_space_id, "n": note},
        )
        for row in file_rows:
            await session.execute(
                text(
                    "INSERT INTO fusion_file_map "
                    "(batch_no,a_file_id,b_file_id,src_object_key,dst_object_key,size_bytes,content_sha256) "
                    "VALUES (:b,:a,:bf,:src,:dst,:sz,:sha) ON DUPLICATE KEY UPDATE "
                    "b_file_id=VALUES(b_file_id), dst_object_key=VALUES(dst_object_key), "
                    "size_bytes=VALUES(size_bytes), content_sha256=VALUES(content_sha256)"
                ),
                {
                    "b": batch_no,
                    "a": row["a_file_id"],
                    "bf": row.get("b_file_id"),
                    "src": row.get("src_object_key"),
                    "dst": row.get("dst_object_key"),
                    "sz": row.get("size_bytes"),
                    "sha": row.get("content_sha256"),
                },
            )
        for row in doc_rows:
            await session.execute(
                text(
                    "INSERT INTO fusion_document_map (batch_no,a_doc_id,b_doc_id) "
                    "VALUES (:b,:a,:s) ON DUPLICATE KEY UPDATE b_doc_id=VALUES(b_doc_id)"
                ),
                {"b": batch_no, "a": row["a_doc_id"], "s": row["b_doc_id"]},
            )
        for exc in exceptions:
            await session.execute(
                text(
                    "INSERT INTO fusion_exception "
                    "(batch_no,a_space_id,a_file_id,kind,detail) "
                    "VALUES (:b,:s,:f,:k,:d)"
                ),
                {
                    "b": batch_no,
                    "s": exc.get("a_space_id") or a_space_id,
                    "f": exc.get("a_file_id"),
                    "k": exc.get("kind"),
                    "d": (exc.get("detail") or "")[:1024],
                },
            )
        await session.commit()


def _put_object(key: str, path: Path) -> None:
    from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync

    client = get_minio_storage_sync()
    if client.object_exists_sync(object_name=key):
        return
    client.put_object_sync(object_name=key, file=str(path))


async def apply_space(
    *,
    export: dict,
    plan: dict,
    user_map: dict[int, int],
    dept_map: dict[int, int],
    object_dir: Path,
    batch_no: str,
    apply: bool,
    manifest_path: Path,
) -> dict:
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.common.models.space_channel_member import (
        BusinessTypeEnum,
        MembershipStatusEnum,
        SpaceChannelMember,
        SpaceChannelMemberDao,
        UserRoleEnum,
    )
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.core.database import get_async_db_session
    from bisheng.knowledge.domain.models.knowledge import (
        AuthTypeEnum,
        KnowledgeDao,
        KnowledgeState,
    )
    from bisheng.knowledge.domain.models.knowledge_space_scope import (
        KnowledgeSpaceLevelEnum,
    )
    from bisheng.knowledge.domain.services.knowledge_space_service import (
        KnowledgeSpaceService,
    )
    from bisheng.permission.domain.schemas.permission_schema import AuthorizeGrantItem
    from bisheng.permission.domain.services.permission_service import PermissionService
    from bisheng.user.domain.models.user import UserDao

    a_space_id = int(export["space"]["id"])
    if not plan.get("ok"):
        raise SystemExit(
            f"dry-run 未通过, 阻断 a_space_id={a_space_id}: {plan.get('reasons')}"
        )
    owner_b = int(plan["owner_b_user_id"])
    target_name = plan["target_name"]
    result = {
        "a_space_id": a_space_id,
        "b_space_id": None,
        "target_name": target_name,
        "owner_b_user_id": owner_b,
    }
    if not apply:
        print(
            json.dumps(
                {"dry_run": True, **result, "plan": plan}, ensure_ascii=False, indent=2
            )
        )
        return result

    existing_space, existing_files = await _existing_maps(a_space_id)
    owner = UserDao.get_user(owner_b)
    login_user = UserPayload(
        user_id=owner_b,
        user_name=getattr(owner, "user_name", "") if owner else "fusion",
        tenant_id=1,
        user_role=[2],
        is_global_super=True,
    )
    level_raw = plan.get("level") or "personal"
    try:
        level = KnowledgeSpaceLevelEnum(level_raw)
    except ValueError:
        level = KnowledgeSpaceLevelEnum.PERSONAL
    dept_id = None
    scope = export.get("scope") or {}
    if scope.get("owner_type") == "department" and scope.get("owner_id"):
        dept_id = dept_map.get(int(scope["owner_id"]))
        if dept_id is None:
            raise SystemExit(
                f"空间部门作用域映不上, 禁止降级 personal a_space_id={a_space_id} "
                f"a_dept={scope.get('owner_id')}"
            )

    try:
        auth_type = AuthTypeEnum(export["space"].get("auth_type") or "public")
    except ValueError:
        auth_type = AuthTypeEnum.PUBLIC

    merge_favorite = plan.get("merge_favorite_b_space_id")
    b_space_id = existing_space or (int(merge_favorite) if merge_favorite else None)
    if b_space_id is None:
        svc = KnowledgeSpaceService(_FusionRequest(), login_user)
        with bypass_tenant_filter():
            space = await svc.create_knowledge_space(
                name=target_name,
                description=export["space"].get("description"),
                icon=export["space"].get("icon") or None,
                auth_type=auth_type,
                is_released=False,
                space_level=level,
                department_id=dept_id,
                system_managed=True,
                skip_user_limit=True,
                validate_tag_libraries=False,
            )
        b_space_id = int(space.id)
        await KnowledgeDao.async_update_state(b_space_id, KnowledgeState.UNPUBLISHED)
        if export["space"].get("is_favorite"):
            from sqlalchemy import text as sql_text

            async with get_async_db_session() as session:
                await session.execute(
                    sql_text("UPDATE knowledge SET is_favorite=1 WHERE id=:i"),
                    {"i": b_space_id},
                )
                await session.commit()

    result["b_space_id"] = b_space_id
    async with get_async_db_session() as session:
        ingest = await ingest_files(
            session,
            export=export,
            b_space_id=b_space_id,
            owner_b=owner_b,
            owner_name=login_user.user_name,
            user_map=user_map,
            object_dir=object_dir,
            batch_no=batch_no,
            existing_file_map=existing_files,
            put_object=_put_object,
        )
        tag_result = await apply_tags(
            session,
            export=export,
            b_space_id=b_space_id,
            owner_b=owner_b,
            batch_no=batch_no,
            user_map=user_map,
        )
        ingest.setdefault("exceptions", []).extend(tag_result.get("exceptions") or [])
        await session.commit()

    for member in plan.get("members_ok") or []:
        grant_type = (member.get("grant_subject_type") or "user").lower()
        if grant_type == "department":
            rel = member.get("grant_relation") or "viewer"
            try:
                await PermissionService.authorize(
                    object_type="knowledge_space",
                    object_id=str(b_space_id),
                    grants=[
                        AuthorizeGrantItem(
                            subject_type="department",
                            subject_id=int(member["b_subject_id"]),
                            relation=rel,
                            include_children=True,
                        )
                    ],
                    enforce_fga_success=False,
                )
            except Exception as exc:  # noqa: BLE001 - 部门授权失败进例外, 不阻断
                ingest["exceptions"].append(
                    {
                        "kind": "dept_unmapped",
                        "a_space_id": a_space_id,
                        "detail": f"authorize department failed: {exc}",
                    }
                )
            continue
        b_uid = int(member.get("b_user_id") or 0)
        if not b_uid or b_uid == owner_b:
            continue
        role = (member.get("user_role") or "member").lower()
        try:
            user_role = UserRoleEnum(role)
        except ValueError:
            user_role = UserRoleEnum.MEMBER
        existed = await SpaceChannelMemberDao.async_find_member(b_space_id, b_uid)
        if existed is None:
            await SpaceChannelMemberDao.async_insert_member(
                SpaceChannelMember(
                    business_id=str(b_space_id),
                    business_type=BusinessTypeEnum.SPACE,
                    user_id=b_uid,
                    user_role=user_role,
                    status=MembershipStatusEnum.ACTIVE,
                    membership_source="manual",
                    is_pinned=bool(member.get("is_pinned")),
                )
            )
        elif member.get("is_pinned"):
            await SpaceChannelMemberDao.pin_space_id(b_space_id, b_uid, True)
        rel = ROLE_TO_RELATION.get(role, "viewer")
        if rel == "owner":
            continue
        await PermissionService.authorize(
            object_type="knowledge_space",
            object_id=str(b_space_id),
            grants=[
                AuthorizeGrantItem(
                    subject_type="user",
                    subject_id=b_uid,
                    relation=rel,
                    include_children=False,
                )
            ],
            enforce_fga_success=False,
        )

    exceptions = list(plan.get("exceptions") or []) + list(
        ingest.get("exceptions") or []
    )
    await _write_maps(
        batch_no=batch_no,
        a_space_id=a_space_id,
        b_space_id=b_space_id,
        note=target_name,
        file_rows=ingest.get("file_map_rows") or [],
        doc_rows=ingest.get("doc_map_rows") or [],
        exceptions=exceptions,
    )

    enqueue = subprocess.run(
        [
            sys.executable,
            "scripts/enqueue_reparse_knowledge_space_files.py",
            "--apply",
            "--space-id",
            str(b_space_id),
            "--status",
            "success",
            "--status",
            "failed",
            "--status",
            "timeout",
        ],
        cwd=str(_BACKEND_ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    result["enqueue_exit"] = enqueue.returncode
    result["enqueue_stdout"] = (enqueue.stdout or "")[-2000:]
    if enqueue.returncode != 0:
        result["enqueue_stderr"] = (enqueue.stderr or "")[-2000:]
        print(json.dumps({"applied": True, **result}, ensure_ascii=False, indent=2))
        raise SystemExit(
            f"入队重解析失败 rc={enqueue.returncode} a_space_id={a_space_id} "
            f"b_space_id={b_space_id}: {(enqueue.stderr or '')[-500:]}"
        )

    manifest = {
        "batch_no": batch_no,
        "a_space_id": a_space_id,
        "b_space_id": b_space_id,
        "b_object_keys": ingest.get("new_object_keys") or [],
        "b_file_ids": [
            row.get("b_file_id") for row in ingest.get("file_map_rows") or []
        ],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if manifest_path.exists():
        prev = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(prev, list):
            prev.append(manifest)
            payload = prev
        else:
            payload = [prev, manifest]
    else:
        payload = [manifest]
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"applied": True, **result}, ensure_ascii=False, indent=2))
    return result


async def _amain(args: argparse.Namespace) -> int:
    from bisheng.common.services.config_service import settings
    from bisheng.core.context.manager import close_app_context, initialize_app_context

    export = json.loads(Path(args.export_json).read_text(encoding="utf-8"))
    dry = json.loads(Path(args.dry_run).read_text(encoding="utf-8"))
    a_space_id = int(export["space"]["id"])
    plan = None
    for row in dry.get("spaces") or []:
        if int(row["a_space_id"]) == a_space_id:
            plan = row
            break
    if plan is None:
        raise SystemExit(f"dry-run 报告没有 a_space_id={a_space_id}")
    user_map = _load_user_map(Path(args.user_map))
    dept_map = _load_dept_map(Path(args.dept_map) if args.dept_map else None)
    await initialize_app_context(config=settings)
    try:
        await apply_space(
            export=export,
            plan=plan,
            user_map=user_map,
            dept_map=dept_map,
            object_dir=Path(args.object_dir),
            batch_no=args.batch_no,
            apply=args.apply,
            manifest_path=Path(args.manifest),
        )
    finally:
        await close_app_context()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-json", required=True)
    parser.add_argument("--dry-run", required=True)
    parser.add_argument("--user-map", required=True)
    parser.add_argument("--dept-map", default="")
    parser.add_argument("--object-dir", required=True)
    parser.add_argument("--batch-no", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    sys.exit(asyncio.run(_amain(args)))


if __name__ == "__main__":
    main()
