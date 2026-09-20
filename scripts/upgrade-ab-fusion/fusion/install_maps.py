"""无冲突时把 proposed 写成 p4 正式对照表, 免手工 cp."""

from __future__ import annotations

import shutil
from pathlib import Path

from fusion.sql import load_csv, load_table, write_csv

PROPOSED_PAIRS = (
    ("user-map.proposed.csv", "user-map.csv"),
    ("dept-map.proposed.csv", "dept-map.csv"),
    ("role-map.proposed.csv", "role-map.csv"),
    ("model-map.proposed.csv", "model-map.csv"),
    ("server-map.proposed.csv", "server-map.csv"),
    ("tool-map.proposed.csv", "tool-map.csv"),
)


def conflict_stems(log_p4: Path) -> list[str]:
    """冲突 csv 只要有数据行就阻断安装."""
    hits: list[str] = []
    for path in sorted(log_p4.glob("*.conflicts.csv")):
        if load_csv(path):
            hits.append(path.name)
    return hits


def write_tenant_map(pack: Path, log_p4: Path) -> str:
    """单租户 1:1, 或多租户按 tenant_code bind; 对不上则拷 example."""
    dest = pack / "p4" / "tenant-map.csv"
    b_rows = load_table(log_p4 / "b-tenants.tsv")
    a_rows = load_table(log_p4 / "a-tenants.tsv")
    if len(b_rows) == 1 and len(a_rows) == 1:
        write_csv(
            dest,
            ["b_tenant_id", "a_tenant_id", "action", "note"],
            [
                {
                    "b_tenant_id": str(b_rows[0].get("id") or "1"),
                    "a_tenant_id": str(a_rows[0].get("id") or "1"),
                    "action": "bind",
                    "note": "单租户 1:1",
                }
            ],
        )
        return "tenant-map.csv"
    a_by_code = {
        (row.get("tenant_code") or "").strip(): row for row in a_rows if (row.get("tenant_code") or "").strip()
    }
    mapped: list[dict[str, str]] = []
    unmatched = False
    for row in b_rows:
        code = (row.get("tenant_code") or "").strip()
        hit = a_by_code.get(code)
        if not hit:
            unmatched = True
            break
        mapped.append(
            {
                "b_tenant_id": str(row.get("id") or ""),
                "a_tenant_id": str(hit.get("id") or ""),
                "action": "bind",
                "note": f"tenant_code={code}",
            }
        )
    if mapped and not unmatched:
        write_csv(
            dest,
            ["b_tenant_id", "a_tenant_id", "action", "note"],
            mapped,
        )
        return "tenant-map.csv"
    example = pack / "p4" / "tenant-map.csv.example"
    if example.exists():
        shutil.copy(example, dest)
        return "tenant-map.csv"
    raise ValueError("无法自动写 tenant-map.csv, 请按 p4/tenant-map.csv.example 填写")


def install_official_maps(pack: Path, log_p4: Path) -> list[str]:
    """把无冲突的 proposed 安装到 pack/p4. 有冲突则退出 2."""
    hits = conflict_stems(log_p4)
    if hits:
        raise ValueError("有冲突, 未写入 p4 正式对照表: " + ", ".join(hits))
    written: list[str] = []
    dest_dir = pack / "p4"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for src_name, dst_name in PROPOSED_PAIRS:
        src = log_p4 / src_name
        if not src.exists():
            continue
        shutil.copy(src, dest_dir / dst_name)
        written.append(dst_name)
    written.append(write_tenant_map(pack, log_p4))
    group_dest = dest_dir / "group-map.csv"
    group_example = dest_dir / "group-map.csv.example"
    if not group_dest.exists() and group_example.exists():
        shutil.copy(group_example, group_dest)
        written.append("group-map.csv")
    return written
