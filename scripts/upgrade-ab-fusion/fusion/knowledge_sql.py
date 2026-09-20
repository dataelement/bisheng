"""B 知识库 INSERT 到 A. 永不 UPDATE knowledge.type=3 的既有行."""

from __future__ import annotations

from fusion import NAME_SUFFIX
from fusion.maps import require_mapped_model
from fusion.minio_keys import rewrite_object_key, rewrite_stored_value
from fusion.sql import alloc_int_id, fusion_batch_open_sql, sql_int, sql_json, sql_str
from fusion.vector_names import target_collection_name, target_index_name


def unique_name(name: str, existing: set[str]) -> str:
    if name not in existing:
        return name
    candidate = f"{name}{NAME_SUFFIX}"
    n = 1
    while candidate in existing:
        n += 1
        candidate = f"{name}{NAME_SUFFIX}{n}"
    return candidate


def generate_knowledge_sql(
    *,
    batch: str,
    knowledges: list[dict],
    files: list[dict],
    user_map: dict[str, str],
    tenant_map: dict[str, str],
    model_map: dict[str, str],
    a_knowledge_names: set[str],
    a_existing_ids: set[int],
    next_knowledge_id: int,
    next_file_id: int,
    a_tenant_default: str,
    a_space_ids: set[int],
    migrate_b_spaces: bool = False,
    existing_knowledge: dict[str, str] | None = None,
    existing_files: dict[str, str] | None = None,
) -> tuple[str, list[dict], list[dict]]:
    """返回 (sql, knowledge_maps, file_maps). 写集合不得包含 a_space_ids.
    src 已在 mapping 则跳过 INSERT, 但仍写入 maps 以便新文件挂到旧库."""
    lines = [
        "SET NAMES utf8mb4;",
        f"-- batch {batch} knowledge B->A (INSERT only)",
        "START TRANSACTION;",
        fusion_batch_open_sql(batch, "knowledge"),
    ]
    names = set(a_knowledge_names)
    k_maps: list[dict] = []
    f_maps: list[dict] = []
    k_alloc: dict[str, str] = {}
    existing_knowledge = dict(existing_knowledge or {})
    existing_files = dict(existing_files or {})
    taken_k = set(a_existing_ids) | set(a_space_ids)
    for dst in existing_knowledge.values():
        try:
            taken_k.add(int(dst))
        except ValueError:
            pass
    taken_f: set[int] = set()
    for dst in existing_files.values():
        try:
            taken_f.add(int(dst))
        except ValueError:
            pass
    kid = next_knowledge_id
    fid = next_file_id

    for k in knowledges:
        src = str(k.get("id") or "")
        ktype = int(k.get("type") or 0)
        if ktype == 3 and not migrate_b_spaces:
            continue
        if src in existing_knowledge:
            dst = existing_knowledge[src]
            k_alloc[src] = dst
            k_maps.append(
                {
                    "b_id": src,
                    "a_id": dst,
                    "type": str(ktype),
                    "name": k.get("name") or "",
                    "b_collection": k.get("collection_name") or "",
                    "a_collection": target_collection_name(
                        src, k.get("collection_name"), dst
                    ),
                    "b_index": k.get("index_name") or "",
                    "a_index": target_index_name(src, k.get("index_name"), dst),
                    "b_model": str(k.get("model") or ""),
                    "a_model": str(k.get("model") or ""),
                }
            )
            continue
        dst_id = alloc_int_id(kid, taken_k)
        kid = dst_id + 1
        k_alloc[src] = str(dst_id)
        owner = user_map.get(str(k.get("user_id") or ""))
        if not owner:
            raise ValueError(f"knowledge {src} 所有者 {k.get('user_id')} 未映射")
        tenant = tenant_map.get(str(k.get("tenant_id") or "1"), a_tenant_default)
        name = unique_name(k.get("name") or f"kb-{src}", names)
        names.add(name)
        b_model = k.get("model") or ""
        model = (
            require_mapped_model("knowledge", src, str(b_model), model_map)
            if b_model
            else ""
        )
        b_coll = k.get("collection_name") or ""
        b_idx = k.get("index_name") or ""
        # 避免覆盖 A 现有 collection / index 名
        coll = target_collection_name(src, b_coll, str(dst_id))
        idx = target_index_name(src, b_idx, str(dst_id))
        lines.append(
            "INSERT INTO knowledge (id, user_id, tenant_id, name, type, description, model, "
            "collection_name, index_name, state, is_released, is_favorite) VALUES ("
            f"{dst_id}, {sql_int(owner)}, {sql_int(tenant)}, {sql_str(name)}, {ktype}, "
            f"{sql_str(k.get('description') or None)}, {sql_str(model or None)}, "
            f"{sql_str(coll)}, {sql_str(idx)}, {sql_int(k.get('state') or 1, '1')}, "
            f"{sql_int(k.get('is_released') or 0, '0')}, {sql_int(k.get('is_favorite') or 0, '0')});"
        )
        lines.append(
            "INSERT INTO fusion_map (batch_no, entity, src_id, dst_id, action, note) VALUES ("
            f"{sql_str(batch)}, 'knowledge', {sql_str(src)}, {sql_str(str(dst_id))}, 'create', "
            f"{sql_str(f'type={ktype} name={name}')});"
        )
        k_maps.append(
            {
                "b_id": src,
                "a_id": str(dst_id),
                "type": str(ktype),
                "name": name,
                "b_collection": b_coll,
                "a_collection": coll,
                "b_index": b_idx,
                "a_index": idx,
                "b_model": str(b_model),
                "a_model": str(model or ""),
            }
        )

    for f in files:
        src = str(f.get("id") or "")
        src_kid = str(f.get("knowledge_id") or "")
        dst_kid = k_alloc.get(src_kid)
        if not dst_kid:
            # 所属库被 MIGRATE_B_SPACES=0 跳过时, 文件一并跳过
            continue
        if src in existing_files:
            f_maps.append({"b_id": src, "a_id": existing_files[src], "extra_jobs": []})
            continue
        dst_fid = str(alloc_int_id(fid, taken_f))
        fid = int(dst_fid) + 1
        owner = user_map.get(str(f.get("user_id") or ""), "")
        tenant = tenant_map.get(str(f.get("tenant_id") or "1"), a_tenant_default)
        obj = rewrite_object_key(f.get("object_name"), dst_fid)
        preview = rewrite_object_key(f.get("preview_file_object_name"), dst_fid)
        bbox = rewrite_object_key(f.get("bbox_object_name"), dst_fid)
        thumb_new, thumb_jobs = rewrite_stored_value(
            f.get("thumbnails"), dst_fid, ref=src, kind="thumbnails"
        )
        thumb_sql = (
            sql_json(thumb_new)
            if isinstance(thumb_new, (dict, list))
            else sql_str(thumb_new or None)
        )
        updater = user_map.get(str(f.get("updater_id") or ""), "") or None
        orig_up = user_map.get(str(f.get("original_uploader_id") or ""), "") or None
        orig_kid = k_alloc.get(str(f.get("original_knowledge_id") or ""))
        lines.append(
            "INSERT INTO knowledgefile (id, user_id, user_name, knowledge_id, tenant_id, "
            "file_name, alias_name, file_type, file_source, object_name, preview_file_object_name, "
            "bbox_object_name, thumbnails, status, md5, file_size, parse_type, split_rule, "
            "user_metadata, remark, updater_id, original_uploader_id, original_knowledge_id) VALUES ("
            f"{sql_int(dst_fid)}, {sql_int(owner or None)}, {sql_str(f.get('user_name') or None)}, "
            f"{sql_int(dst_kid)}, {sql_int(tenant)}, {sql_str(f.get('file_name') or '')}, "
            f"{sql_str(f.get('alias_name') or None)}, "
            f"{sql_int(f.get('file_type') or 1, '1')}, {sql_str(f.get('file_source') or 'upload')}, "
            f"{sql_str(obj)}, {sql_str(preview)}, {sql_str(bbox)}, "
            f"{thumb_sql}, {sql_int(f.get('status') or 2, '2')}, "
            f"{sql_str(f.get('md5') or None)}, {sql_int(f.get('file_size') or None)}, "
            f"{sql_str(f.get('parse_type') or None)}, {sql_str(f.get('split_rule') or None)}, "
            f"{sql_json(f.get('user_metadata'))}, {sql_str(f.get('remark') or None)}, "
            f"{sql_int(updater)}, {sql_int(orig_up)}, {sql_int(orig_kid)});"
        )
        lines.append(
            "INSERT INTO fusion_map (batch_no, entity, src_id, dst_id, action, note) VALUES ("
            f"{sql_str(batch)}, 'file', {sql_str(src)}, {sql_str(dst_fid)}, 'create', "
            f"{sql_str((obj or '') + '|' + (f.get('object_name') or ''))});"
        )
        f_maps.append(
            {
                "b_id": src,
                "a_id": dst_fid,
                "src_object_key": f.get("object_name") or "",
                "dst_object_key": obj or "",
                "preview_src": f.get("preview_file_object_name") or "",
                "preview_dst": preview or "",
                "bbox_src": f.get("bbox_object_name") or "",
                "bbox_dst": bbox or "",
                "extra_jobs": thumb_jobs,
            }
        )

    # 硬保护: 生成物不得引用 A 原空间 id 作为 UPDATE 目标
    for stmt in lines:
        if "UPDATE knowledge" in stmt.upper():
            raise ValueError("knowledge SQL 禁止 UPDATE knowledge")

    lines.append("COMMIT;")
    return "\n".join(lines) + "\n", k_maps, f_maps


def assert_write_set_skips_a_spaces(
    knowledge_maps: list[dict], a_space_ids: set[int]
) -> None:
    for row in knowledge_maps:
        if int(row["a_id"]) in a_space_ids:
            raise ValueError(f"写集合命中 A 原空间 id={row['a_id']}")
