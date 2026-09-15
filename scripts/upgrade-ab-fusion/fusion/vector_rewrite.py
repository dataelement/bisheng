"""Chunk 元数据重写: 保留向量/正文, 只换 ID 和对象路径. 不重新 Embedding."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

from fusion.minio_keys import PATH_KEYS, extract_object_key, rewrite_object_key

FILE_ID_KEYS = frozenset({"file_id", "document_id"})
KNOWLEDGE_ID_KEYS = frozenset({"knowledge_id"})
TENANT_ID_KEYS = frozenset({"tenant_id"})
DROP_KEYS = frozenset({"pk", "_id", "id"})
TEXT_KEYS = frozenset({"text", "page_content", "content"})
PATH_TOKEN_RE = re.compile(r"(?:original|preview|bbox|thumbnails|knowledge/images/files)/[0-9A-Za-z._-]+")


def is_int_dtype(dtype: str | None) -> bool:
    text = (dtype or "").upper()
    return "INT" in text and "SPRINT" not in text


def coerce_id(value: Any, dtype: str | None, original: Any = None) -> Any:
    if value is None or value == "":
        return value
    if is_int_dtype(dtype):
        return int(value)
    if dtype:
        return str(value)
    if isinstance(original, int):
        return int(value)
    if original is not None:
        return str(value)
    return value


def lookup(table: dict[str, str], value: Any) -> str | None:
    if value is None or value == "":
        return None
    return table.get(str(value))


def rewrite_path_text(text: str, src_file_id: str, dst_file_id: str) -> str:
    """只改对象路径里的文件 ID, 不替换正文里的普通数字."""
    if not text or not src_file_id or src_file_id == dst_file_id:
        return text

    def repl(match: re.Match[str]) -> str:
        token = match.group(0)
        if f"/{src_file_id}" not in token and not token.endswith(f"/{src_file_id}"):
            if f"/{src_file_id}." not in token:
                return token
        dst = rewrite_object_key(token, dst_file_id)
        return dst or token

    return PATH_TOKEN_RE.sub(repl, text)


def _rewrite_json_node(
    node: Any,
    *,
    file_map: dict[str, str],
    knowledge_map: dict[str, str],
    tenant_map: dict[str, str],
    src_file_id: str,
    dst_file_id: str,
    parent_key: str = "",
) -> Any:
    if isinstance(node, dict):
        return {
            k: _rewrite_json_node(
                v,
                file_map=file_map,
                knowledge_map=knowledge_map,
                tenant_map=tenant_map,
                src_file_id=src_file_id,
                dst_file_id=dst_file_id,
                parent_key=k,
            )
            for k, v in node.items()
        }
    if isinstance(node, list):
        return [
            _rewrite_json_node(
                item,
                file_map=file_map,
                knowledge_map=knowledge_map,
                tenant_map=tenant_map,
                src_file_id=src_file_id,
                dst_file_id=dst_file_id,
                parent_key=parent_key,
            )
            for item in node
        ]
    if parent_key in FILE_ID_KEYS:
        hit = lookup(file_map, node)
        return int(hit) if hit and str(hit).isdigit() else (hit if hit else node)
    if parent_key in KNOWLEDGE_ID_KEYS:
        hit = lookup(knowledge_map, node)
        if hit is None:
            return node
        return int(hit) if str(node).isdigit() and str(hit).isdigit() else hit
    if parent_key in TENANT_ID_KEYS:
        hit = lookup(tenant_map, node)
        if hit is None:
            return node
        return int(hit) if str(hit).isdigit() else hit
    if isinstance(node, str) and parent_key in PATH_KEYS:
        src = extract_object_key(node)
        if src:
            return rewrite_object_key(src, dst_file_id) or node
        return rewrite_path_text(node, src_file_id, dst_file_id)
    if isinstance(node, str):
        return rewrite_path_text(node, src_file_id, dst_file_id)
    return node


def rewrite_blob(
    value: Any,
    *,
    file_map: dict[str, str],
    knowledge_map: dict[str, str],
    tenant_map: dict[str, str],
    src_file_id: str,
    dst_file_id: str,
) -> Any:
    """重写 extra/bbox 一类 JSON 或字符串."""
    if value is None or value == "":
        return value
    if isinstance(value, (dict, list)):
        return _rewrite_json_node(
            value,
            file_map=file_map,
            knowledge_map=knowledge_map,
            tenant_map=tenant_map,
            src_file_id=src_file_id,
            dst_file_id=dst_file_id,
        )
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, (dict, list)):
                new = _rewrite_json_node(
                    parsed,
                    file_map=file_map,
                    knowledge_map=knowledge_map,
                    tenant_map=tenant_map,
                    src_file_id=src_file_id,
                    dst_file_id=dst_file_id,
                )
                return json.dumps(new, ensure_ascii=False, separators=(",", ":"))
        return rewrite_path_text(value, src_file_id, dst_file_id)
    return value


def identity_file_id(entity: dict) -> str:
    meta = entity.get("metadata") if isinstance(entity.get("metadata"), dict) else {}
    for key in ("file_id", "document_id"):
        for src in (entity, meta):
            val = src.get(key)
            if val not in (None, ""):
                return str(val)
    return ""


def rewrite_entity(
    entity: dict,
    *,
    file_map: dict[str, str],
    knowledge_map: dict[str, str],
    tenant_map: dict[str, str],
    field_types: dict[str, str] | None = None,
) -> dict:
    """返回可写入 A 的实体. 缺 file 映射则抛错, 由门禁决定整库进例外."""
    types = field_types or {}
    out = deepcopy(entity)
    for key in list(out):
        if key in DROP_KEYS:
            out.pop(key, None)

    src_fid = identity_file_id(out)
    dst_fid = lookup(file_map, src_fid) if src_fid else None
    if src_fid and dst_fid is None:
        raise ValueError(f"file_id {src_fid} 未映射")

    def apply_map(obj: dict, nested: bool) -> None:
        prefix = "metadata." if nested else ""
        if "file_id" in obj and obj.get("file_id") not in (None, ""):
            original = obj.get("file_id")
            hit = lookup(file_map, original)
            if hit is None:
                raise ValueError(f"file_id {original} 未映射")
            dtype = types.get(prefix + "file_id") or types.get("file_id")
            obj["file_id"] = coerce_id(hit, dtype, original)
        if "document_id" in obj and obj.get("document_id") not in (None, ""):
            original = obj.get("document_id")
            hit = lookup(file_map, original)
            if hit is None:
                raise ValueError(f"document_id {original} 未映射")
            dtype = types.get(prefix + "document_id") or types.get("document_id")
            obj["document_id"] = coerce_id(hit, dtype, original)
        if "knowledge_id" in obj and obj.get("knowledge_id") not in (None, ""):
            original = obj.get("knowledge_id")
            hit = lookup(knowledge_map, original)
            if hit is None:
                raise ValueError(f"knowledge_id {original} 未映射")
            dtype = types.get(prefix + "knowledge_id") or types.get("knowledge_id")
            obj["knowledge_id"] = coerce_id(hit, dtype, original)
        if "tenant_id" in obj and obj.get("tenant_id") not in (None, ""):
            original = obj.get("tenant_id")
            hit = lookup(tenant_map, original)
            if hit:
                dtype = types.get(prefix + "tenant_id") or types.get("tenant_id")
                obj["tenant_id"] = coerce_id(hit, dtype, original)
        for blob_key in ("extra", "bbox", "source", "user_metadata"):
            if blob_key in obj:
                obj[blob_key] = rewrite_blob(
                    obj.get(blob_key),
                    file_map=file_map,
                    knowledge_map=knowledge_map,
                    tenant_map=tenant_map,
                    src_file_id=src_fid,
                    dst_file_id=dst_fid or src_fid,
                )
        for text_key in TEXT_KEYS:
            if isinstance(obj.get(text_key), str) and dst_fid:
                obj[text_key] = rewrite_path_text(obj[text_key], src_fid, dst_fid)

    apply_map(out, nested=False)
    if isinstance(out.get("metadata"), dict):
        apply_map(out["metadata"], nested=True)
        if dst_fid:
            for text_key in TEXT_KEYS:
                if isinstance(out["metadata"].get(text_key), str):
                    out["metadata"][text_key] = rewrite_path_text(out["metadata"][text_key], src_fid, dst_fid)
    return out


def rewrite_entities(
    rows: list[dict],
    *,
    file_map: dict[str, str],
    knowledge_map: dict[str, str],
    tenant_map: dict[str, str],
    field_types: dict[str, str] | None = None,
) -> list[dict]:
    return [
        rewrite_entity(
            row,
            file_map=file_map,
            knowledge_map=knowledge_map,
            tenant_map=tenant_map,
            field_types=field_types,
        )
        for row in rows
    ]
