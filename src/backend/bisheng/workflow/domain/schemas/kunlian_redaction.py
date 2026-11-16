"""Public graph projection for proven workflow credential locations.

AgentNode reads group_params[].params[key=sql_agent].value.db_password into
SqlAgentParams (workflow/nodes/agent/agent.py). Do not blanket-delete keys named
password/api_key from user inputs: they can be legitimate business schemas.
"""

from copy import deepcopy


def redact_workflow_graph(graph):
    result = deepcopy(graph)
    if not isinstance(result, dict):
        return result
    for node in result.get("nodes", []):
        if not isinstance(node, dict) or not isinstance(node.get("data"), dict):
            continue
        for group in node["data"].get("group_params", []) or []:
            if not isinstance(group, dict):
                continue
            for parameter in group.get("params", []) or []:
                if (
                    isinstance(parameter, dict)
                    and parameter.get("key") == "sql_agent"
                    and isinstance(parameter.get("value"), dict)
                ):
                    parameter["value"].pop("db_password", None)
    return result


def _sql_secret_nodes(graph):
    """Only unique, consistently identified Agent nodes can retain a credential."""
    if not isinstance(graph, dict):
        return {}
    nodes, duplicates = {}, set()
    for node in graph.get("nodes", []) or []:
        if not isinstance(node, dict) or not isinstance(node.get("data"), dict):
            continue
        data = node["data"]
        node_id = node.get("id") or data.get("id")
        if not isinstance(node_id, str) or not node_id:
            continue
        if node_id in nodes:
            duplicates.add(node_id)
        nodes[node_id] = node
    result = {}
    for node_id, node in nodes.items():
        data = node["data"]
        if node_id in duplicates or data.get("type") != "agent" or data.get("id", node_id) != node_id:
            continue
        parameters = [
            parameter
            for group in data.get("group_params", []) or []
            if isinstance(group, dict)
            for parameter in group.get("params", []) or []
            if isinstance(parameter, dict) and parameter.get("key") == "sql_agent"
        ]
        if len(parameters) == 1 and isinstance(parameters[0].get("value"), dict):
            result[node_id] = parameters[0]["value"]
    return result


def merge_redacted_workflow_secrets(incoming, stored):
    """Restore omitted SQL passwords only for the same unambiguous Agent node.

    Explicit values (including empty or null) remain caller edits. Never infer
    credentials by list position or copy them to a different node identity.
    """
    result = deepcopy(incoming)
    original = _sql_secret_nodes(stored)
    for node_id, value in _sql_secret_nodes(result).items():
        previous = original.get(node_id)
        if "db_password" not in value and previous is not None and "db_password" in previous:
            value["db_password"] = deepcopy(previous["db_password"])
    return result


PUBLIC_METADATA_FIELDS = frozenset(
    {
        "id",
        "name",
        "description",
        "logo",
        "status",
        "is_current",
        "create_time",
        "update_time",
        "draft_revision",
        "versions",
        "allowed_actions",
    }
)


def redact_workflow_response(result, *, include_graph=True):
    """Preserve Owner error envelopes; project successful envelopes or raw records."""
    from fastapi.encoders import jsonable_encoder

    from bisheng.common.schemas.api import resp_200

    envelope = hasattr(result, "status_code") and hasattr(result, "data")
    if envelope and result.status_code != 200:
        return result
    payload = jsonable_encoder(result.data if envelope else result)
    if not isinstance(payload, dict):
        return result
    public = {key: value for key, value in payload.items() if key in PUBLIC_METADATA_FIELDS}
    if include_graph and "data" in payload:
        public["data"] = redact_workflow_graph(payload["data"])
    return resp_200(public) if envelope else public
