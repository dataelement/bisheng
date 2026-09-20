"""Milvus Collection / ES Index 目标名. 与 knowledge SQL 必须同一套规则."""

from __future__ import annotations


def prefixed_store_name(src_id: str, raw: str | None, fallback: str) -> str:
    """B 原名加 b{src}_ 前缀, 避免覆盖 A. 已带 b 前缀则不再加."""
    name = (raw or "").strip() or fallback
    if name.startswith("b"):
        return name
    return f"b{src_id}_{name}"


def target_collection_name(src_id: str, raw: str | None, dst_id: str) -> str:
    return prefixed_store_name(src_id, raw, f"col_{dst_id}")


def target_index_name(src_id: str, raw: str | None, dst_id: str) -> str:
    return prefixed_store_name(src_id, raw, f"idx_{dst_id}")
