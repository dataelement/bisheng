"""工作流 / 助手 SQL. UUID 无冲突则保留."""

from __future__ import annotations

import json
import uuid

from fusion import NAME_SUFFIX
from fusion.json_rewrite import rewrite_flow_data
from fusion.maps import require_mapped_model
from fusion.minio_keys import rewrite_stored_value
from fusion.sql import fusion_batch_open_sql, sql_int, sql_json, sql_str


def _dropped_exception_kind(dropped: list[str]) -> str:
    """JSON 丢掉的引用: 已删模型 vs 已删知识库, 写入 fusion_exception.kind."""
    if any(item.startswith("model:") for item in dropped):
        return "dangling_model_ref"
    return "dangling_knowledge_ref"


def pick_uuid(src_id: str, a_existing: set[str]) -> str:
    if src_id and src_id not in a_existing:
        return src_id
    return uuid.uuid4().hex


def unique_flow_name(name: str, existing: set[str]) -> str:
    if name not in existing:
        return name
    candidate = f"{name}{NAME_SUFFIX}"
    n = 1
    while candidate in existing:
        n += 1
        candidate = f"{name}{NAME_SUFFIX}{n}"
    return candidate


def generate_flow_sql(
    *,
    batch: str,
    flows: list[dict],
    versions: list[dict],
    variables: list[dict],
    maps: dict[str, dict[str, str]],
    a_flow_ids: set[str],
    a_flow_names: set[str],
    next_version_id: int,
    a_tenant_default: str,
) -> tuple[str, list[dict], list[dict], list[dict]]:
    """返回 (sql, flow_maps, version_maps, reports). 已映射 flow/version 跳过 INSERT."""
    lines = [
        "SET NAMES utf8mb4;",
        f"-- batch {batch} flow B->A",
        "START TRANSACTION;",
        fusion_batch_open_sql(batch, "flow"),
    ]
    reports: list[dict] = []
    flow_maps: list[dict] = []
    version_maps: list[dict] = []
    vid = next_version_id
    version_alloc: dict[str, str] = {}
    names = set(a_flow_names)
    existing_ids = set(a_flow_ids)
    preexisting_flow = dict(maps.get("flow") or {})
    preexisting_version = dict(maps.get("flowversion") or {})
    flow_alloc = dict(preexisting_flow)

    for fl in flows:
        src = str(fl.get("id") or "")
        if src in preexisting_flow:
            dst = preexisting_flow[src]
            existing_ids.add(dst)
            flow_alloc[src] = dst
            flow_maps.append(
                {
                    "b_id": src,
                    "a_id": dst,
                    "name": fl.get("name") or "",
                    "extra_jobs": [],
                }
            )
            continue
        dst = pick_uuid(src, existing_ids)
        existing_ids.add(dst)
        flow_alloc[src] = dst
        owner = (maps.get("user") or {}).get(str(fl.get("user_id") or ""))
        if not owner:
            raise ValueError(f"flow {src} 所有者未映射")
        tenant = (maps.get("tenant") or {}).get(str(fl.get("tenant_id") or "1"), a_tenant_default)
        name = unique_flow_name(fl.get("name") or f"flow-{src}", names)
        names.add(name)
        data = fl.get("data")
        if isinstance(data, str):
            data = json.loads(data) if data else {}
        rewritten, report = rewrite_flow_data(data or {}, {**maps, "flow": flow_alloc})
        if report.missing:
            raise ValueError(f"flow {src} 嵌套引用未映射: {report.missing[:8]}")
        if report.dropped:
            lines.append(
                "INSERT INTO fusion_exception (batch_no, kind, src_entity, src_id, detail) VALUES ("
                f"{sql_str(batch)}, {sql_str(_dropped_exception_kind(report.dropped))}, "
                f"'flow', {sql_str(src)}, "
                f"{sql_str(','.join(report.dropped)[:2000])});"
            )
        status = fl.get("status") or 1
        # 未完成权限验证前保持下线
        status = 1
        logo_new, logo_jobs = rewrite_stored_value(fl.get("logo"), dst, ref=src, kind="logo")
        logo_sql = sql_json(logo_new) if isinstance(logo_new, (dict, list)) else sql_str(logo_new or None)
        lines.append(
            "INSERT INTO flow (id, name, user_id, tenant_id, description, data, logo, status, flow_type, guide_word) "
            "VALUES ("
            f"{sql_str(dst)}, {sql_str(name)}, {sql_int(owner)}, {sql_int(tenant)}, "
            f"{sql_str(fl.get('description') or None)}, {sql_json(rewritten)}, "
            f"{logo_sql}, {sql_int(status)}, "
            f"{sql_int(fl.get('flow_type') or 10, '10')}, {sql_str(fl.get('guide_word') or None)});"
        )
        lines.append(
            "INSERT INTO fusion_map (batch_no, entity, src_id, dst_id, action, note) VALUES ("
            f"{sql_str(batch)}, 'flow', {sql_str(src)}, {sql_str(dst)}, "
            f"{sql_str('keep' if dst == src else 'new_uuid')}, {sql_str(name)});"
        )
        flow_maps.append(
            {
                "b_id": src,
                "a_id": dst,
                "name": name,
                "extra_jobs": logo_jobs,
            }
        )
        reports.append({"flow": src, **report.as_dict()})

    maps = {**maps, "flow": flow_alloc}

    # 先分配全部 version id, 才能重写 original_version_id
    pending_versions = []
    for ver in versions:
        src = str(ver.get("id") or "")
        if src in preexisting_version:
            dst = preexisting_version[src]
            version_alloc[src] = dst
            version_maps.append({"b_id": src, "a_id": dst})
            continue
        flow_src = str(ver.get("flow_id") or "")
        if flow_src not in flow_alloc:
            # 父工作流已删, 版本行仍残留 (常见 is_delete=1)
            lines.append(
                "INSERT INTO fusion_exception (batch_no, kind, src_entity, src_id, detail) VALUES ("
                f"{sql_str(batch)}, 'orphan_flowversion', 'flowversion', {sql_str(src)}, "
                f"{sql_str(f'flow_id={flow_src} 无对应 flow, 跳过')});"
            )
            continue
        dst = str(vid)
        vid += 1
        version_alloc[src] = dst
        pending_versions.append((src, dst, ver))
        version_maps.append({"b_id": src, "a_id": dst})

    for src, dst, ver in pending_versions:
        flow_dst = flow_alloc.get(str(ver.get("flow_id") or ""))
        owner = (maps.get("user") or {}).get(str(ver.get("user_id") or ""), None)
        tenant = (maps.get("tenant") or {}).get(str(ver.get("tenant_id") or "1"), a_tenant_default)
        data = ver.get("data")
        if isinstance(data, str):
            data = json.loads(data) if data else {}
        rewritten, report = rewrite_flow_data(data or {}, maps)
        if report.missing:
            raise ValueError(f"flowversion {src} 嵌套引用未映射: {report.missing[:8]}")
        if report.dropped:
            lines.append(
                "INSERT INTO fusion_exception (batch_no, kind, src_entity, src_id, detail) VALUES ("
                f"{sql_str(batch)}, {sql_str(_dropped_exception_kind(report.dropped))}, "
                f"'flowversion', {sql_str(src)}, "
                f"{sql_str(','.join(report.dropped)[:2000])});"
            )
        orig = ver.get("original_version_id")
        orig_sql = "NULL"
        if orig not in (None, "", "0", 0):
            mapped_orig = version_alloc.get(str(orig))
            orig_sql = sql_int(mapped_orig) if mapped_orig else "NULL"
        lines.append(
            "INSERT INTO flowversion (id, flow_id, name, data, description, user_id, flow_type, "
            "is_current, is_delete, original_version_id, tenant_id) VALUES ("
            f"{sql_int(dst)}, {sql_str(flow_dst)}, {sql_str(ver.get('name') or 'v')}, {sql_json(rewritten)}, "
            f"{sql_str(ver.get('description') or None)}, {sql_int(owner)}, "
            f"{sql_int(ver.get('flow_type') or 10, '10')}, {sql_int(ver.get('is_current') or 0, '0')}, "
            f"{sql_int(ver.get('is_delete') or 0, '0')}, {orig_sql}, {sql_int(tenant)});"
        )
        lines.append(
            "INSERT INTO fusion_map (batch_no, entity, src_id, dst_id, action, note) VALUES ("
            f"{sql_str(batch)}, 'flowversion', {sql_str(src)}, {sql_str(dst)}, 'create', NULL);"
        )
        reports.append({"flowversion": src, **report.as_dict()})

    for var in variables:
        if str(var.get("version_id") or "") in preexisting_version:
            continue
        flow_dst = flow_alloc.get(str(var.get("flow_id") or ""))
        ver_dst = version_alloc.get(str(var.get("version_id") or ""))
        if not flow_dst:
            continue
        tenant = (maps.get("tenant") or {}).get(str(var.get("tenant_id") or "1"), a_tenant_default)
        lines.append(
            "INSERT INTO t_variable_value (flow_id, version_id, node_id, variable_name, value_type, "
            "is_option, `value`, tenant_id) VALUES ("
            f"{sql_str(flow_dst)}, {sql_int(ver_dst) if ver_dst else 'NULL'}, "
            f"{sql_str(var.get('node_id') or '')}, {sql_str(var.get('variable_name') or None)}, "
            f"{sql_int(var.get('value_type') or 1, '1')}, {sql_int(var.get('is_option') or 1, '1')}, "
            f"{sql_str(var.get('value') or None)}, {sql_int(tenant)});"
        )

    lines.append("COMMIT;")
    return "\n".join(lines) + "\n", flow_maps, version_maps, reports


def generate_assistant_sql(
    *,
    batch: str,
    assistants: list[dict],
    links: list[dict],
    maps: dict[str, dict[str, str]],
    a_assistant_ids: set[str],
    a_tenant_default: str,
) -> tuple[str, list[dict], list[dict]]:
    """返回 (sql, assistant_maps, 跳过的未映射工具 link)."""
    lines = [
        "SET NAMES utf8mb4;",
        f"-- batch {batch} assistant B->A",
        "START TRANSACTION;",
        fusion_batch_open_sql(batch, "assistant"),
    ]
    existing = set(a_assistant_ids)
    preexisting = dict(maps.get("assistant") or {})
    alloc: dict[str, str] = dict(preexisting)
    out_maps: list[dict] = []
    link_gaps: list[dict] = []
    for a in assistants:
        src = str(a.get("id") or "")
        if src in preexisting:
            dst = preexisting[src]
            existing.add(dst)
            alloc[src] = dst
            out_maps.append({"b_id": src, "a_id": dst, "extra_jobs": []})
            continue
        dst = pick_uuid(src, existing)
        existing.add(dst)
        alloc[src] = dst
        owner = (maps.get("user") or {}).get(str(a.get("user_id") or ""))
        if not owner:
            raise ValueError(f"assistant {src} 所有者未映射")
        tenant = (maps.get("tenant") or {}).get(str(a.get("tenant_id") or "1"), a_tenant_default)
        model = require_mapped_model("assistant", src, str(a.get("model_name") or ""), maps.get("model") or {})
        name = a.get("name") or f"asst-{src}"
        if NAME_SUFFIX not in name:
            # 助手同名不合并, 但 UUID 已隔离; 名称冲突只加后缀当 A 已有同名时由调用方传入
            pass
        logo_new, logo_jobs = rewrite_stored_value(a.get("logo"), dst, ref=src, kind="logo")
        logo_sql = sql_json(logo_new) if isinstance(logo_new, (dict, list)) else sql_str(logo_new or "")
        lines.append(
            "INSERT INTO assistant (id, name, tenant_id, logo, `desc`, system_prompt, prompt, "
            "guide_word, guide_question, model_name, temperature, max_token, status, user_id, is_delete) VALUES ("
            f"{sql_str(dst)}, {sql_str(name)}, {sql_int(tenant)}, {logo_sql}, "
            f"{sql_str(a.get('desc') or '')}, {sql_str(a.get('system_prompt') or '')}, "
            f"{sql_str(a.get('prompt') or '')}, {sql_str(a.get('guide_word') or '')}, "
            f"{sql_json(a.get('guide_question'))}, {sql_str(model)}, "
            f"{a.get('temperature') if a.get('temperature') is not None else 1}, "
            f"{sql_int(a.get('max_token') or 32000, '32000')}, 1, {sql_int(owner)}, "
            f"{sql_int(a.get('is_delete') or 0, '0')});"
        )
        lines.append(
            "INSERT INTO fusion_map (batch_no, entity, src_id, dst_id, action, note) VALUES ("
            f"{sql_str(batch)}, 'assistant', {sql_str(src)}, {sql_str(dst)}, "
            f"{sql_str('keep' if dst == src else 'new_uuid')}, {sql_str(name)});"
        )
        out_maps.append(
            {
                "b_id": src,
                "a_id": dst,
                "extra_jobs": logo_jobs,
            }
        )

    for link in links:
        asst_src = str(link.get("assistant_id") or "")
        if asst_src in preexisting:
            continue
        asst = alloc.get(asst_src)
        if not asst:
            continue
        tenant = (maps.get("tenant") or {}).get(str(link.get("tenant_id") or "1"), a_tenant_default)
        tool = link.get("tool_id")
        kid = link.get("knowledge_id")
        fid = link.get("flow_id")
        tool_s = None
        if tool not in (None, 0, "0", ""):
            tool_s = (maps.get("tool") or {}).get(str(tool))
            if tool_s is None:
                link_gaps.append(
                    {
                        "kind": "assistantlink",
                        "assistant_id": asst_src,
                        "b_tool_id": str(tool),
                        "reason": "工具未映射, 跳过该 link",
                    }
                )
                continue
        kid_s = (maps.get("knowledge") or {}).get(str(kid), None) if kid not in (None, 0, "0", "") else None
        fid_s = (maps.get("flow") or {}).get(str(fid), None) if fid not in (None, "", "0") else None
        lines.append(
            "INSERT INTO assistantlink (assistant_id, tool_id, flow_id, knowledge_id, tenant_id) VALUES ("
            f"{sql_str(asst)}, {sql_int(tool_s)}, {sql_str(fid_s)}, {sql_int(kid_s)}, {sql_int(tenant)});"
        )
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n", out_maps, link_gaps
