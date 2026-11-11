"""Stopped-service registered-source effects, separate from ordinary binding authority.

The migration coordinator owns verified frozen membership, physical after
facts and its Run checkpoint in the same transaction. Nothing here creates
Owner receipts or makes an incomplete migration ready.
"""

import hashlib
import json
from datetime import datetime

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.resource_reference.application.contracts import ReferenceSpec, TargetKey, reference_set_digest
from bisheng.resource_reference.domain.repositories.reference_backfill_repository import ReferenceBackfillRepository


def fingerprint(value):
    def scalar(item):
        if isinstance(item, datetime):
            return item.isoformat()
        raise TypeError("closed SQL scalar required")

    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False, default=scalar
        ).encode()
    ).hexdigest()


def blocked(reason):
    raise KnowledgeOperationPlanConflictError(reason="reference_registered_backfill_" + reason)


def _identity(row):
    return row["slot_key"], row["target_type"], row["target_id"]


def _guard_root(root, baseline, revision):
    if baseline is not None:
        expected = {**baseline, "source_revision": revision}
        if root != baseline and root != expected:
            blocked("root_changed")
    elif root is not None and (
        root["source_revision"] != revision
        or root["source_version"] != "__root__"
        or root["record_kind"] != "root_guard"
        or root["effective"] is not False
        or root["ready"] is not False
        or root["extractor_version"] != "root-guard-v1"
        or root["digest"] != reference_set_digest(())
        or root["digest_version"] != "sha256-reference-set-v1"
    ):
        blocked("unregistered_root")


class RegisteredReferenceBackfill:
    def __init__(self, repository=None):
        self.repository = repository or ReferenceBackfillRepository()

    async def aprocess(
        self, session, *, source_key, frozen_index, rows, extractor_version, reference_digest, root_revision, write
    ):
        """Exact original or exact complete after; partial states always reject."""
        root, source, actual = await self.repository.aload_raw_snapshot(
            session, source_key=source_key, for_update=write
        )
        # Frozen times are canonical SQL strings; compare all original raw columns.
        normalized = json.loads(json.dumps((root, source, actual), default=lambda item: item.isoformat()))
        _guard_root(normalized[0], frozen_index["root_head"], root_revision)
        identities = {_identity(row) for row in rows}
        if (
            len(identities) != len(rows)
            or reference_set_digest(
                tuple(ReferenceSpec(row["slot_key"], TargetKey(row["target_type"], row["target_id"])) for row in rows)
            )
            != reference_digest
        ):
            blocked("template_reference_digest")
        if write:
            if normalized[1] != frozen_index["source_head"] or (len(actual), fingerprint(actual)) != (
                frozen_index["raw_count"],
                frozen_index["raw_digest"],
            ):
                blocked("original_source_changed")
            root, source, actual = await self.repository.awrite_registered_source(
                session,
                source_key=source_key,
                expected_snapshot=(root, source, actual),
                root_revision=root_revision,
                rows=rows,
                extractor_version=extractor_version,
                reference_digest=reference_digest,
            )
        if (
            source is None
            or root is None
            or (
                source["record_kind"],
                source["source_revision"],
                source["extractor_version"],
                source["digest"],
                source["digest_version"],
                source["effective"],
                source["ready"],
                root["source_revision"],
            )
            != (
                "source",
                root_revision,
                extractor_version,
                reference_digest,
                "sha256-reference-set-v1",
                True,
                True,
                root_revision,
            )
        ):
            blocked("after_head_changed")
        original = {_identity(row): row for row in actual}
        if set(original) != identities:
            blocked("after_binding_membership")
        for template in rows:
            current = original[_identity(template)]
            if any(current[name] != value for name, value in template.items()):
                blocked("after_binding_changed")
            if (current["tenant_id"], current["source_type"], current["source_id"], current["source_version"]) != (
                source_key.tenant_id,
                source_key.source_type.value,
                source_key.source_id,
                source_key.source_version,
            ):
                blocked("after_source_identity")
        return fingerprint((root, source, actual))
