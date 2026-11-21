"""Visitor-only read views. Execution and editor models remain server-side."""

from copy import deepcopy

from fastapi.encoders import jsonable_encoder

_DISPLAY_FIELDS = frozenset(
    {"id", "name", "description", "desc", "logo", "status", "flow_type", "create_time", "update_time"}
)
_NODE_FIELDS = frozenset({"id", "type", "position"})
_NODE_DATA_FIELDS = frozenset({"id", "type", "name"})
_EDGE_FIELDS = frozenset({"id", "source", "target", "sourceHandle", "targetHandle", "type"})


def _select(data: dict, fields: frozenset[str]) -> dict:
    if not isinstance(data, dict):
        return {}
    return {key: deepcopy(value) for key, value in data.items() if key in fields}


def _graph_view(graph: object) -> dict:
    if not isinstance(graph, dict):
        return {"nodes": [], "edges": []}
    nodes = []
    for source in graph.get("nodes", []):
        if not isinstance(source, dict):
            continue
        node = _select(source, _NODE_FIELDS)
        data = source.get("data")
        data = data if isinstance(data, dict) else {}
        view = _select(data, _NODE_DATA_FIELDS)
        # The chat input adapter needs tab and parameter identities, not saved
        # values, prompts, credentials, source code or any executable settings.
        if data.get("type") == "input":
            tab = data.get("tab")
            if isinstance(tab, dict):
                view["tab"] = {"value": tab.get("value")}
            view["group_params"] = [
                {
                    "params": [
                        _select(param, frozenset({"key", "tab"}))
                        for param in group.get("params", [])
                        if isinstance(param, dict)
                    ]
                }
                for group in data.get("group_params", [])
                if isinstance(group, dict)
            ]
        node["data"] = view
        nodes.append(node)
    return {
        "nodes": nodes,
        "edges": [_select(edge, _EDGE_FIELDS) for edge in graph.get("edges", []) if isinstance(edge, dict)],
        "viewport": _select(graph.get("viewport", {}), frozenset({"x", "y", "zoom"})),
    }


def public_workflow_view(data: object) -> dict:
    """Only the public HTTP adapter uses this; never persist the result."""
    payload = jsonable_encoder(data)
    result = _select(payload, _DISPLAY_FIELDS | {"guide_word", "guide_question"})
    result["data"] = _graph_view(payload.get("data"))
    result["can_share"] = False
    return result


def public_assistant_view(data: object) -> dict:
    """Linked apps are metadata only, even when an unpublished graph is linked."""
    payload = jsonable_encoder(data)
    # Keep the published app's user-facing guidance, not author/runtime settings.
    result = _select(
        payload, _DISPLAY_FIELDS | {"guide_word", "guide_question", "opening_remarks", "suggested_questions"}
    )
    for collection in ("flow_list", "tool_list", "knowledge_list"):
        result[collection] = [
            _select(item, _DISPLAY_FIELDS) for item in payload.get(collection, []) if isinstance(item, dict)
        ]
    result["can_share"] = False
    return result
