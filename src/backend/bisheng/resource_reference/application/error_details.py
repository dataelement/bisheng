"""Bounded diagnostics derived only from an already authorized selection."""

import json


def reference_error_details(references, states, graph=None):
    """Keep exact target states and all affected node locations without name lookups."""
    nodes = {
        str(node["data"]["id"]): node["data"]
        for node in (graph or {}).get("nodes", [])
        if isinstance(node, dict) and isinstance(node.get("data"), dict) and "id" in node["data"]
    }
    details = []
    for reference in references:
        state = states.get(reference.target)
        if state is None:
            continue
        detail = {
            "resource_type": reference.target.target_type.value,
            "target_id": reference.target.target_id,
            "state": str(state),
        }
        for node_id, node in nodes.items():
            prefix = f"node:{node_id}."
            if not reference.slot_key.startswith(prefix):
                continue
            parameter = reference.slot_key[len(prefix) :]
            if parameter == "qa_knowledge_id":
                detail["resource_type"] = "qa_knowledge"
            elif parameter == "advanced_retrieval_switch.rerank_model":
                detail["resource_type"] = "rerank_model"
            detail.update(node_id=node_id[:100], node_name=(str(node.get("name") or "").strip() or node_id)[:100])
            break
        if detail not in details:
            details.append(detail)
        if len(details) == 5:
            break
    return details


def snapshot_reference_errors(snapshot, facts):
    payload = json.loads(snapshot.payload_json)
    return reference_error_details(
        snapshot.references,
        {fact.key: fact.state if str(fact.state) != "valid" else "unavailable" for fact in facts if not fact.is_valid},
        payload.get("graph"),
    )
