#!/usr/bin/env python3
"""用冻结的 fusion_user_map 解空间所有者与成员。解不了所有者则阻断该空间。"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


SUFFIX = "[A迁移]"
REPARSE_STATUSES = {2, 3, 6}  # SUCCESS / FAILED / TIMEOUT
VIOLATION = 7


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        filtered = [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    if not filtered:
        return []
    return [
        {k: (v or "").strip() for k, v in row.items() if k}
        for row in csv.DictReader(filtered)
    ]


def load_user_map(path: Path) -> dict[int, dict[str, str]]:
    out: dict[int, dict[str, str]] = {}
    for row in _read_csv(path):
        a_id = int(row["a_user_id"])
        out[a_id] = row
    return out


def load_dept_map(path: Path | None) -> dict[int, dict[str, str]]:
    if path is None or not path.exists():
        return {}
    out: dict[int, dict[str, str]] = {}
    for row in _read_csv(path):
        if not row.get("a_dept_pk"):
            continue
        out[int(row["a_dept_pk"])] = row
    return out


def load_b_favorites(path: Path | None) -> dict[int, int]:
    out: dict[int, int] = {}
    if path is None or not path.exists():
        return out
    for row in _read_csv(path):
        if row.get("user_id") and row.get("id"):
            out[int(row["user_id"])] = int(row["id"])
    return out


def load_b_names(path: Path | None) -> set[str]:
    names: set[str] = set()
    if path is None or not path.exists():
        return names
    for line in path.read_text(encoding="utf-8").splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1].strip():
            names.add(parts[1].strip())
    return names


def dry_run_space(
    data: dict,
    user_map: dict[int, dict[str, str]],
    dept_map: dict[int, dict[str, str]],
    b_names: set[str],
    b_favorites: dict[int, int] | None = None,
) -> dict:
    space = data["space"]
    a_space_id = int(space["id"])
    owner_a = space.get("user_id")
    exceptions: list[dict] = []
    blocked = False
    reasons: list[str] = []

    owner_row = user_map.get(int(owner_a)) if owner_a is not None else None
    owner_b = None
    b_favorites = b_favorites or {}
    if (
        owner_row is None
        or not owner_row.get("b_user_id")
        or owner_row.get("b_user_id") == "0"
    ):
        if owner_row and owner_row.get("action") == "create_on_b":
            reasons.append("所有者仍是 create_on_b 占位, 需先 APPLY P4")
        else:
            reasons.append(f"所有者 a_user_id={owner_a} 不在 fusion_user_map")
        blocked = True
        exceptions.append(
            {
                "kind": "owner_unmapped",
                "a_space_id": a_space_id,
                "detail": reasons[-1],
            }
        )
    else:
        owner_b = int(owner_row["b_user_id"])

    name = (space.get("name") or "").strip()
    target_name = name
    if name in b_names:
        target_name = f"{name}{SUFFIX}"
        if target_name in b_names:
            target_name = f"{name}{SUFFIX}-{a_space_id}"
        exceptions.append(
            {
                "kind": "name_suffix",
                "a_space_id": a_space_id,
                "detail": f"B 已有同名, 使用 {target_name}",
            }
        )

    members_ok = []
    members_skip = []
    for member in data.get("members") or []:
        grant_type = (member.get("grant_subject_type") or "").lower()
        if grant_type == "department":
            dept_id = member.get("grant_subject_id")
            mapped = dept_map.get(int(dept_id)) if dept_id else None
            if not mapped or not mapped.get("b_dept_pk"):
                exceptions.append(
                    {
                        "kind": "dept_unmapped",
                        "a_space_id": a_space_id,
                        "detail": f"部门授权 a_dept={dept_id} 映不上, 不阻断用户成员",
                    }
                )
                continue
            members_ok.append({**member, "b_subject_id": int(mapped["b_dept_pk"])})
            continue
        a_uid = int(member["user_id"])
        row = user_map.get(a_uid)
        if row is None or not row.get("b_user_id") or row.get("b_user_id") == "0":
            members_skip.append(a_uid)
            exceptions.append(
                {
                    "kind": "member_unmapped",
                    "a_space_id": a_space_id,
                    "detail": f"成员 a_user_id={a_uid} 映不上, 跳过该成员",
                }
            )
            continue
        members_ok.append({**member, "b_user_id": int(row["b_user_id"])})

    files = data.get("files") or []
    reparse = []
    violation = []
    copy_objects = []
    for f in files:
        if int(f.get("file_type") or 1) != 1:
            continue
        st = int(f.get("status") or 0)
        if st == VIOLATION:
            violation.append(int(f["id"]))
            exceptions.append(
                {
                    "kind": "violation",
                    "a_space_id": a_space_id,
                    "a_file_id": int(f["id"]),
                    "detail": f["file_name"],
                }
            )
        elif st in REPARSE_STATUSES:
            reparse.append(int(f["id"]))
        if f.get("object_name"):
            copy_objects.append(f["object_name"])
        if f.get("preview_file_object_name"):
            copy_objects.append(f["preview_file_object_name"])
        if f.get("thumbnails"):
            copy_objects.append(f["thumbnails"])

    scope = data.get("scope") or {}
    level = scope.get("level") or "personal"
    if scope.get("owner_type") == "department" and scope.get("owner_id"):
        dept_id = int(scope["owner_id"])
        mapped = dept_map.get(dept_id)
        if mapped is None:
            blocked = True
            reasons.append(
                f"部门作用域 a_dept={dept_id} 不在 fusion_dept_map, 禁止降级 personal"
            )
            exceptions.append(
                {
                    "kind": "dept_unmapped",
                    "a_space_id": a_space_id,
                    "detail": reasons[-1],
                }
            )
        elif not mapped.get("b_dept_pk") and mapped.get("action") != "create":
            blocked = True
            reasons.append(f"部门作用域 a_dept={dept_id} 无 b_dept_pk")
            exceptions.append(
                {
                    "kind": "dept_unmapped",
                    "a_space_id": a_space_id,
                    "detail": reasons[-1],
                }
            )
        elif mapped.get("action") == "create" and not mapped.get("b_dept_pk"):
            exceptions.append(
                {
                    "kind": "dept_pending_create",
                    "a_space_id": a_space_id,
                    "detail": f"部门 a_dept={dept_id} 将新建, APPLY 空间前须先 APPLY 部门",
                }
            )

    merge_favorite_b_space_id = None
    if data.get("space", {}).get("is_favorite") and owner_b:
        fav_b = b_favorites.get(int(owner_b))
        if fav_b:
            merge_favorite_b_space_id = fav_b
            target_name = name
            exceptions.append(
                {
                    "kind": "favorite_merge",
                    "a_space_id": a_space_id,
                    "detail": f"B 用户 {owner_b} 已有收藏库 {fav_b}, 文件并入不新建",
                }
            )

    return {
        "a_space_id": a_space_id,
        "ok": not blocked,
        "blocked": blocked,
        "reasons": reasons,
        "a_name": name,
        "target_name": target_name,
        "owner_a_user_id": owner_a,
        "owner_b_user_id": owner_b,
        "level": level,
        "merge_favorite_b_space_id": merge_favorite_b_space_id,
        "members_ok": members_ok,
        "members_skip": members_skip,
        "file_total": len(files),
        "reparse_file_ids": reparse,
        "violation_file_ids": violation,
        "copy_objects": len(copy_objects),
        "exceptions": exceptions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-dir", type=Path, required=True)
    parser.add_argument("--user-map", type=Path, required=True)
    parser.add_argument("--dept-map", type=Path, default=None)
    parser.add_argument("--b-names", type=Path, default=None)
    parser.add_argument("--b-favorites", type=Path, default=None)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    user_map = load_user_map(args.user_map)
    if not user_map:
        raise SystemExit(f"用户映射为空: {args.user_map}")
    dept_map = load_dept_map(args.dept_map)
    b_names = load_b_names(args.b_names)
    b_favorites = load_b_favorites(args.b_favorites)

    reports = []
    for path in sorted(args.json_dir.glob("a-space-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        reports.append(dry_run_space(data, user_map, dept_map, b_names, b_favorites))

    blocked = [r for r in reports if r["blocked"]]
    ok = [r for r in reports if r["ok"]]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ok_count": len(ok),
        "blocked_count": len(blocked),
        "spaces": reports,
    }
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"ok={len(ok)} blocked={len(blocked)} -> {args.out}")
    for row in blocked:
        print(f"BLOCK a_space_id={row['a_space_id']} {'; '.join(row['reasons'])}")
    if blocked:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
