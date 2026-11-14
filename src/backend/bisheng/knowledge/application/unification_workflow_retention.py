"""Closed invalid workflow source facts; no authority or source binding writes."""

import json
from dataclasses import asdict

from bisheng.knowledge.domain.services.unification_fingerprints import digest

INVALID_WORKFLOW_ROOT = "retained_invalid_workflow_root"
INVALID_WORKFLOW_VERSION = "retained_invalid_workflow_version"


def invalid_workflow_root(root_key, parent):
    from bisheng.knowledge.application.unification_sources import RetiredInventoryRecord

    reason = "deleted_parent" if parent is None else "foreign_parent"
    checksum = digest({"root_key": asdict(root_key), "actual_parent": asdict(parent) if parent else None})
    return RetiredInventoryRecord(
        root_key, None, (INVALID_WORKFLOW_ROOT, reason, parent.tenant_id if parent else None), checksum, checksum
    )


def invalid_workflow_version(source_key, parent, version):
    from bisheng.knowledge.application.unification_sources import RetiredInventoryRecord
    from bisheng.resource_reference.application.contracts import SourceRootKey

    root_key = SourceRootKey(source_key.tenant_id, source_key.source_type, source_key.source_id)
    root = invalid_workflow_root(root_key, parent)
    return RetiredInventoryRecord(
        root_key,
        source_key,
        (INVALID_WORKFLOW_VERSION, root.lifecycle[1], version.flow_type, version.is_current, version.is_delete),
        digest({"data": json.loads(version.data_json)}),
        digest({"root": root.business_revision_digest, "version": asdict(version)}),
    )


def invalid_root(record):
    return bool(record.lifecycle and record.lifecycle[0] == INVALID_WORKFLOW_ROOT)


def invalid_version(record):
    return bool(record.lifecycle and record.lifecycle[0] == INVALID_WORKFLOW_VERSION)
