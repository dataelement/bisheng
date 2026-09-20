"""消息引用: 重写 message/chat/flow, citation_id 一律换新, 避免撞 A 唯一键."""

from __future__ import annotations

import json
import uuid

from fusion.json_rewrite import rewrite_tree
from fusion.sql import alloc_int_id, fusion_batch_open_sql, sql_int, sql_json, sql_str


def _parse_payload(raw):
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str) and raw.strip().startswith(("{", "[")):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


def generate_citation_sql(
    *,
    batch: str,
    citations: list[dict],
    relations: list[dict],
    maps: dict[str, dict[str, str]],
    a_citation_ids: set[str],
    a_citation_pks: set[int],
    a_relation_ids: set[int],
    next_citation_id: int,
    next_relation_id: int,
    a_tenant_default: str,
) -> tuple[str, list[dict], list[dict]]:
    """返回 (sql, citation_maps, relation_maps). 消息未映射则跳过."""
    lines = [
        "SET NAMES utf8mb4;",
        f"-- batch {batch} message_citation B->A",
        "START TRANSACTION;",
        fusion_batch_open_sql(batch, "citation"),
    ]
    msg_map = maps.get("message") or {}
    chat_map = maps.get("chat") or {}
    flow_map = maps.get("flow") or {}
    asst_map = maps.get("assistant") or {}
    tenant_map = maps.get("tenant") or {}
    taken_pk = set(a_citation_pks)
    taken_cid = set(a_citation_ids)
    taken_rel = set(a_relation_ids)
    nxt = next_citation_id
    rel_nxt = next_relation_id
    cit_alloc: dict[str, str] = dict(maps.get("citation") or {})
    preexisting_cit = dict(cit_alloc)
    preexisting_rel = dict(maps.get("citation_relation") or {})
    cit_maps: list[dict] = []
    rel_maps: list[dict] = []
    skipped = 0

    for row in citations:
        src = str(row.get("id") or "")
        if src in preexisting_cit:
            dst_pk = preexisting_cit[src]
            cit_alloc[src] = dst_pk
            old_cid = str(row.get("citation_id") or "")
            if old_cid:
                cit_alloc[old_cid] = dst_pk
            cit_maps.append({"b_id": src, "a_id": dst_pk})
            continue
        src_msg = str(row.get("message_id") or "")
        dst_msg = msg_map.get(src_msg)
        if not dst_msg:
            skipped += 1
            continue
        dst_pk = alloc_int_id(nxt, taken_pk)
        nxt = dst_pk + 1
        cid = uuid.uuid4().hex
        while cid in taken_cid:
            cid = uuid.uuid4().hex
        taken_cid.add(cid)
        if src:
            cit_alloc[src] = cid
        old_cid = str(row.get("citation_id") or "")
        if old_cid:
            cit_alloc[old_cid] = cid
        chat_src = str(row.get("chat_id") or "")
        chat_dst = chat_map.get(chat_src) if chat_src else None
        flow_src = str(row.get("flow_id") or "")
        flow_dst = (
            flow_map.get(flow_src) or asst_map.get(flow_src) or "" if flow_src else ""
        )
        payload = _parse_payload(row.get("source_payload"))
        if isinstance(payload, (dict, list)):
            payload_new, report = rewrite_tree(payload, maps)
            if report.missing:
                lines.append(
                    f"-- WARN citation {src} payload missing {report.missing[:6]}"
                )
        else:
            payload_new = payload
        lines.append(
            "INSERT INTO message_citation (id, citation_id, message_id, chat_id, flow_id, "
            "citation_type, source_payload) VALUES ("
            f"{dst_pk}, {sql_str(cid)}, {sql_int(dst_msg)}, {sql_str(chat_dst)}, "
            f"{sql_str(flow_dst or None)}, {sql_str(row.get('citation_type') or 'file')}, "
            f"{sql_json(payload_new) if isinstance(payload_new, (dict, list)) else sql_json({})});"
        )
        lines.append(
            "INSERT INTO fusion_map (batch_no, entity, src_id, dst_id, action, note) VALUES ("
            f"{sql_str(batch)}, 'citation', {sql_str(src or old_cid)}, {sql_str(str(dst_pk))}, "
            f"'create', {sql_str(cid)});"
        )
        cit_maps.append(
            {
                "b_id": src or old_cid,
                "a_id": str(dst_pk),
                "citation_id": cid,
                "message_id": dst_msg,
            }
        )

    for row in relations:
        src = str(row.get("id") or "")
        if src in preexisting_rel:
            rel_maps.append({"b_id": src, "a_id": preexisting_rel[src]})
            continue
        src_msg = str(row.get("message_id") or "")
        dst_msg = msg_map.get(src_msg)
        src_cid = str(row.get("citation_id") or "")
        dst_cid = cit_alloc.get(src_cid)
        if not dst_msg or not dst_cid:
            skipped += 1
            continue
        dst = alloc_int_id(rel_nxt, taken_rel)
        rel_nxt = dst + 1
        tenant = tenant_map.get(str(row.get("tenant_id") or "1"), a_tenant_default)
        lines.append(
            "INSERT INTO message_citation_relation (id, tenant_id, message_id, citation_id) VALUES ("
            f"{dst}, {sql_int(tenant)}, {sql_int(dst_msg)}, {sql_str(dst_cid)});"
        )
        lines.append(
            "INSERT INTO fusion_map (batch_no, entity, src_id, dst_id, action, note) VALUES ("
            f"{sql_str(batch)}, 'citation_relation', {sql_str(src)}, {sql_str(str(dst))}, "
            f"'create', {sql_str(dst_cid)});"
        )
        rel_maps.append({"b_id": src, "a_id": str(dst)})

    lines.append(f"-- skipped={skipped}")
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n", cit_maps, rel_maps
