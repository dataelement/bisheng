#!/usr/bin/env python3
"""把 A 空间绑定的标签库写到 B: 公共库按名 bind 并并入缺的标签, 私有库新发号。"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession


def _as_tags(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()]
    if isinstance(value, str):
        text_value = value.strip()
        if not text_value:
            return []
        try:
            parsed = json.loads(text_value)
        except json.JSONDecodeError:
            return [text_value]
        if isinstance(parsed, list):
            return [str(x) for x in parsed if str(x).strip()]
    return []


async def apply_tags(
    session: AsyncSession,
    *,
    export: dict,
    b_space_id: int,
    owner_b: int,
    batch_no: str,
    user_map: dict[int, int],
) -> dict[str, Any]:
    """写入标签库和 knowledge_tag_library_link。返回 tag_map_rows 与例外。"""
    exceptions: list[dict] = []
    tag_map_rows: list[dict] = []
    a_space_id = int(export["space"]["id"])
    libraries = list(export.get("tag_libraries") or [])
    links = list(export.get("tag_links") or [])
    id_map: dict[int, int] = {}

    for lib in libraries:
        a_id = int(lib["id"])
        name = (lib.get("name") or f"tag-{a_id}").strip()
        tags = _as_tags(lib.get("tags"))
        owner_a = lib.get("owner_knowledge_id")
        user_id = user_map.get(int(lib["user_id"])) if lib.get("user_id") else owner_b
        if not user_id:
            user_id = owner_b
        is_builtin = 1 if str(lib.get("is_builtin")) in {"1", "true", "True"} else 0
        if owner_a and int(owner_a) != a_space_id:
            exceptions.append(
                {
                    "kind": "tag_unmapped",
                    "a_space_id": a_space_id,
                    "detail": f"标签库 {a_id} 的私有归属空间 {owner_a} 不是当前空间, 跳过",
                }
            )
            continue
        if owner_a is None or owner_a == "":
            found = (
                await session.execute(
                    text(
                        "SELECT id, tags FROM knowledge_space_tag_library "
                        "WHERE owner_knowledge_id IS NULL AND name=:n "
                        "ORDER BY id LIMIT 1"
                    ),
                    {"n": name},
                )
            ).first()
            if found:
                b_id = int(found[0])
                existing = _as_tags(found[1])
                merged = list(dict.fromkeys(existing + tags))
                if merged != existing:
                    await session.execute(
                        text(
                            "UPDATE knowledge_space_tag_library "
                            "SET tags=:t, tag_count=:c WHERE id=:i"
                        ),
                        {
                            "t": json.dumps(merged, ensure_ascii=False),
                            "c": len(merged),
                            "i": b_id,
                        },
                    )
                id_map[a_id] = b_id
                tag_map_rows.append(
                    {"a_tag_id": a_id, "b_tag_id": b_id, "action": "bind", "name": name}
                )
                continue
            await session.execute(
                text(
                    "INSERT INTO knowledge_space_tag_library "
                    "(tenant_id, name, description, tags, tag_count, ai_tags, ai_tag_count, "
                    "is_builtin, owner_knowledge_id, user_id) "
                    "VALUES (1,:n,:d,:t,:c,'[]',0,:b,NULL,:u)"
                ),
                {
                    "n": name[:200],
                    "d": (lib.get("description") or "")[:1000] or None,
                    "t": json.dumps(tags, ensure_ascii=False),
                    "c": len(tags),
                    "b": is_builtin,
                    "u": user_id,
                },
            )
            b_id = int(
                (await session.execute(text("SELECT LAST_INSERT_ID()"))).scalar() or 0
            )
            id_map[a_id] = b_id
            tag_map_rows.append(
                {"a_tag_id": a_id, "b_tag_id": b_id, "action": "create", "name": name}
            )
            continue

        await session.execute(
            text(
                "INSERT INTO knowledge_space_tag_library "
                "(tenant_id, name, description, tags, tag_count, ai_tags, ai_tag_count, "
                "is_builtin, owner_knowledge_id, user_id) "
                "VALUES (1,:n,:d,:t,:c,'[]',0,0,:s,:u)"
            ),
            {
                "n": name[:200],
                "d": (lib.get("description") or "")[:1000] or None,
                "t": json.dumps(tags, ensure_ascii=False),
                "c": len(tags),
                "s": b_space_id,
                "u": user_id,
            },
        )
        b_id = int(
            (await session.execute(text("SELECT LAST_INSERT_ID()"))).scalar() or 0
        )
        id_map[a_id] = b_id
        tag_map_rows.append(
            {
                "a_tag_id": a_id,
                "b_tag_id": b_id,
                "action": "create_private",
                "name": name,
            }
        )

    for link in links:
        a_lib = int(link["tag_library_id"])
        b_lib = id_map.get(a_lib)
        if not b_lib:
            exceptions.append(
                {
                    "kind": "tag_unmapped",
                    "a_space_id": a_space_id,
                    "detail": f"空间标签链接 tag_library_id={a_lib} 映不上",
                }
            )
            continue
        await session.execute(
            text(
                "INSERT INTO knowledge_tag_library_link "
                "(tenant_id, knowledge_id, tag_library_id, sort_order) "
                "SELECT 1,:s,:t,:o FROM DUAL WHERE NOT EXISTS ("
                "SELECT 1 FROM knowledge_tag_library_link "
                "WHERE knowledge_id=:s AND tag_library_id=:t)"
            ),
            {"s": b_space_id, "t": b_lib, "o": int(link.get("sort_order") or 0)},
        )

    for row in tag_map_rows:
        await session.execute(
            text(
                "INSERT INTO fusion_tag_map "
                "(batch_no,a_tag_id,b_tag_id,action,name) VALUES "
                "(:b,:a,:s,:act,:n) ON DUPLICATE KEY UPDATE "
                "b_tag_id=VALUES(b_tag_id), action=VALUES(action)"
            ),
            {
                "b": batch_no,
                "a": row["a_tag_id"],
                "s": row["b_tag_id"],
                "act": row["action"],
                "n": (row.get("name") or "")[:200],
            },
        )
    return {"tag_map_rows": tag_map_rows, "exceptions": exceptions}
