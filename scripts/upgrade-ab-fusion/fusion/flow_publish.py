"""迁入工作流/助手上线门禁. 默认生成 UPDATE, 不自动跑端到端."""

from __future__ import annotations

import json

from fusion.json_rewrite import rewrite_flow_data
from fusion.sql import sql_int, sql_str

ONLINE = 2
OFFLINE = 1


def used_from_report(report) -> dict[str, list[str]]:
    data = report.as_dict() if hasattr(report, "as_dict") else report
    return data.get("used") or {}


def gate_flow(
    *,
    src_id: str,
    dst_id: str,
    desired_status: int,
    data: dict | None,
    maps: dict[str, dict[str, str]],
    gap_model_ids: set[str],
    gap_tool_ids: set[str],
    vector_exception_kids: set[str],
) -> dict:
    """通过才允许把 A 上该工作流 status 改回 B 原值."""
    if not dst_id:
        return {"src_id": src_id, "ok": False, "reason": "无 A 映射"}
    if int(desired_status or OFFLINE) != ONLINE:
        return {
            "src_id": src_id,
            "dst_id": dst_id,
            "ok": False,
            "reason": "B 原为下线, 不发布",
            "desired_status": int(desired_status or OFFLINE),
        }
    payload = data or {}
    if isinstance(payload, str):
        payload = json.loads(payload) if payload else {}
    _rewritten, report = rewrite_flow_data(payload, maps)
    if report.missing:
        return {
            "src_id": src_id,
            "dst_id": dst_id,
            "ok": False,
            "reason": "引用未映射: " + ",".join(report.missing[:6]),
        }
    model_dropped = [x for x in report.dropped if x.startswith("model:")]
    if model_dropped:
        return {
            "src_id": src_id,
            "dst_id": dst_id,
            "ok": False,
            "reason": "模型引用已删除: " + ",".join(model_dropped[:6]),
        }
    used = used_from_report(report)
    for mid in used.get("model") or []:
        if mid in gap_model_ids:
            return {
                "src_id": src_id,
                "dst_id": dst_id,
                "ok": False,
                "reason": f"模型 {mid} 仍在缺口清单",
            }
    for tid in used.get("tool") or []:
        if tid in gap_tool_ids:
            return {
                "src_id": src_id,
                "dst_id": dst_id,
                "ok": False,
                "reason": f"工具 {tid} 仍在缺口清单",
            }
    for kid in used.get("knowledge") or []:
        if kid in vector_exception_kids:
            return {
                "src_id": src_id,
                "dst_id": dst_id,
                "ok": False,
                "reason": f"知识库 {kid} 向量不兼容, 禁止上线",
            }
    return {
        "src_id": src_id,
        "dst_id": dst_id,
        "ok": True,
        "reason": "",
        "desired_status": ONLINE,
    }


def gate_assistant(
    *,
    src_id: str,
    dst_id: str,
    desired_status: int,
    model_name: str,
    maps: dict[str, dict[str, str]],
    gap_model_ids: set[str],
) -> dict:
    if not dst_id:
        return {"src_id": src_id, "ok": False, "reason": "无 A 映射"}
    if int(desired_status or OFFLINE) != ONLINE:
        return {
            "src_id": src_id,
            "dst_id": dst_id,
            "ok": False,
            "reason": "B 原为下线, 不发布",
        }
    if model_name and model_name in gap_model_ids:
        return {
            "src_id": src_id,
            "dst_id": dst_id,
            "ok": False,
            "reason": f"模型 {model_name} 仍在缺口清单",
        }
    if model_name and model_name.isdigit() and model_name not in (maps.get("model") or {}):
        return {
            "src_id": src_id,
            "dst_id": dst_id,
            "ok": False,
            "reason": f"模型 {model_name} 未 bind",
        }
    return {"src_id": src_id, "dst_id": dst_id, "ok": True, "desired_status": ONLINE}


def generate_publish_sql(
    *,
    batch: str,
    flow_rows: list[dict],
    assistant_rows: list[dict],
) -> str:
    """只 UPDATE 门禁通过的 dst. 调用方保证 dst 都是本批映射."""
    lines = [
        "SET NAMES utf8mb4;",
        f"-- publish migrated flows/assistants batch {batch}",
        "START TRANSACTION;",
    ]
    n = 0
    for row in flow_rows:
        if not row.get("ok"):
            continue
        lines.append(f"UPDATE flow SET status={sql_int(ONLINE)} WHERE id={sql_str(row['dst_id'])};")
        n += 1
    for row in assistant_rows:
        if not row.get("ok"):
            continue
        lines.append(f"UPDATE assistant SET status={sql_int(ONLINE)} WHERE id={sql_str(row['dst_id'])};")
        n += 1
    lines.append("COMMIT;")
    if n == 0:
        return f"-- publish batch {batch}: none passed gate\n"
    return "\n".join(lines) + "\n"
