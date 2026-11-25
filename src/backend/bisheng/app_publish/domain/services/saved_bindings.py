"""Read business target selections without certifying the reverse index."""

from bisheng.app_publish.domain.schemas.app_manifest import CapabilityDeclaration
from bisheng.app_publish.domain.services.reference_extractor import extract_app_reference_requests
from bisheng.resource_reference.application.contracts import ReferenceSpec, TargetKey


def binding_payload(references):
    return {
        ref.slot_key: {"target_type": ref.target.target_type.value, "target_id": ref.target.target_id}
        for ref in references
    }


def saved_bindings(capabilities, injections, legacy_rows=()):
    """Absent old identities remain unresolved, never resolved by today's name.

    Legacy rows must already be scoped to the actual tenant/app/version by the
    caller. Only their original target IDs are consumed, not coverage proofs.
    """
    declaration = CapabilityDeclaration.model_validate(capabilities or {})
    requests = extract_app_reference_requests(declaration)
    explicit = isinstance(injections, dict) and "resource_bindings" in injections
    if explicit:
        raw = injections["resource_bindings"]
        raw = raw if isinstance(raw, dict) else {}
    else:
        raw, conflicts = {}, set()
        for row in legacy_rows:
            slot = row.slot_key
            item = {"target_type": row.target_type, "target_id": row.target_id}
            if slot in raw and raw[slot] != item:
                conflicts.add(slot)
            raw[slot] = item
        for slot in conflicts:
            raw.pop(slot, None)
    references, unresolved = [], []
    for request in requests:
        item = raw.get(request.slot_key)
        if not explicit and request.target_id is not None:
            item = {"target_type": request.target_type.value, "target_id": request.target_id}
        try:
            target = TargetKey(item["target_type"], item["target_id"])
            if target.target_type != request.target_type or (
                request.target_id is not None and target.target_id != request.target_id
            ):
                raise ValueError("saved target differs from declaration")
        except (TypeError, ValueError, KeyError):
            unresolved.append(request.slot_key)
        else:
            references.append(ReferenceSpec(request.slot_key, target))
    return declaration, tuple(references), tuple(unresolved)
