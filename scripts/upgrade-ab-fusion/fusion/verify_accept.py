"""迁后验收: A 原空间元数据, 原会话仍在, 本批悬挂引用 SQL."""

from __future__ import annotations

from pathlib import Path

from fusion.sql import escape, load_table

SPACE_FIELDS = (
    "id",
    "name",
    "description",
    "user_id",
    "tenant_id",
    "update_time",
)


def _index_by_id(rows: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in rows:
        key = str(row.get("id") or "").strip()
        if key:
            out[key] = row
    return out


def compare_space_meta(base_rows: list[dict], now_rows: list[dict]) -> list[str]:
    """基线每一行必须仍在且字段一致. 多出来的行不报 (本批不应给 type=3 插行)."""
    errors: list[str] = []
    now = _index_by_id(now_rows)
    for src_id, old in _index_by_id(base_rows).items():
        new = now.get(src_id)
        if new is None:
            errors.append(f"A 空间 id={src_id} 消失")
            continue
        for field in SPACE_FIELDS:
            if field == "id":
                continue
            left = str(old.get(field) or "")
            right = str(new.get(field) or "")
            if left != right:
                errors.append(f"A 空间 id={src_id} {field} 从 {left!r} 变成 {right!r}")
    return errors


def missing_ids(pre: set[str], now: set[str]) -> list[str]:
    return sorted(x for x in pre if x and x not in now)


def ids_from_tsv(path: Path, key: str) -> set[str]:
    out: set[str] = set()
    for row in load_table(path):
        val = str(row.get(key) or next(iter(row.values()), "")).strip()
        if val:
            out.add(val)
    return out


def dangling_checks(batch: str | None = None) -> list[tuple[str, str]]:
    """返回 (名称, 应返回 0 的 COUNT SQL). 只扫 fusion_map 本批 dst."""
    extra = ""
    if batch:
        extra = f" AND m.batch_no='{escape(batch)}'"
    return [
        (
            "knowledge.user_id",
            "SELECT COUNT(*) FROM fusion_map m "
            "JOIN knowledge k ON k.id = CAST(m.dst_id AS UNSIGNED) "
            "LEFT JOIN `user` u ON u.user_id = k.user_id "
            f"WHERE m.entity='knowledge'{extra} AND u.user_id IS NULL",
        ),
        (
            "file.knowledge_id",
            "SELECT COUNT(*) FROM fusion_map m "
            "JOIN knowledgefile f ON f.id = CAST(m.dst_id AS UNSIGNED) "
            "LEFT JOIN knowledge k ON k.id = f.knowledge_id "
            f"WHERE m.entity='file'{extra} AND k.id IS NULL",
        ),
        (
            "flow.user_id",
            "SELECT COUNT(*) FROM fusion_map m "
            "JOIN flow f ON f.id = m.dst_id "
            "LEFT JOIN `user` u ON u.user_id = f.user_id "
            f"WHERE m.entity='flow'{extra} AND u.user_id IS NULL",
        ),
        (
            "session.user_id",
            "SELECT COUNT(*) FROM fusion_map m "
            "JOIN message_session s ON s.chat_id = m.dst_id "
            "LEFT JOIN `user` u ON u.user_id = s.user_id "
            f"WHERE m.entity='chat' AND m.action IN ('keep','new_id'){extra} "
            "AND u.user_id IS NULL",
        ),
        (
            "session.flow_id",
            "SELECT COUNT(*) FROM fusion_map m "
            "JOIN message_session s ON s.chat_id = m.dst_id "
            f"WHERE m.entity='chat' AND m.action IN ('keep','new_id'){extra} "
            "AND s.flow_id IS NOT NULL AND s.flow_id != '' "
            "AND NOT EXISTS (SELECT 1 FROM flow x WHERE x.id = s.flow_id) "
            "AND NOT EXISTS (SELECT 1 FROM assistant a WHERE a.id = s.flow_id)",
        ),
        (
            "message.chat_id",
            "SELECT COUNT(*) FROM fusion_map m "
            "JOIN chatmessage c ON c.id = CAST(m.dst_id AS UNSIGNED) "
            "LEFT JOIN message_session s ON s.chat_id = c.chat_id "
            f"WHERE m.entity='message'{extra} AND s.chat_id IS NULL",
        ),
    ]
