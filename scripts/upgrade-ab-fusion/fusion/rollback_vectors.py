"""回滚要删的 Milvus Collection / ES Index 名单. 不连库.

vector-created.tsv 只记本轮真正 import 成功的名字. skip(already_on_a) 的旧向量
不在清单里, 回滚会漏删. 本模块合并:

- A 上本批 knowledge.collection_name / index_name (删表前快照)
- vector-jobs 的 a_collection / a_index (含 skip)
- 仍保留 vector-created.tsv
- knowledge-map + B 库原名按同一套 b{src}_ 规则还原

A 原空间名走 forbid, 不会进删除名单.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PACK = Path(__file__).resolve().parent.parent
if str(PACK) not in sys.path:
    sys.path.insert(0, str(PACK))

from fusion.maps import SKIP_ROLLBACK_ACTIONS
from fusion.sql import load_table, write_csv
from fusion.vector_names import target_collection_name, target_index_name

FIELDS = ["kind", "name", "b_id", "source"]
JOB_VERDICTS = frozenset({"copy", "convert", "skip"})


def _add(
    rows: list[dict[str, str]],
    seen: set[tuple[str, str]],
    *,
    kind: str,
    name: str,
    b_id: str = "",
    source: str = "",
    forbid: set[str],
) -> None:
    text = (name or "").strip()
    if not text or text in forbid:
        return
    key = (kind, text)
    if key in seen:
        return
    seen.add(key)
    rows.append({"kind": kind, "name": text, "b_id": b_id, "source": source})


def collect_rollback_vector_stores(
    *,
    knowledge_stores: list[dict] | None = None,
    vector_jobs: list[dict] | None = None,
    vector_created: list[dict] | None = None,
    knowledge_maps: list[dict] | None = None,
    b_knowledges: list[dict] | None = None,
    forbid: set[str] | None = None,
) -> list[dict[str, str]]:
    """去重后的删除名单. kind 为 milvus 或 es."""
    blocked = {x.strip() for x in (forbid or set()) if str(x).strip()}
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for row in knowledge_stores or []:
        kid = str(row.get("id") or row.get("a_id") or "").strip()
        _add(
            out,
            seen,
            kind="milvus",
            name=str(row.get("collection_name") or ""),
            b_id=kid,
            source="knowledge_snapshot",
            forbid=blocked,
        )
        _add(
            out,
            seen,
            kind="es",
            name=str(row.get("index_name") or ""),
            b_id=kid,
            source="knowledge_snapshot",
            forbid=blocked,
        )

    for row in vector_jobs or []:
        if (row.get("verdict") or "").strip() not in JOB_VERDICTS:
            continue
        b_id = str(row.get("b_id") or "").strip()
        _add(
            out,
            seen,
            kind="milvus",
            name=str(row.get("a_collection") or ""),
            b_id=b_id,
            source="vector_jobs",
            forbid=blocked,
        )
        _add(
            out,
            seen,
            kind="es",
            name=str(row.get("a_index") or ""),
            b_id=b_id,
            source="vector_jobs",
            forbid=blocked,
        )

    for row in vector_created or []:
        kind = (row.get("kind") or "").strip()
        if kind not in {"milvus", "es"}:
            continue
        _add(
            out,
            seen,
            kind=kind,
            name=str(row.get("name") or ""),
            b_id=str(row.get("b_id") or ""),
            source="vector_created",
            forbid=blocked,
        )

    b_by_id = {
        str(k.get("id") or "").strip(): k
        for k in (b_knowledges or [])
        if str(k.get("id") or "").strip()
    }
    for row in knowledge_maps or []:
        action = (row.get("action") or "create").strip()
        if action in SKIP_ROLLBACK_ACTIONS:
            continue
        src = str(row.get("b_id") or "").strip()
        dst = str(row.get("a_id") or "").strip()
        if not src:
            continue
        mapped_coll = (row.get("a_collection") or "").strip()
        mapped_idx = (row.get("a_index") or "").strip()
        b_row = b_by_id.get(src) or {}
        b_coll = (row.get("b_collection") or b_row.get("collection_name") or "").strip()
        b_idx = (row.get("b_index") or b_row.get("index_name") or "").strip()
        milvus_name = mapped_coll or (
            target_collection_name(src, b_coll, dst) if b_coll else ""
        )
        es_name = mapped_idx or (target_index_name(src, b_idx, dst) if b_idx else "")
        _add(
            out,
            seen,
            kind="milvus",
            name=milvus_name,
            b_id=src,
            source="reconstruct",
            forbid=blocked,
        )
        _add(
            out,
            seen,
            kind="es",
            name=es_name,
            b_id=src,
            source="reconstruct",
            forbid=blocked,
        )

    return out


def write_rollback_vector_stores(path: Path, rows: list[dict[str, str]]) -> None:
    write_csv(path, FIELDS, rows, delimiter="\t")


def _load_optional(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.exists():
        return []
    return load_table(path)


def _forbid_from(path: Path | None) -> set[str]:
    if path is None or not path.exists():
        return set()
    return {
        ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--knowledge-stores", default="")
    p.add_argument("--vector-jobs", default="")
    p.add_argument("--vector-created", default="")
    p.add_argument("--knowledge-map", default="")
    p.add_argument("--b-knowledge", default="")
    p.add_argument("--forbid", default="")
    args = p.parse_args()
    rows = collect_rollback_vector_stores(
        knowledge_stores=_load_optional(
            Path(args.knowledge_stores) if args.knowledge_stores else None
        ),
        vector_jobs=_load_optional(
            Path(args.vector_jobs) if args.vector_jobs else None
        ),
        vector_created=_load_optional(
            Path(args.vector_created) if args.vector_created else None
        ),
        knowledge_maps=_load_optional(
            Path(args.knowledge_map) if args.knowledge_map else None
        ),
        b_knowledges=_load_optional(
            Path(args.b_knowledge) if args.b_knowledge else None
        ),
        forbid=_forbid_from(Path(args.forbid) if args.forbid else None),
    )
    write_rollback_vector_stores(Path(args.out), rows)
    print(f"rollback vector stores={len(rows)} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
