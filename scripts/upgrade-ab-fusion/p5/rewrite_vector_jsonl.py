#!/usr/bin/env python3
"""把 B 导出的 chunk jsonl 按映射重写后给 A 导入. 纯转换, 不连库."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACK))

from fusion.maps import load_map
from fusion.vector_gate import field_types
from fusion.vector_rewrite import rewrite_entity


def _iter_jsonl(path: Path):
    with path.open(encoding="utf-8") as f:
        for ln in f:
            text = ln.strip()
            if text:
                yield json.loads(text)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--src", required=True)
    p.add_argument("--dst", required=True)
    p.add_argument("--maps", required=True)
    p.add_argument("--schema", default="")
    args = p.parse_args()
    map_dir = Path(args.maps)
    file_map = load_map(map_dir / "file-map.csv", "b_id", "a_id")
    knowledge_map = load_map(map_dir / "knowledge-map.csv", "b_id", "a_id")
    tenant_map = load_map(map_dir / "tenant-map.csv", "b_tenant_id", "a_tenant_id")
    types = {}
    if args.schema:
        schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
        types = field_types(schema)
    out = Path(args.dst)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out.open("w", encoding="utf-8") as f:
        for row in _iter_jsonl(Path(args.src)):
            new = rewrite_entity(
                row,
                file_map=file_map,
                knowledge_map=knowledge_map,
                tenant_map=tenant_map,
                field_types=types,
            )
            f.write(json.dumps(new, ensure_ascii=False) + "\n")
            n += 1
    print(f"rewritten={n} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
