"""会话和消息. A 原会话不修改; B chat_id 冲突则换新 id."""

from __future__ import annotations

import json
import uuid

from fusion.json_rewrite import rewrite_tree
from fusion.minio_keys import rewrite_stored_value
from fusion.sql import fusion_batch_open_sql, sql_bool, sql_int, sql_json, sql_str


def pick_chat_id(src: str, a_existing: set[str], same_content: bool) -> tuple[str, str]:
    if src not in a_existing:
        return src, "keep"
    if same_content:
        return src, "dedupe"
    return uuid.uuid4().hex, "new_id"


def generate_session_sql(
    *,
    batch: str,
    sessions: list[dict],
    messages: list[dict],
    maps: dict[str, dict[str, str]],
    a_chat_ids: set[str],
    a_session_digest: dict[str, str],
    next_message_id: int,
    a_tenant_default: str,
    a_existing_message_ids: set[int] | None = None,
) -> tuple[str, list[dict], list[dict], list[dict]]:
    """返回 (sql, session_maps, message_maps, group_id 例外). 未映射组从 group_ids 去掉并记例外."""
    lines = [
        "SET NAMES utf8mb4;",
        f"-- batch {batch} session B->A",
        "START TRANSACTION;",
        fusion_batch_open_sql(batch, "session"),
    ]
    chat_alloc: dict[str, str] = dict(maps.get("chat") or {})
    preexisting_chat = dict(maps.get("chat") or {})
    preexisting_msg = dict(maps.get("message") or {})
    session_maps: list[dict] = []
    group_exceptions: list[dict] = []
    existing = set(a_chat_ids)
    mid = next_message_id
    taken_msg: set[int] = set(a_existing_message_ids or [])
    for dst in preexisting_msg.values():
        try:
            taken_msg.add(int(dst))
        except ValueError:
            pass

    for s in sessions:
        src = str(s.get("chat_id") or "")
        if src in preexisting_chat:
            dst = preexisting_chat[src]
            chat_alloc[src] = dst
            session_maps.append(
                {"b_id": src, "a_id": dst, "action": "keep", "extra_jobs": []}
            )
            continue
        digest = s.get("digest") or ""
        same = bool(
            src in a_session_digest and a_session_digest[src] == digest and digest
        )
        dst, action = pick_chat_id(src, existing, same)
        if action == "dedupe":
            chat_alloc[src] = src
            session_maps.append({"b_id": src, "a_id": src, "action": "dedupe"})
            lines.append(
                "INSERT INTO fusion_map (batch_no, entity, src_id, dst_id, action, note) VALUES ("
                f"{sql_str(batch)}, 'chat', {sql_str(src)}, {sql_str(src)}, 'dedupe', '同源去重');"
            )
            continue
        existing.add(dst)
        chat_alloc[src] = dst
        owner = (maps.get("user") or {}).get(str(s.get("user_id") or ""))
        if not owner:
            raise ValueError(f"session {src} 用户未映射")
        tenant = (maps.get("tenant") or {}).get(
            str(s.get("tenant_id") or "1"), a_tenant_default
        )
        flow_id = str(s.get("flow_id") or "")
        flow_dst = (
            (maps.get("flow") or {}).get(flow_id)
            or (maps.get("assistant") or {}).get(flow_id)
            or flow_id
        )
        if (
            flow_id
            and flow_id not in (maps.get("flow") or {})
            and flow_id not in (maps.get("assistant") or {})
        ):
            # 无对应应用: 保留快照, flow_id 置空串, 名称仍用 B 的 flow_name
            flow_dst = ""
        group_ids = s.get("group_ids") or []
        if isinstance(group_ids, str):
            group_ids = json.loads(group_ids) if group_ids else []
        rewritten_groups = []
        dropped_groups: list[str] = []
        for g in group_ids:
            if g in (None, "", 0, "0"):
                continue
            mapped = (maps.get("group") or {}).get(str(g))
            if mapped:
                rewritten_groups.append(int(mapped))
            else:
                dropped_groups.append(str(g))
        if dropped_groups:
            group_exceptions.append(
                {
                    "chat_id": src,
                    "dropped_group_ids": ",".join(dropped_groups),
                    "reason": "用户组未映射, 已从 group_ids 去掉",
                }
            )
            lines.append(
                f"-- EXCEPT session {src} dropped group_ids {','.join(dropped_groups)}"
            )
        logo_new, logo_jobs = rewrite_stored_value(
            s.get("flow_logo"), dst, ref=src, kind="flow_logo"
        )
        logo_sql = (
            sql_json(logo_new)
            if isinstance(logo_new, (dict, list))
            else sql_str(logo_new or None)
        )
        lines.append(
            "INSERT INTO message_session (chat_id, name, flow_id, flow_type, flow_name, flow_description, "
            "flow_logo, user_id, tenant_id, group_ids, is_delete, `like`, dislike, copied, sensitive_status) VALUES ("
            f"{sql_str(dst)}, {sql_str(s.get('name') or '')}, {sql_str(flow_dst)}, "
            f"{sql_int(s.get('flow_type') or 10, '10')}, {sql_str(s.get('flow_name') or '')}, "
            f"{sql_str(s.get('flow_description') or None)}, {logo_sql}, "
            f"{sql_int(owner)}, {sql_int(tenant)}, {sql_json(rewritten_groups)}, "
            f"{sql_bool(s.get('is_delete'))}, {sql_int(s.get('like') or 0, '0')}, "
            f"{sql_int(s.get('dislike') or 0, '0')}, {sql_int(s.get('copied') or 0, '0')}, "
            f"{sql_int(s.get('sensitive_status') or 1, '1')});"
        )
        lines.append(
            "INSERT INTO fusion_map (batch_no, entity, src_id, dst_id, action, note) VALUES ("
            f"{sql_str(batch)}, 'chat', {sql_str(src)}, {sql_str(dst)}, {sql_str(action)}, NULL);"
        )
        session_maps.append(
            {
                "b_id": src,
                "a_id": dst,
                "action": action,
                "extra_jobs": logo_jobs,
            }
        )

    maps = {**maps, "chat": chat_alloc}
    msg_maps: list[dict] = []
    ordered = sorted(
        messages,
        key=lambda m: (
            str(m.get("chat_id") or ""),
            int(m.get("id") or 0),
            str(m.get("create_time") or ""),
        ),
    )
    for m in ordered:
        src = str(m.get("id") or "")
        if src in preexisting_msg:
            msg_maps.append(
                {
                    "b_id": src,
                    "a_id": preexisting_msg[src],
                    "chat_id": chat_alloc.get(str(m.get("chat_id") or ""), ""),
                    "extra_jobs": [],
                }
            )
            continue
        while mid in taken_msg:
            mid += 1
        dst = str(mid)
        taken_msg.add(mid)
        mid += 1
        chat_dst = chat_alloc.get(str(m.get("chat_id") or ""))
        if not chat_dst:
            continue
        if any(
            x.get("b_id") == str(m.get("chat_id")) and x.get("action") == "dedupe"
            for x in session_maps
        ):
            continue
        owner = (maps.get("user") or {}).get(str(m.get("user_id") or ""))
        tenant = (maps.get("tenant") or {}).get(
            str(m.get("tenant_id") or "1"), a_tenant_default
        )
        flow_id = str(m.get("flow_id") or "")
        flow_dst = (
            (maps.get("flow") or {}).get(flow_id)
            or (maps.get("assistant") or {}).get(flow_id)
            or ""
        )
        extra = m.get("extra")
        files = m.get("files")
        extra_obj = extra
        files_obj = files
        if isinstance(extra, str) and extra.strip().startswith(("{", "[")):
            extra_obj = json.loads(extra)
        if isinstance(files, str) and files.strip().startswith(("{", "[")):
            files_obj = json.loads(files)
        extra_new, extra_rep = (
            rewrite_tree(extra_obj, maps)
            if isinstance(extra_obj, (dict, list))
            else (extra, None)
        )
        files_new, _files_rep = (
            rewrite_tree(files_obj, maps)
            if isinstance(files_obj, (dict, list))
            else (files, None)
        )
        file_jobs: list[dict] = []
        if files_new not in (None, "", []):
            files_new, file_jobs = rewrite_stored_value(
                files_new, dst, ref=src, kind="files"
            )
        if extra_rep and extra_rep.missing:
            lines.append(f"-- WARN extra missing {src}: {extra_rep.missing[:5]}")
        mark_user = m.get("mark_user")
        mark_dst = (
            (maps.get("user") or {}).get(str(mark_user))
            if mark_user not in (None, "", "0", 0)
            else None
        )
        lines.append(
            "INSERT INTO chatmessage (id, is_bot, source, mark_status, mark_user, mark_user_name, message, extra, "
            "`type`, category, flow_id, chat_id, user_id, tenant_id, liked, solved, copied, sensitive_status, "
            "sender, receiver, intermediate_steps, files, remark, create_time) VALUES ("
            f"{sql_int(dst)}, {sql_bool(m.get('is_bot'))}, {sql_int(m.get('source'))}, "
            f"{sql_int(m.get('mark_status') or 1, '1')}, {sql_int(mark_dst)}, "
            f"{sql_str(m.get('mark_user_name') or None)}, {sql_str(m.get('message') or None)}, "
            f"{sql_json(extra_new) if isinstance(extra_new, (dict, list)) else sql_str(extra_new if extra_new else None)}, "
            f"{sql_str(m.get('type') or '')}, {sql_str(m.get('category') or '')}, "
            f"{sql_str(flow_dst)}, {sql_str(chat_dst)}, {sql_int(owner)}, {sql_int(tenant)}, "
            f"{sql_int(m.get('liked') or 0, '0')}, {sql_int(m.get('solved') or 0, '0')}, "
            f"{sql_int(m.get('copied') or 0, '0')}, {sql_int(m.get('sensitive_status') or 1, '1')}, "
            f"{sql_str(m.get('sender') or '')}, {sql_json(m.get('receiver'))}, "
            f"{sql_str(m.get('intermediate_steps') or None)}, "
            f"{sql_json(files_new) if isinstance(files_new, (dict, list)) else sql_str(files_new if files_new else None)}, "
            f"{sql_str(m.get('remark') or None)}, {sql_str(m.get('create_time') or None)});"
        )
        lines.append(
            "INSERT INTO fusion_map (batch_no, entity, src_id, dst_id, action, note) VALUES ("
            f"{sql_str(batch)}, 'message', {sql_str(src)}, {sql_str(dst)}, 'create', "
            f"{sql_str('src_id=' + src)});"
        )
        msg_maps.append(
            {
                "b_id": src,
                "a_id": dst,
                "chat_id": chat_dst,
                "extra_jobs": file_jobs,
            }
        )

    lines.append("COMMIT;")
    return "\n".join(lines) + "\n", session_maps, msg_maps, group_exceptions
