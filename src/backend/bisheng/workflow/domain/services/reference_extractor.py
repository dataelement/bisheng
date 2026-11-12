"""Extract saved workflow slots without loading or executing node services.

The caller supplies one FlowVersion.data, including drafts and noncurrent
versions. Flow.data is a mirror, not a second reference source. This module
does not resolve target existence, tenancy or permission; target Owners do so
inside the binding transaction.
"""

from collections.abc import Mapping

from bisheng.resource_reference.application.contracts import (
    ReferenceSpec,
    TargetKey,
    TargetType,
    normalize_references,
)

WORKFLOW_REFERENCE_EXTRACTOR_VERSION = "workflow-version-v1"

_MODEL_NODE_TYPES = frozenset({"llm", "rag", "agent"})
_KNOWLEDGE_NODE_SLOTS = {"rag": "knowledge", "knowledge_retriever": "knowledge", "agent": "knowledge_id"}
_RERANK_NODE_TYPES = frozenset({"rag", "knowledge_retriever"})
_SUPPORTED_NODE_TYPES = _MODEL_NODE_TYPES | _KNOWLEDGE_NODE_SLOTS.keys() | {"qa_retriever"}


def _mapping(value: object, label: str) -> Mapping:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _list(value: object, label: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be an array")
    return value


def _parameters(node: Mapping) -> dict[str, object]:
    """Match BaseNode.init_data: the last repeated parameter key wins."""
    result = {}
    for group in _list(node.get("group_params") or [], "node group_params"):
        for item in _list(_mapping(group, "node group").get("params", []), "node params"):
            parameter = _mapping(item, "node parameter")
            key = parameter.get("key", "")
            if not isinstance(key, str):
                raise ValueError("node parameter key must be text")
            result[key] = parameter.get("value")
    return result


def _target(value: object, target_type: TargetType) -> TargetKey | None:
    if isinstance(value, bool):
        raise ValueError("reference target ID must not be boolean")
    # Empty controls and the persisted unselected model sentinel are valid
    # incomplete drafts. A nonempty malformed selection must never disappear.
    if value is None or value == "" or value == 0 or value == "0":
        return None
    return TargetKey(target_type, value)


def _selection_targets(value: object) -> tuple[TargetKey, ...]:
    if value is None:
        return ()
    selected = _mapping(value, "knowledge selection")
    selection_type = selected.get("type", "knowledge")
    if selection_type not in {"knowledge", "space"}:
        # Temporary documents are runtime variable outputs, not persisted
        # KnowledgeFile IDs. Never interpret their expressions as entity IDs.
        return ()
    return _selected_keys(selected.get("value") or [])


def _selected_keys(value: object) -> tuple[TargetKey, ...]:
    targets = []
    for item in _list(value, "knowledge selections"):
        if item is None:
            continue
        selected = _mapping(item, "knowledge selection item")
        target = _target(selected.get("key"), TargetType.KNOWLEDGE_SPACE)
        if target is not None:
            targets.append(target)
    return tuple(targets)


def _node_references(node_type: str, params: Mapping) -> tuple[tuple[str, TargetKey], ...]:
    references = []
    if node_type in _MODEL_NODE_TYPES:
        model = _target(params.get("model_id"), TargetType.MODEL)
        if model is not None:
            references.append(("model_id", model))
    if node_type in _KNOWLEDGE_NODE_SLOTS:
        slot = _KNOWLEDGE_NODE_SLOTS[node_type]
        references.extend((slot, target) for target in _selection_targets(params.get(slot)))
    if node_type == "qa_retriever":
        references.extend(("qa_knowledge_id", target) for target in _selected_keys(params.get("qa_knowledge_id") or []))
    if node_type in _RERANK_NODE_TYPES:
        advanced = _mapping(params.get("advanced_retrieval_switch") or {}, "advanced retrieval settings")
        rerank = _target(advanced.get("rerank_model"), TargetType.MODEL)
        if rerank is not None:
            references.append(("advanced_retrieval_switch.rerank_model", rerank))
    # metadata_filter.document_id is a generic comparison expression, not an
    # Owner-resolved physical file/version selector. Likewise, arbitrary prompt,
    # tool, task, history and output JSON never introduces a binding slot.
    return tuple(references)


def extract_workflow_version_references(data: Mapping[str, object] | None) -> tuple[ReferenceSpec, ...]:
    """Return one saved version's deterministic complete reference set.

    Stable node.data.id is the identity consumed by GraphEngine. Version/root
    identity and lifecycle are supplied by the business transaction, not by
    arbitrary graph fields such as status or a copied Flow.data mirror.
    """
    if data is None or data == {}:
        return ()
    graph = _mapping(data, "workflow data")
    nodes = _list(graph.get("nodes"), "workflow nodes")
    references = []
    node_ids = set()
    for raw_node in nodes:
        node = _mapping(_mapping(raw_node, "workflow node").get("data", {}), "workflow node data")
        node_type = node.get("type")
        if node_type not in _SUPPORTED_NODE_TYPES:
            continue
        slots = _node_references(node_type, _parameters(node))
        node_id = node.get("id", "")
        if not isinstance(node_id, str) or not node_id or "\x00" in node_id:
            if slots:
                raise ValueError("a reference-bearing workflow node needs a stable node ID")
            continue
        if node_id in node_ids:
            raise ValueError("duplicate workflow node ID")
        node_ids.add(node_id)
        references.extend(ReferenceSpec(f"node:{node_id}.{slot}", target) for slot, target in slots)
    return normalize_references(tuple(references))
