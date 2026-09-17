"""工作流/消息 JSON: 只按字段白名单重写 ID, 禁止全文替换."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

INT_LEAF_KEYS = {
    "model_id": "model",
    "recommended_llm": "model",
    "rerank_model": "model",
    "user_id": "user",
    "mark_user": "user",
    "knowledge_id": "knowledge",
    "qa_knowledge_id": "knowledge",
    "original_knowledge_id": "knowledge",
    "original_uploader_id": "user",
    "updater_id": "user",
    "create_user": "user",
    "create_id": "user",
    "server_id": "llm_server",
}

STR_LEAF_KEYS = {
    "flow_id": "flow",
    "assistant_id": "assistant",
    "chat_id": "chat",
}

SELECTOR_KEYS = {"knowledge", "qa_knowledge_id", "knowledge_id"}
TOOL_LIST_KEYS = {"tool_list", "tools"}
PARAM_LOGICAL_KEYS = (
    SELECTOR_KEYS
    | set(INT_LEAF_KEYS)
    | set(STR_LEAF_KEYS)
    | TOOL_LIST_KEYS
    | {"group_ids"}
)


class RewriteReport:
    def __init__(self) -> None:
        self.rewritten: list[str] = []
        self.unknown: list[str] = []
        self.missing: list[str] = []
        self.dropped: list[str] = []
        self.used: list[tuple[str, str]] = []

    def as_dict(self) -> dict:
        used: dict[str, list[str]] = {}
        for kind, src in self.used:
            used.setdefault(kind, [])
            if src not in used[kind]:
                used[kind].append(src)
        return {
            "rewritten": self.rewritten,
            "unknown": self.unknown,
            "missing": self.missing,
            "dropped": self.dropped,
            "used": used,
        }


def _is_int_id(value: Any) -> bool:
    """知识库选择器里会混节点输出引用 (如 input_xxx.file), 那些不是资源 ID."""
    if isinstance(value, bool) or value in (None, ""):
        return False
    if isinstance(value, int):
        return True
    text = str(value).strip()
    return text.isdigit()


def _map_int(
    value: Any,
    table: dict[str, str],
    path: str,
    report: RewriteReport,
    kind: str = "",
) -> Any:
    if value in (None, "", 0, "0"):
        return value
    key = str(value)
    if kind:
        report.used.append((kind, key))
    if key in table:
        report.rewritten.append(f"{path}={key}->{table[key]}")
        raw = table[key]
        return int(raw) if str(raw).isdigit() else raw
    report.missing.append(f"{path}={key}")
    return value


def _map_str(
    value: Any,
    table: dict[str, str],
    path: str,
    report: RewriteReport,
    kind: str = "",
) -> Any:
    if value in (None, ""):
        return value
    key = str(value)
    if kind:
        report.used.append((kind, key))
    if key in table:
        report.rewritten.append(f"{path}={key}->{table[key]}")
        return table[key]
    report.missing.append(f"{path}={key}")
    return value


def _rewrite_key_list(
    items: list,
    table: dict[str, str],
    path: str,
    report: RewriteReport,
    kind: str,
) -> list:
    out = []
    for i, item in enumerate(items):
        if isinstance(item, dict) and "key" in item:
            copied = dict(item)
            raw_key = item.get("key")
            # 知识选择器可指向上游节点输出, 不是 knowledge.id
            if kind == "knowledge" and not _is_int_id(raw_key):
                out.append(copied)
                continue
            # B 已删的知识库: 从选择器去掉并记 dropped, 不阻断整条工作流 SQL
            if kind == "knowledge" and str(raw_key) not in table:
                report.dropped.append(f"{path}[{i}].key={raw_key}")
                continue
            copied["key"] = _map_int(
                raw_key, table, f"{path}[{i}].key", report, kind=kind
            )
            out.append(copied)
        else:
            out.append(item)
    return out


def rewrite_value(
    value: Any,
    key: str | None,
    maps: dict[str, dict[str, str]],
    path: str,
    report: RewriteReport,
) -> Any:
    if isinstance(value, list):
        if key == "group_ids":
            return [
                _map_int(
                    v, maps.get("group") or {}, f"{path}[{i}]", report, kind="group"
                )
                for i, v in enumerate(value)
            ]
        if key in TOOL_LIST_KEYS:
            return _rewrite_key_list(
                value, maps.get("tool") or {}, path, report, kind="tool"
            )
        if key == "qa_knowledge_id" and value and not isinstance(value[0], dict):
            table = maps.get("knowledge") or {}
            kept = []
            for i, v in enumerate(value):
                if v in (None, "", 0, "0"):
                    continue
                if not _is_int_id(v) or str(v) in table:
                    kept.append(
                        _map_int(v, table, f"{path}[{i}]", report, kind="knowledge")
                        if _is_int_id(v)
                        else v
                    )
                    continue
                report.dropped.append(f"{path}[{i}]={v}")
            return kept
        return [
            rewrite_value(v, key, maps, f"{path}[{i}]", report)
            for i, v in enumerate(value)
        ]

    if isinstance(value, dict):
        logical = value.get("key")
        # 工作流节点 params: {key: model_id|knowledge, value: ...}
        if (
            isinstance(logical, str)
            and "value" in value
            and logical in PARAM_LOGICAL_KEYS
        ):
            return {
                k: rewrite_value(
                    v, logical if k == "value" else k, maps, f"{path}.{k}", report
                )
                for k, v in value.items()
            }
        if key in SELECTOR_KEYS and "value" in value:
            knowledge_map = maps.get("knowledge") or {}
            out = dict(value)
            items = out.get("value")
            if isinstance(items, list):
                out["value"] = _rewrite_key_list(
                    items, knowledge_map, f"{path}.value", report, kind="knowledge"
                )
            return out
        return {
            k: rewrite_value(v, k, maps, f"{path}.{k}", report)
            for k, v in value.items()
        }

    # 报表 version_key / 自定义 tool_key: 只在提供了对应 map 且命中时改写, 未命中保持原值 (预置工具 key 两边相同).
    if key == "version_key":
        table = maps.get("report_version_key") or {}
        raw = "" if value in (None, "") else str(value)
        if raw and raw in table:
            return _map_str(value, table, path, report, kind="report_version_key")
        return value
    if key == "tool_key":
        table = maps.get("tool_key") or {}
        raw = "" if value in (None, "") else str(value)
        if raw and raw in table:
            return _map_str(value, table, path, report, kind="tool_key")
        return value
    if key in INT_LEAF_KEYS:
        return _map_int(
            value,
            maps.get(INT_LEAF_KEYS[key]) or {},
            path,
            report,
            kind=INT_LEAF_KEYS[key],
        )
    if key in STR_LEAF_KEYS:
        return _map_str(
            value,
            maps.get(STR_LEAF_KEYS[key]) or {},
            path,
            report,
            kind=STR_LEAF_KEYS[key],
        )
    return value


def rewrite_tree(
    data: Any, maps: dict[str, dict[str, str]]
) -> tuple[Any, RewriteReport]:
    report = RewriteReport()
    return rewrite_value(deepcopy(data), None, maps, "$", report), report


def rewrite_flow_data(
    data: Any, maps: dict[str, dict[str, str]]
) -> tuple[Any, RewriteReport]:
    return rewrite_tree(data, maps)
