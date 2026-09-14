#!/usr/bin/env python3
"""按 department.external_id 生成部门映射候选。禁止按部门名自动合并。

规则:
- 外部编码相同: bind, 保留 B id
- B 无此编码: create
- 无编码: 进人工清单, 不建
- 同名不同编码: 不合并, create 并记 note
- B 同一编码多行 / A 父绑到与 B 现父不同的部门: 进冲突清单
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

_PACK_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_PACK_LIB) not in sys.path:
    sys.path.insert(0, str(_PACK_LIB))

from sqlutil import load_tsv, write_csv  # noqa: E402


def _norm(value: str | None) -> str:
    return (value or "").strip()


def _int_or_blank(value: str | None) -> str:
    text = _norm(value)
    if not text:
        return ""
    return str(int(text))


def topo_sort(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """父部门在子部门之前。环则原样返回并在 note 里由调用方处理。"""
    by_id = {int(r["id"]): r for r in rows if r.get("id")}
    visiting: set[int] = set()
    visited: set[int] = set()
    ordered: list[dict[str, str]] = []
    cyclic = False

    def visit(pk: int) -> None:
        nonlocal cyclic
        if pk in visited or pk not in by_id:
            return
        if pk in visiting:
            cyclic = True
            return
        visiting.add(pk)
        parent = _norm(by_id[pk].get("parent_id", ""))
        if parent:
            visit(int(parent))
        visiting.remove(pk)
        visited.add(pk)
        ordered.append(by_id[pk])

    for row in rows:
        visit(int(row["id"]))
    if cyclic:
        return rows
    return ordered


def propose(
    a_rows: list[dict[str, str]], b_rows: list[dict[str, str]]
) -> dict[str, list[dict[str, str]]]:
    """生成 map / conflict / manual。"""
    b_by_ext: dict[str, list[dict[str, str]]] = defaultdict(list)
    b_by_id: dict[int, dict[str, str]] = {}
    b_names: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in b_rows:
        if not row.get("id"):
            continue
        b_by_id[int(row["id"])] = row
        code = _norm(row.get("external_id", ""))
        if code:
            b_by_ext[code].append(row)
        name = _norm(row.get("name", ""))
        if name:
            b_names[name].append(row)

    mapped: list[dict[str, str]] = []
    conflicts: list[dict[str, str]] = []
    manual: list[dict[str, str]] = []
    a_action: dict[int, dict[str, str]] = {}

    for row in topo_sort(a_rows):
        a_pk = int(row["id"])
        code = _norm(row.get("external_id", ""))
        deleted = _norm(row.get("is_deleted", "0")) in {"1", "true", "True"}
        if not code:
            manual.append(row)
            continue
        if deleted:
            manual.append({**row, "note": "A 已删除, 不在 B 新建"})
            continue

        hits = b_by_ext.get(code, [])
        live = [x for x in hits if _norm(x.get("is_deleted", "0")) not in {"1", "true"}]
        chosen = live[0] if live else (hits[0] if hits else None)
        if len(live) > 1:
            conflicts.append(
                {
                    "external_id": code,
                    "a_dept_pk": str(a_pk),
                    "a_name": row.get("name", ""),
                    "reason": f"B 同一 external_id 有 {len(live)} 行, 需定主部门",
                }
            )
            continue

        name = _norm(row.get("name", ""))
        name_note = ""
        if chosen is None and name in b_names:
            other_codes = sorted(
                {
                    _norm(b.get("external_id", ""))
                    for b in b_names[name]
                    if _norm(b.get("external_id", ""))
                    and _norm(b.get("external_id", "")) != code
                }
            )
            if other_codes:
                name_note = f"B 有同名部门但编码不同({','.join(other_codes)}), 不合并"

        if chosen is not None:
            action = "bind"
            b_pk = chosen["id"]
            note = "B 已有相同 external_id, 保留 B id"
        else:
            action = "create"
            b_pk = ""
            note = "B 无此外部编码, 将新建"
            if name_note:
                note = name_note + "; " + note

        item = {
            "a_dept_pk": str(a_pk),
            "b_dept_pk": str(b_pk),
            "external_id": code,
            "action": action,
            "a_name": row.get("name", ""),
            "a_dept_id": row.get("dept_id", ""),
            "a_source": row.get("source", "") or "sg",
            "a_parent_pk": _int_or_blank(row.get("parent_id")),
            "a_short_name": row.get("short_name", ""),
            "a_sort_order": row.get("sort_order", "0") or "0",
            "a_status": row.get("status", "") or "active",
            "a_tenant_id": row.get("tenant_id", "1") or "1",
            "note": note,
        }
        a_action[a_pk] = item
        mapped.append(item)

    for item in mapped:
        parent_a = _norm(item.get("a_parent_pk"))
        if not parent_a:
            continue
        parent_pk = int(parent_a)
        parent_item = a_action.get(parent_pk)
        if parent_item is None:
            item["note"] = (
                item.get("note") or ""
            ) + "; 父部门无编码或未映射, 新建时挂不到父节点"
            continue
        if item["action"] != "bind":
            continue
        b_pk = int(item["b_dept_pk"])
        b_row = b_by_id.get(b_pk)
        if b_row is None:
            continue
        b_parent = _int_or_blank(b_row.get("parent_id"))
        mapped_parent_b = _norm(parent_item.get("b_dept_pk"))
        if (
            parent_item["action"] == "bind"
            and mapped_parent_b
            and b_parent
            and mapped_parent_b != b_parent
        ):
            conflicts.append(
                {
                    "external_id": item["external_id"],
                    "a_dept_pk": item["a_dept_pk"],
                    "a_name": item.get("a_name", ""),
                    "reason": (
                        f"层级冲突: A 父 a_dept={parent_a} 映 B {mapped_parent_b}, "
                        f"B 部门 {b_pk} 当前父={b_parent}"
                    ),
                }
            )
    return {"map": mapped, "conflict": conflicts, "manual": manual}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("a_depts", type=Path)
    parser.add_argument("b_depts", type=Path)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()
    out_dir = args.out_dir or args.a_depts.parent
    result = propose(load_tsv(args.a_depts), load_tsv(args.b_depts))
    write_csv(
        out_dir / "dept-map.proposed.csv",
        [
            "a_dept_pk",
            "b_dept_pk",
            "external_id",
            "action",
            "a_name",
            "a_dept_id",
            "a_source",
            "a_parent_pk",
            "a_short_name",
            "a_sort_order",
            "a_status",
            "a_tenant_id",
            "note",
        ],
        result["map"],
        header_comment="按 external_id bind/create。禁止按部门名合并。层级冲突见 conflicts。",
    )
    write_csv(
        out_dir / "dept-conflicts.tsv",
        ["external_id", "a_dept_pk", "a_name", "reason"],
        result["conflict"],
    )
    write_csv(
        out_dir / "dept-manual.tsv",
        [
            "id",
            "dept_id",
            "name",
            "source",
            "external_id",
            "parent_id",
            "is_deleted",
            "note",
        ],
        result["manual"],
    )
    print(
        f"proposed={len(result['map'])} conflicts={len(result['conflict'])} "
        f"manual={len(result['manual'])} -> {out_dir}"
    )
    print("复核后复制为 p4/dept-map.csv 再跑 p4/04-apply-depts.sh (默认 APPLY=0)")


if __name__ == "__main__":
    main()
