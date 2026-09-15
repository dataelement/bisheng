#!/usr/bin/env python3
"""从 dump + maps + describe 快照生成 vector-jobs / exceptions. 不连 Milvus/ES."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACK))

from fusion.maps import load_map
from fusion.sql import load_jsonl, load_table
from fusion.vector_jobs import (
    build_vector_jobs,
    model_dims,
    store_set,
    write_vector_outputs,
)


def _describe(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dump", required=True)
    p.add_argument("--maps", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--batch", default="fusion")
    p.add_argument("--b-describe", default="")
    p.add_argument("--a-describe", default="")
    p.add_argument("--a-space-stores", default="")
    p.add_argument("--a-knowledge-stores", default="")
    p.add_argument("--b-models", default="")
    p.add_argument("--a-models", default="")
    p.add_argument("--described", action="store_true")
    args = p.parse_args()

    dump = json.loads(Path(args.dump).read_text(encoding="utf-8"))
    map_dir = Path(args.maps)
    knowledge_map = load_map(map_dir / "knowledge-map.csv", "b_id", "a_id")
    model_map = load_map(map_dir / "model-map.csv", "b_model_id", "a_model_id")

    b_desc = _describe(Path(args.b_describe)) if args.b_describe else None
    a_desc = _describe(Path(args.a_describe)) if args.a_describe else {}
    if a_desc is None:
        a_desc = {}

    space_rows = load_table(Path(args.a_space_stores)) if args.a_space_stores else []
    all_rows = (
        load_table(Path(args.a_knowledge_stores)) if args.a_knowledge_stores else []
    )
    b_models = load_jsonl(Path(args.b_models)) if args.b_models else []
    a_models = load_jsonl(Path(args.a_models)) if args.a_models else []

    jobs, exceptions = build_vector_jobs(
        batch=args.batch,
        knowledges=dump.get("knowledges") or [],
        knowledge_map=knowledge_map,
        model_map=model_map,
        b_describe=b_desc,
        a_describe=a_desc,
        a_space_collections=store_set(space_rows, "collection_name"),
        a_space_indices=store_set(space_rows, "index_name"),
        a_existing_collections=store_set(all_rows, "collection_name"),
        a_existing_indices=store_set(all_rows, "index_name"),
        b_model_dims=model_dims(b_models),
        a_model_dims=model_dims(a_models),
        described=bool(args.described or b_desc),
    )
    out = Path(args.out_dir)
    write_vector_outputs(out, args.batch, jobs, exceptions)
    print(f"jobs={len(jobs)} exceptions={len(exceptions)} -> {out / 'vector-jobs.tsv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
