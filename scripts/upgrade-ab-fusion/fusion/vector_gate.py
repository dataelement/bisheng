"""方案 8.3 兼容门禁. 不连库. 不自动重解析."""

from __future__ import annotations

from typing import Any

from fusion.vector_names import target_collection_name, target_index_name

COPY = "copy"
CONVERT = "convert"
SKIP = "skip"
EXCEPTION = "exception"
PENDING = "pending"

NEED_REPARSE = "need_reparse"

IDENTITY_FIELDS = ("file_id", "document_id")
VECTOR_FIELDS = ("vector", "embedding")
TEXT_FIELDS = ("text", "page_content")
SPACE_HINT_FIELDS = frozenset({"knowledge_ids"})


def parse_dim(config: Any) -> int | None:
    if isinstance(config, str) and config.strip():
        import json

        try:
            config = json.loads(config)
        except json.JSONDecodeError:
            return None
    if not isinstance(config, dict):
        return None
    for key in ("dimensions", "dimension", "dim", "embedding_size", "vector_dim"):
        raw = config.get(key)
        if raw in (None, ""):
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            continue
    return None


def field_map(schema: dict | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for field in (schema or {}).get("fields") or []:
        name = str(field.get("name") or "")
        if name:
            out[name] = field
    return out


def field_types(schema: dict | None) -> dict[str, str]:
    return {name: str(f.get("dtype") or "") for name, f in field_map(schema).items()}


def vector_dim(schema: dict | None) -> int | None:
    for name in VECTOR_FIELDS:
        field = field_map(schema).get(name)
        if not field:
            continue
        params = field.get("params") or {}
        dim = params.get("dim") or field.get("dim")
        if dim not in (None, ""):
            return int(dim)
    return None


def has_any(schema: dict | None, names: tuple[str, ...]) -> bool:
    fields = field_map(schema)
    return any(n in fields for n in names)


def es_has_text(mapping: dict | None) -> bool:
    props = ((mapping or {}).get("mappings") or {}).get("properties") or mapping or {}
    if not isinstance(props, dict):
        return False
    if "text" in props or "page_content" in props:
        return True
    inner = props.get("properties") if isinstance(props.get("properties"), dict) else {}
    return "text" in inner


def milvus_expr(schema: dict | None, src_id: str) -> str:
    fields = field_map(schema)
    if "knowledge_id" not in fields:
        return ""
    dtype = str(fields["knowledge_id"].get("dtype") or "")
    if "VARCHAR" in dtype.upper() or "STRING" in dtype.upper():
        return f'knowledge_id == "{src_id}"'
    return f"knowledge_id == {src_id}"


def refuse_a_space_store(name: str, space_names: set[str]) -> None:
    if name and name in space_names:
        raise ValueError(f"拒绝写入 A 原空间存储 {name}")


def gate_knowledge(
    *,
    src_id: str,
    dst_id: str,
    ktype: int,
    b_collection: str,
    b_index: str,
    b_model: str,
    a_model: str | None,
    b_schema: dict | None,
    b_es: dict | None,
    a_collections: set[str],
    a_indices: set[str],
    a_space_collections: set[str],
    a_space_indices: set[str],
    b_model_dim: int | None,
    a_model_dim: int | None,
    described: bool,
) -> dict:
    """按知识库给出 copy/convert/exception. exception 默认 need_reparse, 不自动解析."""
    a_coll = target_collection_name(src_id, b_collection, dst_id)
    a_idx = target_index_name(src_id, b_index, dst_id)
    conversions: list[str] = ["drop_pk", "new_es_ids"]
    reasons: list[str] = []

    base = {
        "b_id": src_id,
        "a_id": dst_id,
        "type": str(ktype),
        "b_collection": b_collection,
        "a_collection": a_coll,
        "b_index": b_index or b_collection,
        "a_index": a_idx,
        "b_model": b_model,
        "a_model": a_model or "",
        "expr": "",
        "conversions": conversions,
        "disposition": "",
    }

    if ktype not in (0, 1):
        return {
            **base,
            "verdict": EXCEPTION,
            "reason": f"type={ktype} 不在传统库范围",
            "disposition": NEED_REPARSE,
        }
    if not (b_collection or "").strip():
        return {
            **base,
            "verdict": EXCEPTION,
            "reason": "collection_name 为空",
            "disposition": NEED_REPARSE,
        }

    try:
        refuse_a_space_store(a_coll, a_space_collections)
        refuse_a_space_store(a_idx, a_space_indices)
        refuse_a_space_store(b_collection, a_space_collections)
        refuse_a_space_store(b_index, a_space_indices)
    except ValueError as exc:
        return {
            **base,
            "verdict": EXCEPTION,
            "reason": str(exc),
            "disposition": NEED_REPARSE,
        }

    if a_coll in a_space_collections or a_idx in a_space_indices:
        hit = a_coll if a_coll in a_space_collections else a_idx
        return {
            **base,
            "verdict": EXCEPTION,
            "reason": f"目标与 A 原空间存储冲突: {hit}",
            "disposition": NEED_REPARSE,
        }

    if not a_model:
        return {
            **base,
            "verdict": EXCEPTION,
            "reason": f"Embedding 模型 {b_model} 未 bind, 禁止直接拷向量",
            "disposition": NEED_REPARSE,
        }

    if not described:
        return {
            **base,
            "verdict": PENDING,
            "reason": "未拿到 B/A Milvus ES 描述, APPLY=0 可继续; APPLY=1 须先 describe",
        }

    if not b_schema:
        return {
            **base,
            "verdict": EXCEPTION,
            "reason": f"B Collection 不存在或无法描述: {b_collection}",
            "disposition": NEED_REPARSE,
        }

    if SPACE_HINT_FIELDS & set(field_map(b_schema)):
        return {
            **base,
            "verdict": EXCEPTION,
            "reason": "Schema 含 knowledge_ids, 疑似空间共享存储, 拒绝",
            "disposition": NEED_REPARSE,
        }

    if not has_any(b_schema, VECTOR_FIELDS):
        return {
            **base,
            "verdict": EXCEPTION,
            "reason": "Milvus 无 vector/embedding 字段",
            "disposition": NEED_REPARSE,
        }
    if not has_any(b_schema, TEXT_FIELDS):
        reasons.append("无 text 字段, 仅迁向量侧")
        conversions.append("milvus_only_no_text")
    if not has_any(b_schema, IDENTITY_FIELDS):
        return {
            **base,
            "verdict": EXCEPTION,
            "reason": "Chunk 无 file_id/document_id, 无法确定性重写",
            "disposition": NEED_REPARSE,
        }

    dim = vector_dim(b_schema)
    if dim is None:
        return {
            **base,
            "verdict": EXCEPTION,
            "reason": "无法读取向量维度",
            "disposition": NEED_REPARSE,
        }
    if b_model_dim is not None and b_model_dim != dim:
        return {
            **base,
            "verdict": EXCEPTION,
            "reason": f"B 模型维度 {b_model_dim} 与 Collection dim {dim} 不一致",
            "disposition": NEED_REPARSE,
        }
    if a_model_dim is not None and a_model_dim != dim:
        return {
            **base,
            "verdict": EXCEPTION,
            "reason": f"A 绑定模型维度 {a_model_dim} 与 B 向量 dim {dim} 不兼容",
            "disposition": NEED_REPARSE,
        }

    expr = milvus_expr(b_schema, src_id)
    if expr:
        conversions.append("knowledge_id_filter")
    if (b_collection or "").startswith("partition_"):
        conversions.append("partition_to_dedicated")

    indexes = b_schema.get("indexes") or []
    for idx in indexes:
        itype = str(idx.get("index_type") or idx.get("indexType") or "")
        if itype and itype.upper() not in {
            "HNSW",
            "FLAT",
            "IVF_FLAT",
            "IVF_SQ8",
            "AUTOINDEX",
            "",
        }:
            conversions.append("index_fallback_hnsw")
            break

    es_ok = True
    if b_es is None:
        es_ok = False
        reasons.append("B ES Index 不存在或无法描述")
    elif not es_has_text(b_es):
        conversions.append("es_mapping_passthrough")
        reasons.append("ES mapping 无标准 text, 尝试原样拷 _source")

    if not es_ok:
        return {
            **base,
            "expr": expr,
            "verdict": EXCEPTION,
            "reason": "; ".join(reasons) or "ES 不可用",
            "disposition": NEED_REPARSE,
            "conversions": conversions,
        }

    verdict = CONVERT if conversions else COPY
    # drop_pk / new_es_ids 是默认转换, 单独不算不兼容
    extra = [c for c in conversions if c not in {"drop_pk", "new_es_ids"}]
    verdict = CONVERT if extra else COPY
    reason = "兼容, 保留向量/正文并重写 ID"
    if extra:
        reason = "可转换: " + ",".join(extra)
    if reasons:
        reason = reason + "; " + "; ".join(reasons)
    if a_coll in a_collections or a_idx in a_indices:
        return {
            **base,
            "expr": expr,
            "verdict": SKIP,
            "reason": f"目标已存在, 视为本批已写入, 续跑跳过: {a_coll}",
            "conversions": conversions + ["already_on_a"],
        }
    return {
        **base,
        "expr": expr,
        "verdict": verdict,
        "reason": reason,
        "conversions": conversions,
    }
