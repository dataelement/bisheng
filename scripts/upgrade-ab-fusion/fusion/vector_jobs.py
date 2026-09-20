"""从映射和 describe 快照生成 Milvus/ES 任务与例外清单."""

from __future__ import annotations

from pathlib import Path

from fusion.sql import sql_str, write_csv
from fusion.vector_gate import (
    CONVERT,
    COPY,
    NEED_REPARSE,
    PENDING,
    SKIP,
    gate_knowledge,
    parse_dim,
    refuse_a_space_store,
)
from fusion.vector_names import target_collection_name, target_index_name

JOB_FIELDS = [
    "b_id",
    "a_id",
    "type",
    "verdict",
    "b_collection",
    "a_collection",
    "b_index",
    "a_index",
    "expr",
    "conversions",
    "reason",
]
EXC_FIELDS = [
    "kind",
    "src_entity",
    "src_id",
    "a_id",
    "verdict",
    "disposition",
    "reason",
    "a_collection",
    "a_index",
]


def model_dims(rows: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        dim = parse_dim(row.get("config"))
        mid = str(row.get("id") or "")
        if mid and dim is not None:
            out[mid] = dim
    return out


def store_set(rows: list[dict], key: str) -> set[str]:
    out: set[str] = set()
    for row in rows:
        name = (row.get(key) or "").strip()
        if name:
            out.add(name)
    return out


def _schema_for(describe: dict | None, name: str, kind: str) -> dict | None:
    if not describe:
        return None
    bucket = describe.get("collections" if kind == "milvus" else "indices") or {}
    return bucket.get(name)


def build_vector_jobs(
    *,
    batch: str,
    knowledges: list[dict],
    knowledge_map: dict[str, str],
    model_map: dict[str, str],
    b_describe: dict | None,
    a_describe: dict | None,
    a_space_collections: set[str],
    a_space_indices: set[str],
    a_existing_collections: set[str],
    a_existing_indices: set[str],
    b_model_dims: dict[str, int],
    a_model_dims: dict[str, int],
    migrate_b_spaces: bool = False,
    described: bool = False,
) -> tuple[list[dict], list[dict]]:
    described = described or bool(b_describe)
    a_cols = set(a_existing_collections)
    a_idxs = set(a_existing_indices)
    if a_describe:
        a_cols |= set((a_describe.get("collections") or {}).keys())
        a_idxs |= set((a_describe.get("indices") or {}).keys())

    jobs: list[dict] = []
    exceptions: list[dict] = []
    for k in knowledges:
        src = str(k.get("id") or "")
        ktype = int(k.get("type") or 0)
        if ktype == 3 and not migrate_b_spaces:
            continue
        dst = knowledge_map.get(src)
        if not dst:
            continue
        b_coll = (k.get("collection_name") or "").strip()
        b_idx = (k.get("index_name") or "").strip() or b_coll
        b_model = str(k.get("model") or "")
        a_model = model_map.get(b_model) if b_model else ""
        result = gate_knowledge(
            src_id=src,
            dst_id=dst,
            ktype=ktype,
            b_collection=b_coll,
            b_index=b_idx,
            b_model=b_model,
            a_model=a_model or None,
            b_schema=_schema_for(b_describe, b_coll, "milvus"),
            b_es=_schema_for(b_describe, b_idx, "es")
            or _schema_for(b_describe, b_coll, "es"),
            a_collections=a_cols,
            a_indices=a_idxs,
            a_space_collections=a_space_collections,
            a_space_indices=a_space_indices,
            b_model_dim=b_model_dims.get(b_model),
            a_model_dim=a_model_dims.get(a_model or ""),
            described=described,
        )
        conv = result.get("conversions") or []
        row = {
            "b_id": src,
            "a_id": dst,
            "type": str(ktype),
            "verdict": result["verdict"],
            "b_collection": result["b_collection"],
            "a_collection": result["a_collection"],
            "b_index": result["b_index"],
            "a_index": result["a_index"],
            "expr": result.get("expr") or "",
            "conversions": ",".join(conv),
            "reason": result.get("reason") or "",
        }
        if result["verdict"] in {COPY, CONVERT, SKIP}:
            refuse_a_space_store(row["a_collection"], a_space_collections)
            refuse_a_space_store(row["a_index"], a_space_indices)
            jobs.append(row)
        else:
            exceptions.append(
                {
                    "kind": "vector_incompatible",
                    "src_entity": "knowledge",
                    "src_id": src,
                    "a_id": dst,
                    "verdict": result["verdict"],
                    "disposition": result.get("disposition") or NEED_REPARSE,
                    "reason": result.get("reason") or "",
                    "a_collection": result["a_collection"],
                    "a_index": result["a_index"],
                    "batch_no": batch,
                }
            )
    return jobs, exceptions


def write_vector_outputs(
    out_dir: Path, batch: str, jobs: list[dict], exceptions: list[dict]
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(out_dir / "vector-jobs.tsv", JOB_FIELDS, jobs, delimiter="\t")
    write_csv(out_dir / "vector-exceptions.tsv", EXC_FIELDS, exceptions, delimiter="\t")
    (out_dir / "vector-exceptions.sql").write_text(
        generate_exception_sql(batch, exceptions), encoding="utf-8"
    )


def generate_exception_sql(batch: str, rows: list[dict]) -> str:
    lines = [
        "SET NAMES utf8mb4;",
        f"-- fusion_exception vector gate batch {batch}",
    ]
    for row in rows:
        if row.get("verdict") == PENDING:
            continue
        detail = (row.get("reason") or "")[:2000]
        lines.append(
            "INSERT INTO fusion_exception (batch_no, kind, src_entity, src_id, detail) VALUES ("
            f"{sql_str(batch)}, {sql_str(row.get('kind') or 'vector_incompatible')}, "
            f"{sql_str(row.get('src_entity') or 'knowledge')}, {sql_str(row.get('src_id'))}, "
            f"{sql_str(detail)});"
        )
    if len(lines) == 2:
        lines.append("-- no exceptions")
    return "\n".join(lines) + "\n"


def job_targets_from_maps(
    knowledges: list[dict], knowledge_map: dict[str, str]
) -> list[dict]:
    """无 describe 时仍能算出目标名, 供保护核对."""
    out = []
    for k in knowledges:
        src = str(k.get("id") or "")
        dst = knowledge_map.get(src)
        if not dst:
            continue
        out.append(
            {
                "b_id": src,
                "a_id": dst,
                "a_collection": target_collection_name(
                    src, k.get("collection_name"), dst
                ),
                "a_index": target_index_name(src, k.get("index_name"), dst),
            }
        )
    return out
