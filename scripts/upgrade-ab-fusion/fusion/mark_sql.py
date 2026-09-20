"""标注任务: 重写用户/应用/会话 ID. 不迁未映射会话."""

from __future__ import annotations

from fusion.sql import alloc_int_id, fusion_batch_open_sql, sql_int, sql_str


def remap_csv_ids(raw, table: dict[str, str]) -> str:
    """逗号分隔 ID 按表重写, 未映射的丢掉."""
    out = []
    for part in str(raw or "").split(","):
        token = part.strip()
        if not token:
            continue
        mapped = table.get(token)
        if mapped:
            out.append(str(mapped))
    return ",".join(out)


def _remap_app_id(raw, maps: dict[str, dict[str, str]]) -> str:
    flow_map = maps.get("flow") or {}
    asst_map = maps.get("assistant") or {}
    out = []
    for part in str(raw or "").split(","):
        token = part.strip()
        if not token:
            continue
        mapped = flow_map.get(token) or asst_map.get(token)
        if mapped:
            out.append(str(mapped))
    return ",".join(out)


def generate_mark_sql(
    *,
    batch: str,
    tasks: list[dict],
    records: list[dict],
    app_users: list[dict],
    maps: dict[str, dict[str, str]],
    a_task_ids: set[int],
    a_record_ids: set[int],
    a_app_user_ids: set[int],
    next_task_id: int,
    next_record_id: int,
    next_app_user_id: int,
    a_tenant_default: str,
) -> tuple[str, list[dict], list[dict], list[dict]]:
    """返回 (sql, task_maps, record_maps, app_user_maps)."""
    lines = [
        "SET NAMES utf8mb4;",
        f"-- batch {batch} marktask/markrecord B->A",
        "START TRANSACTION;",
        fusion_batch_open_sql(batch, "mark"),
    ]
    user_map = maps.get("user") or {}
    chat_map = maps.get("chat") or {}
    tenant_map = maps.get("tenant") or {}
    taken_task = set(a_task_ids)
    taken_rec = set(a_record_ids)
    taken_au = set(a_app_user_ids)
    nxt = next_task_id
    rec_nxt = next_record_id
    au_nxt = next_app_user_id
    task_alloc: dict[str, str] = dict(maps.get("mark_task") or {})
    preexisting_task = dict(task_alloc)
    preexisting_rec = dict(maps.get("mark_record") or {})
    preexisting_au = dict(maps.get("mark_app_user") or {})
    task_maps: list[dict] = []
    rec_maps: list[dict] = []
    au_maps: list[dict] = []
    skipped = 0

    for row in tasks:
        src = str(row.get("id") or "")
        if src in preexisting_task:
            task_maps.append({"b_id": src, "a_id": preexisting_task[src]})
            continue
        owner = user_map.get(str(row.get("create_id") or ""))
        if not owner:
            skipped += 1
            continue
        apps = _remap_app_id(row.get("app_id"), maps)
        users = remap_csv_ids(row.get("process_users"), user_map)
        mark_user = remap_csv_ids(row.get("mark_user"), user_map)
        tenant = tenant_map.get(str(row.get("tenant_id") or "1"), a_tenant_default)
        dst = alloc_int_id(nxt, taken_task)
        nxt = dst + 1
        task_alloc[src] = str(dst)
        lines.append(
            "INSERT INTO marktask (id, create_user, create_id, app_id, process_users, "
            "mark_user, status, tenant_id) VALUES ("
            f"{dst}, {sql_str(row.get('create_user') or '')}, {sql_int(owner)}, "
            f"{sql_str(apps)}, {sql_str(users)}, {sql_str(mark_user or None)}, "
            f"{sql_int(row.get('status') or 1, '1')}, {sql_int(tenant)});"
        )
        lines.append(
            "INSERT INTO fusion_map (batch_no, entity, src_id, dst_id, action, note) VALUES ("
            f"{sql_str(batch)}, 'mark_task', {sql_str(src)}, {sql_str(str(dst))}, 'create', "
            f"{sql_str(apps)});"
        )
        task_maps.append({"b_id": src, "a_id": str(dst)})

    for row in records:
        src = str(row.get("id") or "")
        if src in preexisting_rec:
            rec_maps.append({"b_id": src, "a_id": preexisting_rec[src]})
            continue
        dst_task = task_alloc.get(str(row.get("task_id") or ""))
        dst_chat = chat_map.get(str(row.get("session_id") or ""))
        owner = user_map.get(str(row.get("create_id") or ""))
        if not dst_task or not dst_chat or not owner:
            skipped += 1
            continue
        tenant = tenant_map.get(str(row.get("tenant_id") or "1"), a_tenant_default)
        dst = alloc_int_id(rec_nxt, taken_rec)
        rec_nxt = dst + 1
        app_raw = row.get("app_id")
        app_sql = "NULL"
        if app_raw not in (None, "", "0", 0):
            mapped_app = _remap_app_id(str(app_raw), maps)
            if mapped_app and "," not in mapped_app:
                # markrecord.app_id 是 int, 只在仍是数字时写入
                app_sql = sql_int(mapped_app) if str(mapped_app).isdigit() else "NULL"
        lines.append(
            "INSERT INTO markrecord (id, create_user, flow_type, create_id, app_id, task_id, "
            "session_id, status, tenant_id) VALUES ("
            f"{dst}, {sql_str(row.get('create_user') or '')}, "
            f"{sql_int(row.get('flow_type') or 10, '10')}, {sql_int(owner)}, {app_sql}, "
            f"{sql_int(dst_task)}, {sql_str(dst_chat)}, "
            f"{sql_int(row.get('status') or 1, '1')}, {sql_int(tenant)});"
        )
        lines.append(
            "INSERT INTO fusion_map (batch_no, entity, src_id, dst_id, action, note) VALUES ("
            f"{sql_str(batch)}, 'mark_record', {sql_str(src)}, {sql_str(str(dst))}, "
            f"'create', {sql_str(dst_chat)});"
        )
        rec_maps.append({"b_id": src, "a_id": str(dst)})

    for row in app_users:
        src = str(row.get("id") or "")
        if src in preexisting_au:
            au_maps.append({"b_id": src, "a_id": preexisting_au[src]})
            continue
        dst_task = task_alloc.get(str(row.get("task_id") or ""))
        owner = user_map.get(str(row.get("create_id") or ""))
        uid = user_map.get(str(row.get("user_id") or ""))
        app = _remap_app_id(row.get("app_id"), maps)
        if not dst_task or not owner or not uid or not app:
            skipped += 1
            continue
        tenant = tenant_map.get(str(row.get("tenant_id") or "1"), a_tenant_default)
        dst = alloc_int_id(au_nxt, taken_au)
        au_nxt = dst + 1
        lines.append(
            "INSERT INTO markappuser (id, app_id, user_id, task_id, create_id, status, tenant_id) VALUES ("
            f"{dst}, {sql_str(app)}, {sql_int(uid)}, {sql_int(dst_task)}, {sql_int(owner)}, "
            f"{sql_int(row.get('status') or 1, '1')}, {sql_int(tenant)});"
        )
        lines.append(
            "INSERT INTO fusion_map (batch_no, entity, src_id, dst_id, action, note) VALUES ("
            f"{sql_str(batch)}, 'mark_app_user', {sql_str(src)}, {sql_str(str(dst))}, "
            f"'create', {sql_str(app)});"
        )
        au_maps.append({"b_id": src, "a_id": str(dst)})

    lines.append(f"-- skipped={skipped}")
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n", task_maps, rec_maps, au_maps
