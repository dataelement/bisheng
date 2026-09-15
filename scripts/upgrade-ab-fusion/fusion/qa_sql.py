"""QA 问答对: 只迁已映射传统库 (type=0/1) 下的 qaknowledge. 不碰 A 原空间."""

from __future__ import annotations

from fusion.sql import alloc_int_id, fusion_batch_open_sql, sql_int, sql_json, sql_str


def generate_qa_sql(
    *,
    batch: str,
    qas: list[dict],
    knowledge_map: dict[str, str],
    user_map: dict[str, str],
    tenant_map: dict[str, str],
    a_existing_ids: set[int],
    next_qa_id: int,
    a_tenant_default: str,
    existing_qa: dict[str, str] | None = None,
) -> tuple[str, list[dict]]:
    """返回 (sql, qa_maps). knowledge 未映射则跳过该问答对."""
    lines = [
        "SET NAMES utf8mb4;",
        f"-- batch {batch} qaknowledge B->A",
        "START TRANSACTION;",
        fusion_batch_open_sql(batch, "qa"),
    ]
    taken = set(a_existing_ids)
    nxt = next_qa_id
    maps: list[dict] = []
    skipped = 0
    existing_qa = dict(existing_qa or {})
    for dst in existing_qa.values():
        try:
            taken.add(int(dst))
        except ValueError:
            pass
    for row in qas:
        src = str(row.get("id") or "")
        src_kid = str(row.get("knowledge_id") or "")
        dst_kid = knowledge_map.get(src_kid)
        if src in existing_qa:
            maps.append(
                {
                    "b_id": src,
                    "a_id": existing_qa[src],
                    "knowledge_id": dst_kid or "",
                }
            )
            continue
        if not dst_kid:
            skipped += 1
            continue
        owner = user_map.get(str(row.get("user_id") or ""))
        if not owner:
            raise ValueError(f"qaknowledge {src} 用户 {row.get('user_id')} 未映射")
        tenant = tenant_map.get(str(row.get("tenant_id") or "1"), a_tenant_default)
        dst = alloc_int_id(nxt, taken)
        nxt = dst + 1
        questions = row.get("questions")
        answers = row.get("answers")
        extra = row.get("extra_meta")
        lines.append(
            "INSERT INTO qaknowledge (id, user_id, knowledge_id, questions, answers, source, "
            "status, extra_meta, remark, tenant_id) VALUES ("
            f"{dst}, {sql_int(owner)}, {sql_int(dst_kid)}, {sql_json(questions)}, "
            f"{sql_json(answers) if isinstance(answers, (list, dict)) else sql_str(answers)}, "
            f"{sql_int(row.get('source') or 0, '0')}, {sql_int(row.get('status') or 1, '1')}, "
            f"{sql_json(extra) if isinstance(extra, (list, dict)) else sql_str(extra)}, "
            f"{sql_str(row.get('remark') or None)}, {sql_int(tenant)});"
        )
        lines.append(
            "INSERT INTO fusion_map (batch_no, entity, src_id, dst_id, action, note) VALUES ("
            f"{sql_str(batch)}, 'qa', {sql_str(src)}, {sql_str(str(dst))}, 'create', "
            f"{sql_str(f'knowledge {src_kid}->{dst_kid}')});"
        )
        maps.append({"b_id": src, "a_id": str(dst), "knowledge_id": dst_kid})
    lines.append(f"-- skipped={skipped}")
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n", maps
