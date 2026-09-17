#!/usr/bin/env python3
"""按水位 diff + dump 生成增量 DELETE/UPDATE SQL."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACK))

from fusion.incr_sql import generate_incr_delete_sql, generate_incr_update_sql
from fusion.maps import load_map
from fusion.sql import load_table


def _maps(map_dir: Path) -> dict[str, dict[str, str]]:
    return {
        "user": load_map(map_dir / "user-map.csv", "b_user_id", "a_user_id"),
        "tenant": load_map(map_dir / "tenant-map.csv", "b_tenant_id", "a_tenant_id"),
        "model": load_map(map_dir / "model-map.csv", "b_model_id", "a_model_id"),
        "tool": load_map(map_dir / "tool-map.csv", "b_tool_id", "a_tool_id"),
        "knowledge": load_map(map_dir / "knowledge-map.csv", "b_id", "a_id"),
        "file": load_map(map_dir / "file-map.csv", "b_id", "a_id"),
        "flow": load_map(map_dir / "flow-map.csv", "b_id", "a_id"),
        "flowversion": load_map(map_dir / "flowversion-map.csv", "b_id", "a_id"),
        "assistant": load_map(map_dir / "assistant-map.csv", "b_id", "a_id"),
        "chat": load_map(map_dir / "chat-map.csv", "b_id", "a_id"),
        "message": load_map(map_dir / "message-map.csv", "b_id", "a_id"),
        "qa": load_map(map_dir / "qa-map.csv", "b_id", "a_id"),
        "review_tag": load_map(map_dir / "tag-map.csv", "b_id", "a_id"),
        "review_tag_link": load_map(map_dir / "tag-link-map.csv", "b_id", "a_id"),
        "group_resource": load_map(map_dir / "group-resource-map.csv", "b_id", "a_id"),
        "report": load_map(map_dir / "report-map.csv", "b_id", "a_id"),
        "role_access": load_map(map_dir / "role-access-map.csv", "b_id", "a_id"),
        "audit": load_map(map_dir / "audit-map.csv", "b_id", "a_id"),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dump", required=True)
    p.add_argument("--maps", required=True)
    p.add_argument(
        "--diff", required=True, help="含 incr-deleted.tsv / incr-updated.tsv"
    )
    p.add_argument("--out-dir", required=True)
    p.add_argument("--batch", default="fusion")
    args = p.parse_args()
    dump = json.loads(Path(args.dump).read_text(encoding="utf-8"))
    maps = _maps(Path(args.maps))
    a_space_ids = set(dump.get("a_space_ids") or [])
    tenant_default = next(iter(maps["tenant"].values()), "1")
    deleted = load_table(Path(args.diff) / "incr-deleted.tsv")
    updated_rows = load_table(Path(args.diff) / "incr-updated.tsv")
    updated = {
        ((row.get("entity") or "").strip(), (row.get("src_id") or "").strip())
        for row in updated_rows
        if row.get("entity") and row.get("src_id")
    }
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    delete_sql = generate_incr_delete_sql(
        batch=args.batch,
        deleted=deleted,
        maps=maps,
        a_space_ids=a_space_ids,
    )
    update_sql = generate_incr_update_sql(
        batch=args.batch,
        knowledges=dump.get("knowledges") or [],
        files=dump.get("files") or [],
        flows=dump.get("flows") or [],
        assistants=dump.get("assistants") or [],
        maps=maps,
        updated=updated,
        a_space_ids=a_space_ids,
        a_tenant_default=tenant_default,
    )
    (out_dir / "incr-delete.sql").write_text(delete_sql, encoding="utf-8")
    (out_dir / "incr-update.sql").write_text(update_sql, encoding="utf-8")
    print(out_dir / "incr-delete.sql")
    print(out_dir / "incr-update.sql")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
