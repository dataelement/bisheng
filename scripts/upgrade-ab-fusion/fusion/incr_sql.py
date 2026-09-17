"""增量 SQL: 已映射行的 UPDATE / 删除清单 DELETE. 禁止碰 A 原空间."""

from __future__ import annotations

import json

from fusion.json_rewrite import rewrite_flow_data
from fusion.maps import require_mapped_model
from fusion.sql import sql_int, sql_json, sql_str
from fusion.vector_names import target_collection_name, target_index_name


def maps_for_deleted(
    *,
    deleted: list[dict],
    maps: dict[str, dict[str, str]],
) -> dict[str, list[tuple[str, str]]]:
    """deleted 行 entity+src_id -> fusion_map 风格."""
    out: dict[str, list[tuple[str, str]]] = {}
    for row in deleted:
        entity = (row.get("entity") or "").strip()
        src = (row.get("src_id") or "").strip()
        table = maps.get(entity) or {}
        dst = table.get(src)
        if not entity or not src or not dst:
            continue
        out.setdefault(entity, []).append((src, dst))
    return out


def generate_incr_delete_sql(
    *,
    batch: str,
    deleted: list[dict],
    maps: dict[str, dict[str, str]],
    a_space_ids: set[int],
) -> str:
    """只删映射到的 dst, 并去掉对应 fusion_map 行. 不把整批标成 rolled_back."""
    subset = maps_for_deleted(deleted=deleted, maps=maps)
    if not any(subset.values()):
        return f"-- incr delete batch {batch}: empty\n"
    lines = [
        "SET NAMES utf8mb4;",
        f"-- incr delete batch {batch}",
        "START TRANSACTION;",
    ]

    def dsts(entity: str) -> list[str]:
        return [d for _, d in subset.get(entity) or [] if d]

    def srcs(entity: str) -> list[str]:
        return [s for s, d in subset.get(entity) or [] if s and d]

    def delete_int(entity: str, table: str, col: str = "id") -> None:
        ids = dsts(entity)
        if ids:
            lines.append(
                f"DELETE FROM {table} WHERE {col} IN ({','.join(sql_int(i) for i in ids)});"
            )

    delete_int("review_tag_link", "review_tag_link")
    delete_int("review_tag", "review_tag")
    delete_int("qa", "qaknowledge")
    delete_int("group_resource", "groupresource")
    delete_int("role_access", "roleaccess")
    delete_int("report", "t_report")
    audit_ids = dsts("audit")
    if audit_ids:
        lines.append(
            "DELETE FROM auditlog WHERE id IN ("
            + ",".join(sql_str(i) for i in audit_ids)
            + ");"
        )
    msg = dsts("message")
    if msg:
        lines.append(
            "DELETE FROM chatmessage WHERE id IN ("
            + ",".join(sql_int(i) for i in msg)
            + ");"
        )
    chats = dsts("chat")
    if chats:
        lines.append(
            "DELETE FROM message_session WHERE chat_id IN ("
            + ",".join(sql_str(i) for i in chats)
            + ");"
        )
    for entity, table in (
        ("assistant", "assistant"),
        ("flowversion", "flowversion"),
        ("flow", "flow"),
        ("file", "knowledgefile"),
    ):
        ids = dsts(entity)
        if not ids:
            continue
        if entity in {"assistant", "flow"}:
            joined = ",".join(sql_str(i) for i in ids)
            if entity == "assistant":
                lines.append(
                    f"DELETE FROM assistantlink WHERE assistant_id IN ({joined});"
                )
            lines.append(f"DELETE FROM {table} WHERE id IN ({joined});")
        else:
            joined = ",".join(
                sql_int(i) if str(i).isdigit() else sql_str(i) for i in ids
            )
            lines.append(f"DELETE FROM {table} WHERE id IN ({joined});")
    k_ids = []
    for _, dst in subset.get("knowledge") or []:
        if int(dst) in a_space_ids:
            raise ValueError(f"增量删除命中 A 原空间 {dst}")
        k_ids.append(dst)
    if k_ids:
        lines.append(
            "DELETE FROM knowledge WHERE id IN ("
            + ",".join(sql_int(i) for i in k_ids)
            + ") AND type IN (0,1);"
        )
    for entity in subset:
        s = srcs(entity)
        if not s:
            continue
        joined = ",".join(sql_str(i) for i in s)
        lines.append(
            "DELETE FROM fusion_map WHERE batch_no="
            f"{sql_str(batch)} AND entity={sql_str(entity)} AND src_id IN ({joined});"
        )
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n"


def generate_incr_update_sql(
    *,
    batch: str,
    knowledges: list[dict],
    files: list[dict],
    flows: list[dict],
    assistants: list[dict],
    maps: dict[str, dict[str, str]],
    updated: set[tuple[str, str]],
    a_space_ids: set[int],
    a_tenant_default: str,
) -> str:
    """只 UPDATE 本批映射到的 B 新建资源. 工作流/助手 status 仍留给 publish."""
    lines = [
        "SET NAMES utf8mb4;",
        f"-- incr update batch {batch}",
        "START TRANSACTION;",
    ]
    kmap = maps.get("knowledge") or {}
    fmap = maps.get("file") or {}
    flow_map = maps.get("flow") or {}
    amap = maps.get("assistant") or {}
    model_map = maps.get("model") or {}
    user_map = maps.get("user") or {}
    tenant_map = maps.get("tenant") or {}

    for k in knowledges:
        src = str(k.get("id") or "")
        if ("knowledge", src) not in updated:
            continue
        dst = kmap.get(src)
        if not dst:
            continue
        if int(dst) in a_space_ids:
            raise ValueError(f"增量 UPDATE 命中 A 原空间 knowledge id={dst}")
        model = ""
        if k.get("model"):
            model = require_mapped_model(
                "incr knowledge", src, str(k.get("model") or ""), model_map
            )
        lines.append(
            "UPDATE knowledge SET name="
            f"{sql_str(k.get('name') or '')}, description={sql_str(k.get('description') or None)}, "
            f"model={sql_str(model or None)}, state={sql_int(k.get('state') or 1, '1')} "
            f"WHERE id={sql_int(dst)} AND type IN (0,1);"
        )

    for f in files:
        src = str(f.get("id") or "")
        if ("file", src) not in updated:
            continue
        dst = fmap.get(src)
        dst_kid = kmap.get(str(f.get("knowledge_id") or ""))
        if not dst or not dst_kid:
            continue
        if int(dst_kid) in a_space_ids:
            raise ValueError(f"增量 UPDATE 文件所属库是 A 空间 file={dst}")
        tenant = tenant_map.get(str(f.get("tenant_id") or "1"), a_tenant_default)
        lines.append(
            "UPDATE knowledgefile SET alias_name="
            f"{sql_str(f.get('alias_name') or None)}, status={sql_int(f.get('status') or 2, '2')}, "
            f"user_metadata={sql_json(f.get('user_metadata'))}, remark={sql_str(f.get('remark') or None)}, "
            f"tenant_id={sql_int(tenant)} WHERE id={sql_int(dst)};"
        )

    for fl in flows:
        src = str(fl.get("id") or "")
        if ("flow", src) not in updated:
            continue
        dst = flow_map.get(src)
        if not dst:
            continue
        data = fl.get("data")
        if isinstance(data, str):
            data = json.loads(data) if data else {}
        rewritten, report = rewrite_flow_data(data or {}, maps)
        if report.missing:
            raise ValueError(f"incr flow {src} 嵌套引用未映射: {report.missing[:8]}")
        lines.append(
            "UPDATE flow SET name="
            f"{sql_str(fl.get('name') or '')}, description={sql_str(fl.get('description') or None)}, "
            f"data={sql_json(rewritten)} WHERE id={sql_str(dst)};"
        )

    for a in assistants:
        src = str(a.get("id") or "")
        if ("assistant", src) not in updated:
            continue
        dst = amap.get(src)
        if not dst:
            continue
        model = ""
        if a.get("model_name"):
            model = require_mapped_model(
                "incr assistant", src, str(a.get("model_name") or ""), model_map
            )
        owner = user_map.get(str(a.get("user_id") or ""))
        lines.append(
            "UPDATE assistant SET name="
            f"{sql_str(a.get('name') or '')}, `desc`={sql_str(a.get('desc') or '')}, "
            f"system_prompt={sql_str(a.get('system_prompt') or '')}, "
            f"prompt={sql_str(a.get('prompt') or '')}, model_name={sql_str(model)}, "
            f"user_id={sql_int(owner)} WHERE id={sql_str(dst)};"
        )

    assert_update_skips_spaces("\n".join(lines), a_space_ids)
    lines.append("COMMIT;")
    if len(lines) == 4:
        return f"-- incr update batch {batch}: empty\n"
    return "\n".join(lines) + "\n"


def assert_update_skips_spaces(sql: str, a_space_ids: set[int]) -> None:
    for line in sql.splitlines():
        if not line.startswith("UPDATE knowledge SET"):
            continue
        if "type IN (0,1)" not in line:
            raise ValueError("增量 UPDATE knowledge 必须限制 type IN (0,1)")
        compact = line.replace(" ", "").lower()
        for sid in a_space_ids:
            if f"whereid={sid}" in compact or f"whereid={sid}and" in compact:
                raise ValueError(f"增量 UPDATE knowledge 命中 A 原空间 {sid}")


def store_names_for_updated_knowledge(
    knowledges: list[dict], knowledge_map: dict[str, str], updated: set[tuple[str, str]]
) -> list[dict]:
    """更新过的库若改了解析产物, 向量任务仍走 b{src}_ 名, 不覆盖 A."""
    out = []
    for k in knowledges:
        src = str(k.get("id") or "")
        if ("knowledge", src) not in updated:
            continue
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
