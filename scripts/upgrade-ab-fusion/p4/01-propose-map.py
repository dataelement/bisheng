#!/usr/bin/env python3
"""按员工编码生成 user-map.csv 候选。禁止按姓名自动 takeover。

规则:
- 同一 external_id 的 A local+sg 两行使用同一个 b_user_id 占位 (X01)
- B 上已有相同 external_id 才标 takeover
- 仅登录名相同、编码不同: 进冲突清单, 不自动 takeover
- 其余 create_on_b
- 无编码 (如 admin) 进人工清单
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path


def _read_users(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            item = {k: (v or "").strip() for k, v in row.items() if k}
            if not item.get("user_id"):
                continue
            rows.append(item)
    return rows


def _norm_code(value: str) -> str:
    return (value or "").strip()


def propose(
    a_rows: list[dict[str, str]], b_rows: list[dict[str, str]]
) -> dict[str, list[dict[str, str]]]:
    """生成 map / conflict / manual 三份清单。"""
    b_by_ext: dict[str, list[dict[str, str]]] = defaultdict(list)
    b_by_name: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in b_rows:
        code = _norm_code(row.get("external_id", ""))
        if code:
            b_by_ext[code].append(row)
        name = (row.get("user_name") or "").strip()
        if name:
            b_by_name[name.lower()].append(row)

    a_by_ext: dict[str, list[dict[str, str]]] = defaultdict(list)
    manual: list[dict[str, str]] = []
    for row in a_rows:
        code = _norm_code(row.get("external_id", ""))
        if not code:
            manual.append(row)
            continue
        a_by_ext[code].append(row)

    mapped: list[dict[str, str]] = []
    conflicts: list[dict[str, str]] = []

    for code, group in sorted(a_by_ext.items()):
        b_hits = b_by_ext.get(code, [])
        live_b = [x for x in b_hits if x.get("delete", "0") != "1"]
        chosen_b = live_b[0] if live_b else (b_hits[0] if b_hits else None)

        name_conflicts: list[str] = []
        if chosen_b is None:
            for a_row in group:
                name = (a_row.get("user_name") or "").strip()
                if not name:
                    continue
                for b_row in b_by_name.get(name.lower(), []):
                    b_code = _norm_code(b_row.get("external_id", ""))
                    if b_code and b_code != code:
                        name_conflicts.append(
                            f"A user_name={name} a_id={a_row['user_id']} "
                            f"vs B user_id={b_row['user_id']} external_id={b_code}"
                        )
                    elif not b_code:
                        name_conflicts.append(
                            f"A user_name={name} a_id={a_row['user_id']} "
                            f"vs B user_id={b_row['user_id']} 无编码(禁止按姓名 takeover)"
                        )

        if name_conflicts and chosen_b is None:
            for a_row in group:
                conflicts.append(
                    {
                        "employee_code": code,
                        "a_user_id": a_row["user_id"],
                        "a_user_name": a_row.get("user_name", ""),
                        "a_source": a_row.get("source", ""),
                        "reason": "; ".join(name_conflicts),
                    }
                )
            continue

        if chosen_b is not None:
            action = "takeover"
            b_user_id = chosen_b["user_id"]
            note = "B 已有相同 external_id"
        else:
            action = "create_on_b"
            b_user_id = "0"
            note = "B 无此员工编码, 将新建"

        preferred_name = ""
        for a_row in group:
            if (a_row.get("source") or "").lower() == "sg" and a_row.get("user_name"):
                preferred_name = a_row["user_name"]
                break
        if not preferred_name:
            preferred_name = group[0].get("user_name") or code

        for a_row in group:
            mapped.append(
                {
                    "a_user_id": a_row["user_id"],
                    "b_user_id": b_user_id,
                    "employee_code": code,
                    "action": action,
                    "a_source": a_row.get("source", ""),
                    "a_user_name": a_row.get("user_name", ""),
                    "create_user_name": preferred_name,
                    "note": note,
                }
            )

    return {"map": mapped, "conflict": conflicts, "manual": manual}


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write("# 同一员工编码的多行必须共用同一个 b_user_id。禁止按姓名合并。\n")
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("a_users", type=Path, help="A 导出 CSV")
    parser.add_argument("b_users", type=Path, help="B 导出 CSV")
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()
    out_dir = args.out_dir or args.a_users.parent

    result = propose(_read_users(args.a_users), _read_users(args.b_users))
    _write_csv(
        out_dir / "user-map.proposed.csv",
        [
            "a_user_id",
            "b_user_id",
            "employee_code",
            "action",
            "a_source",
            "a_user_name",
            "create_user_name",
            "note",
        ],
        result["map"],
    )
    _write_csv(
        out_dir / "conflicts.tsv",
        ["employee_code", "a_user_id", "a_user_name", "a_source", "reason"],
        result["conflict"],
    )
    _write_csv(
        out_dir / "manual.tsv",
        ["user_id", "user_name", "source", "external_id", "delete"],
        result["manual"],
    )
    print(
        f"proposed={len(result['map'])} conflicts={len(result['conflict'])} "
        f"manual={len(result['manual'])} -> {out_dir}"
    )
    print("复核签字后复制为 p4/user-map.csv 再跑 apply-takeover.sh (默认 APPLY=0)")


if __name__ == "__main__":
    main()
