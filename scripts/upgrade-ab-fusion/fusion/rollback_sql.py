"""按 fusion_map 生成批次回滚 SQL. 禁止删除 A 原 type=3 空间."""

from __future__ import annotations

from fusion.sql import sql_int, sql_str


def generate_rollback_sql(
    *,
    batch: str,
    maps: dict[str, list[tuple[str, str]]],
    a_space_ids: set[int],
) -> str:
    lines = [
        "SET NAMES utf8mb4;",
        f"-- rollback batch {batch}; only delete dest rows created by this batch",
        "START TRANSACTION;",
    ]

    def dsts(entity: str) -> list[str]:
        return [d for _, d in maps.get(entity) or [] if d]

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
    delete_int("dictionary", "system_dictionary")
    delete_int("citation_relation", "message_citation_relation")
    delete_int("citation", "message_citation")
    delete_int("mark_app_user", "markappuser")
    delete_int("mark_record", "markrecord")
    delete_int("mark_task", "marktask")
    delete_int("report", "t_report")
    delete_int("tool_type", "t_gpts_tools_type")
    delete_int("role_access", "roleaccess")

    audit_ids = dsts("audit")
    if audit_ids:
        lines.append(
            "DELETE FROM auditlog WHERE id IN ("
            + ",".join(sql_str(i) for i in audit_ids)
            + ");"
        )

    msg_ids = dsts("message")
    if msg_ids:
        ids = ",".join(sql_int(i) for i in msg_ids)
        lines.append(f"DELETE FROM chatmessage WHERE id IN ({ids});")

    chat_ids = dsts("chat")
    # 调用方不得传入 dedupe 行. keep 的 src==dst 也是本批 INSERT, 要删.
    if chat_ids:
        ids = ",".join(sql_str(i) for i in chat_ids)
        lines.append(f"DELETE FROM message_session WHERE chat_id IN ({ids});")

    for entity, table, col in (
        ("share_link", "share_link", "id"),
        ("assistant", "assistantlink", "assistant_id"),
        ("assistant", "assistant", "id"),
        ("flowversion", "flowversion", "id"),
        ("flow", "flow", "id"),
        ("file", "knowledgefile", "id"),
    ):
        ids = dsts(entity)
        if not ids:
            continue
        if col in {"id"} and table in {"flowversion", "knowledgefile"}:
            joined = ",".join(
                sql_int(i) if str(i).isdigit() else sql_str(i) for i in ids
            )
        elif table in {"assistant", "flow", "share_link", "assistantlink"}:
            joined = ",".join(sql_str(i) for i in ids)
        else:
            joined = ",".join(sql_str(i) for i in ids)
        lines.append(f"DELETE FROM {table} WHERE {col} IN ({joined});")

    k_ids = []
    for _, dst in maps.get("knowledge") or []:
        if dst and int(dst) not in a_space_ids:
            k_ids.append(dst)
        elif dst and int(dst) in a_space_ids:
            raise ValueError(f"回滚映射命中 A 原空间 {dst}, 拒绝生成 DELETE")
    if k_ids:
        lines.append(
            "DELETE FROM knowledge WHERE id IN ("
            + ",".join(sql_int(i) for i in k_ids)
            + ");"
        )

    for entity, table, col in (
        ("role", "userrole", "role_id"),
        ("role", "role", "id"),
        ("group", "usergroup", "group_id"),
        ("group", "group", "id"),
        ("user", "user_tenant", "user_id"),
    ):
        ids = dsts(entity)
        if not ids:
            continue
        # 只删 create 出来的用户: 调用方应只传入 action=create 的 user dst
        joined = ",".join(sql_int(i) for i in ids)
        lines.append(f"DELETE FROM {table} WHERE {col} IN ({joined});")

    create_users = dsts("user_create") or dsts("user") or []
    if create_users:
        joined = ",".join(sql_int(i) for i in create_users)
        lines.append(f"DELETE FROM user_department WHERE user_id IN ({joined});")
        lines.append(f"DELETE FROM usergroup WHERE user_id IN ({joined});")
        lines.append(f"DELETE FROM userrole WHERE user_id IN ({joined});")
        lines.append(f"DELETE FROM user_tenant WHERE user_id IN ({joined});")
        lines.append(f"DELETE FROM `user` WHERE user_id IN ({joined});")

    lines.append(f"DELETE FROM fusion_map WHERE batch_no={sql_str(batch)};")
    lines.append(
        f"UPDATE fusion_batch SET status='rolled_back' WHERE batch_no={sql_str(batch)};"
    )
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n"
