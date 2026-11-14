"""Closed original index/deletion facts for formal M2, without bind authority."""

import json
from datetime import datetime

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.domain.repositories.reference_legacy_evidence_repository import KnowledgeLegacyEvidenceRepository
from bisheng.knowledge.domain.services.unification_fingerprints import canonical, digest
from bisheng.resource_reference.application.contracts import (
    ReferenceSpec,
    SourceKey,
    SourceRootKey,
    TargetKey,
    TargetType,
    reference_set_digest,
)
from bisheng.resource_reference.domain.repositories.reference_backfill_repository import ReferenceBackfillRepository

_HEAD = frozenset(
    "id tenant_id source_type source_id source_version record_kind source_revision extractor_version digest digest_version effective ready create_time update_time".split()
)
_BINDING = frozenset(
    "id tenant_id source_type source_id source_version slot_key target_type target_id target_tenant_id target_space_id source_revision legacy_invalid_reason legacy_run_id legacy_evidence_key create_time update_time".split()
)
_TOMBSTONE = frozenset(
    "id tenant_id target_type target_id target_tenant_id operation_id operation_type stage actor_type actor_id deleted_at create_time update_time".split()
)
_INDEX = frozenset({"root_head", "source_head", "raw_count", "raw_digest"})
_STATE = frozenset({"original", "target_tombstones", "ancestor_tombstones", "legacy"})
PHYSICAL_ROOT_ABSENT = ("physical_root_absent",)


def absent_root_digest(key):
    return digest(
        {"tenant_id": key.tenant_id, "source_type": key.source_type.value, "source_id": key.source_id, "exists": False}
    )


def inactive_index_state(key, heads, raw_count):
    """Recognize only the exact committed R2 hard-delete empty-set shape."""
    from bisheng.channel.domain.services.reference_extractor import CHANNEL_SYNC_REFERENCE_EXTRACTOR_VERSION
    from bisheng.knowledge.domain.services.model_reference_extractor import KNOWLEDGE_MODEL_REFERENCE_EXTRACTOR_VERSION
    from bisheng.resource_reference.application.contracts import SourceType

    versions = {
        SourceType.KNOWLEDGE: KNOWLEDGE_MODEL_REFERENCE_EXTRACTOR_VERSION,
        SourceType.CHANNEL_SYNC: CHANNEL_SYNC_REFERENCE_EXTRACTOR_VERSION,
    }
    if key.source_type not in versions or len(heads) != 2 or raw_count != 0:
        blocked("unknown_inactive_index")
    heads = tuple(_row(sql_value(dict(row)), _HEAD) for row in heads)
    root = next((row for row in heads if row["source_version"] == "__root__"), None)
    source = next((row for row in heads if row["source_version"] == "current"), None)
    if (
        root is None
        or source is None
        or any(
            (row["tenant_id"], row["source_type"], row["source_id"])
            != (key.tenant_id, key.source_type.value, key.source_id)
            or row["digest"] != reference_set_digest(())
            or row["effective"]
            for row in heads
        )
        or root["ready"]
        or not source["ready"]
        or root["source_revision"] <= 0
        or root["source_revision"] != source["source_revision"]
        or root["extractor_version"] != "root-guard-v1"
        or source["extractor_version"] != versions[key.source_type]
    ):
        blocked("unknown_inactive_index")
    state = {"root_head": root, "source_heads": [source], "raw_count": 0, "raw_digest": digest(()), "legacy": []}
    parse_retired(state)
    return canonical(state).decode()


def blocked(reason):
    raise KnowledgeOperationPlanConflictError(reason="migration_reference_state_" + reason)


def _text(value):
    return type(value) is str and bool(value) and "\x00" not in value


def _hash(value):
    return type(value) is str and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def sql_value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if type(value) is dict:
        return {key: sql_value(item) for key, item in value.items()}
    if type(value) in (tuple, list):
        return [sql_value(item) for item in value]
    if value is None or type(value) in (str, int, bool):
        return value
    blocked("non_scalar_fact")


def _row(row, names):
    if type(row) is not dict or set(row) != names:
        blocked("closed_sql_row")
    for name, value in row.items():
        if value is not None and type(value) not in (str, int, bool):
            blocked("row_scalar")
        if (
            name in {"id", "tenant_id", "target_tenant_id"}
            and value is not None
            and (type(value) is not int or value <= 0)
        ):
            blocked("row_identifier")
        if name in {"create_time", "update_time", "deleted_at"} and value is not None:
            try:
                if type(value) is not str or datetime.fromisoformat(value).isoformat() != value:
                    blocked("row_timestamp")
            except ValueError as error:
                raise KnowledgeOperationPlanConflictError(reason="migration_reference_state_row_timestamp") from error
    if any(row[name] is None for name in ("create_time", "update_time")):
        blocked("missing_raw_timestamp")
    try:
        if names in (_HEAD, _BINDING):
            source = SourceRootKey(row["tenant_id"], row["source_type"], row["source_id"])
            if row["source_version"] != "__root__":
                SourceKey(source.tenant_id, source.source_type, source.source_id, row["source_version"])
        if names in (_BINDING, _TOMBSTONE):
            TargetKey(row["target_type"], row["target_id"])
    except (TypeError, ValueError) as error:
        raise KnowledgeOperationPlanConflictError(reason="migration_reference_state_identity") from error
    if names == _HEAD:
        if (
            type(row["source_revision"]) is not int
            or row["source_revision"] < 0
            or type(row["effective"]) is not bool
            or type(row["ready"]) is not bool
            or not _hash(row["digest"])
            or row["digest_version"] != "sha256-reference-set-v1"
        ):
            blocked("head_facts")
        root = row["source_version"] == "__root__"
        if row["record_kind"] != ("root_guard" if root else "source") or (root and (row["effective"] or row["ready"])):
            blocked("head_kind")
    if names == _BINDING:
        if row["target_space_id"] is not None:
            if row["target_type"] != "knowledge_file":
                blocked("non_file_parent_metadata")
            TargetKey(TargetType.KNOWLEDGE_SPACE, row["target_space_id"])
        if type(row["source_revision"]) is not int or row["source_revision"] < 0 or row["source_version"] == "__root__":
            blocked("binding_revision")
        legacy = row["legacy_invalid_reason"], row["legacy_run_id"], row["legacy_evidence_key"]
        if legacy != (None, None, None) and (
            legacy[0] != "target_missing" or not all(_text(item) for item in legacy[1:])
        ):
            blocked("legacy_bundle")
        if row["target_tenant_id"] is None and legacy[0] is None:
            blocked("binding_owner_unknown")
    if names == _TOMBSTONE:
        if (
            row["tenant_id"] != row["target_tenant_id"]
            or row["stage"] not in {"deleting", "deleted"}
            or any(not _text(row[name]) for name in ("operation_id", "operation_type", "actor_type", "actor_id"))
        ):
            blocked("tombstone_facts")
        if (row["stage"] == "deleted") != (row["deleted_at"] is not None):
            blocked("tombstone_time")
    return row


def parse_frozen(value, *, index=False, allow_none=False):
    if value is None and allow_none:
        return None
    if type(value) is str:
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError) as error:
            raise KnowledgeOperationPlanConflictError(reason="migration_reference_state_json") from error
        if canonical(parsed).decode() != value:
            blocked("noncanonical_json")
        value = parsed
    if type(value) is not dict or set(value) != (_INDEX if index else _STATE):
        blocked("formal_frozen_state_required_new_run")
    if index:
        for name in ("root_head", "source_head"):
            if value[name] is not None:
                _row(value[name], _HEAD)
        if type(value["raw_count"]) is not int or value["raw_count"] < 0 or not _hash(value["raw_digest"]):
            blocked("raw_inventory")
    else:
        if value["original"] is not None:
            _row(value["original"], _BINDING)
        for name in ("target_tombstones", "ancestor_tombstones"):
            if type(value[name]) is not list:
                blocked("deletion_facts")
            for row in value[name]:
                _row(row, _TOMBSTONE)
        legacy = value["legacy"]
        if legacy is not None and (
            type(legacy) is not dict
            or set(legacy) != {"run_id", "baseline_hash", "evidence_key"}
            or not _text(legacy["run_id"])
            or not _hash(legacy["baseline_hash"])
            or not _text(legacy["evidence_key"])
        ):
            blocked("legacy_proof")
    return value


def frozen_json(value, *, index=False):
    value = sql_value(value)
    parse_frozen(value, index=index)
    return canonical(value).decode()


class OriginalReferenceState:
    def __init__(self, *, repository=None, legacy=None):
        self.repository = repository or ReferenceBackfillRepository()
        self.legacy = legacy or KnowledgeLegacyEvidenceRepository()

    async def acapture(self, session, *, source_key, references, physical, tombstone_cache, snapshot):
        root, source, rows = snapshot
        indexed, by_target, legacy_cache = {}, {}, {}
        for row in rows:
            identity = row["slot_key"], row["target_type"], row["target_id"]
            if identity in indexed:
                blocked("duplicate_original_binding")
            indexed[identity] = row
            by_target.setdefault((row["target_type"], row["target_id"]), []).append(row)
        if source is None and rows:
            blocked("original_rows_without_head")
        if source is not None:
            actual_specs = tuple(
                ReferenceSpec(row["slot_key"], TargetKey(row["target_type"], row["target_id"])) for row in rows
            )
            if (
                root is None
                or root["source_revision"] < source["source_revision"]
                or any(row["source_revision"] != source["source_revision"] for row in rows)
                or source["digest"] != reference_set_digest(actual_specs)
                or set(indexed)
                != {(ref.slot_key, ref.target.target_type.value, ref.target.target_id) for ref in references}
            ):
                blocked("original_index_configuration_mismatch")
        requested = {ref.target for ref in references}
        for ref in references:
            original = indexed.get((ref.slot_key, ref.target.target_type.value, ref.target.target_id))
            parent = physical[ref.target].knowledge_id if ref.target.target_type == TargetType.KNOWLEDGE_FILE else None
            parent = str(parent) if parent is not None else original["target_space_id"] if original else None
            if parent is not None:
                requested.add(TargetKey(TargetType.KNOWLEDGE_SPACE, parent))
        unseen = tuple(sorted(requested - tombstone_cache.keys(), key=lambda key: key.lock_order_key))
        for offset in range(0, len(unseen), 200):
            batch = unseen[offset : offset + 200]
            loaded = await self.repository.aload_tombstones(session, targets=batch)
            grouped = {}
            for row in loaded:
                grouped.setdefault((row["target_type"], row["target_id"]), []).append(row)
            for key in batch:
                values = tuple(grouped.get((key.target_type.value, key.target_id), ()))
                if len(values) > 1:
                    blocked("multiple_target_owners")
                tombstone_cache[key] = values
        state = {}
        for ref in references:
            original = indexed.get((ref.slot_key, ref.target.target_type.value, ref.target.target_id))
            parent = physical[ref.target].knowledge_id if ref.target.target_type == TargetType.KNOWLEDGE_FILE else None
            parent = str(parent) if parent is not None else original["target_space_id"] if original else None
            inherited = (
                tombstone_cache.get(TargetKey(TargetType.KNOWLEDGE_SPACE, parent), ()) if parent is not None else ()
            )
            proof = None
            if original and original["legacy_invalid_reason"] is not None:
                evidence_identity = (ref.target, original["legacy_run_id"], original["legacy_evidence_key"])
                if evidence_identity not in legacy_cache:
                    run_id, baseline_hash, evidence_key = await self.legacy.aload_snapshot_evidence(
                        session,
                        source_key,
                        ref.target,
                        rows=by_target[(ref.target.target_type.value, ref.target.target_id)],
                        run_id=original["legacy_run_id"],
                        evidence_key=original["legacy_evidence_key"],
                    )
                    legacy_cache[evidence_identity] = {
                        "run_id": run_id,
                        "baseline_hash": baseline_hash,
                        "evidence_key": evidence_key,
                    }
                proof = legacy_cache[evidence_identity]
            state[(ref.slot_key, ref.target.target_type.value, ref.target.target_id)] = frozen_json(
                {
                    "original": original,
                    "target_tombstones": tombstone_cache[ref.target],
                    "ancestor_tombstones": inherited if ref.target.target_type == TargetType.KNOWLEDGE_FILE else (),
                    "legacy": proof,
                }
            )
        return frozen_json(
            {"root_head": root, "source_head": source, "raw_count": len(rows), "raw_digest": digest(rows)}, index=True
        ), state


def parse_retired(value):
    if type(value) is str:
        parsed = json.loads(value)
        if canonical(parsed).decode() != value:
            blocked("retired_noncanonical")
        value = parsed
    if type(value) is not dict or set(value) != {"root_head", "source_heads", "raw_count", "raw_digest", "legacy"}:
        blocked("retired_index_required_new_run")
    if value["root_head"] is not None:
        _row(value["root_head"], _HEAD)
    if type(value["source_heads"]) is not list or type(value["legacy"]) is not list:
        blocked("retired_lists")
    for row in value["source_heads"]:
        _row(row, _HEAD)
        if row["source_version"] == "__root__":
            blocked("retired_source_head")
    if type(value["raw_count"]) is not int or value["raw_count"] < 0 or not _hash(value["raw_digest"]):
        blocked("retired_raw_inventory")
    for proof in value["legacy"]:
        if type(proof) is not dict or set(proof) != {
            "source_type",
            "source_id",
            "source_version",
            "target_type",
            "target_id",
            "run_id",
            "baseline_hash",
            "evidence_key",
        }:
            blocked("retired_legacy_shape")
        TargetKey(proof["target_type"], proof["target_id"])
        if not _hash(proof["baseline_hash"]) or not all(
            _text(proof[name]) for name in ("source_type", "source_id", "source_version", "run_id", "evidence_key")
        ):
            blocked("retired_legacy_proof")
    return value


async def retired_index(session, *, repository, legacy, root_key, source_key=None):
    if source_key is None:
        heads, rows = await repository.aload_raw_root(session, root_key=root_key)
        root = next((row for row in heads if row["source_version"] == "__root__"), None)
        sources = tuple(row for row in heads if row["source_version"] != "__root__")
    else:
        root, source, rows = await repository.aload_raw_snapshot(session, source_key=source_key)
        sources = (source,) if source else ()
    grouped, proofs = {}, []
    for row in rows:
        _row(sql_value(row), _BINDING)
        if row["legacy_invalid_reason"] is not None:
            grouped.setdefault(
                (row["source_type"], row["source_id"], row["source_version"], row["target_type"], row["target_id"]), []
            ).append(row)
    for identity, originals in grouped.items():
        kind, ident, version, target_kind, target_id = identity
        original = originals[0]
        run, baseline, evidence = await legacy.aload_snapshot_evidence(
            session,
            SourceKey(root_key.tenant_id, kind, ident, version),
            TargetKey(target_kind, target_id),
            rows=originals,
            run_id=original["legacy_run_id"],
            evidence_key=original["legacy_evidence_key"],
        )
        proofs.append(
            dict(zip(("source_type", "source_id", "source_version", "target_type", "target_id"), identity, strict=True))
            | {"run_id": run, "baseline_hash": baseline, "evidence_key": evidence}
        )
    value = sql_value(
        {
            "root_head": root,
            "source_heads": sources,
            "raw_count": len(rows),
            "raw_digest": digest(rows),
            "legacy": proofs,
        }
    )
    parse_retired(value)
    return canonical(value).decode()


def parse_root_index(value):
    if type(value) is str:
        parsed = json.loads(value)
        if canonical(parsed).decode() != value:
            blocked("root_noncanonical")
        value = parsed
    if type(value) is not dict or set(value) != {"root_guard"}:
        blocked("root_guard_fact_required_new_run")
    if value["root_guard"] is not None:
        _row(value["root_guard"], _HEAD)
        if value["root_guard"]["source_version"] != "__root__":
            blocked("root_guard_version")
    return value


def validate_inventory_fact(record):
    """Formal consumers refuse old/missing original facts before SQL conversion."""
    from bisheng.knowledge.application.unification_sources import (
        ReferenceInventoryRecord,
        RetiredInventoryRecord,
        RootInventoryRecord,
        SourceInventoryRecord,
    )

    if type(record) is SourceInventoryRecord:
        parse_frozen(record.frozen_index, index=True)
    elif type(record) is ReferenceInventoryRecord:
        parse_frozen(record.frozen_state)
    elif type(record) is RootInventoryRecord and record.retained_version_count == 0:
        parse_root_index(record.frozen_index)
    elif type(record) is RetiredInventoryRecord and record.source_key is None:
        state = parse_retired(record.frozen_index)
        if record.lifecycle == PHYSICAL_ROOT_ABSENT:
            heads = [state["root_head"], *state["source_heads"]]
            if (
                state["root_head"] is None
                or state["raw_digest"] != digest(())
                or state["legacy"]
                or inactive_index_state(record.root_key, heads, state["raw_count"]) != record.frozen_index
                or record.configuration_digest != absent_root_digest(record.root_key)
                or record.business_revision_digest != record.configuration_digest
            ):
                blocked("invalid_absent_index_fact")
