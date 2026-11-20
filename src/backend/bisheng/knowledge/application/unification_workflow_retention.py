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


INVALID_WORKFLOW_CONFIGURATION = "retained_invalid_workflow_configuration"


def unextractable_workflow_configuration(version):
    from bisheng.workflow.domain.services.reference_extractor import unextractable_workflow_configuration as classify

    return classify(version.data_json, flow_type=version.flow_type, is_delete=version.is_delete)


def invalid_workflow_configuration(source_key, parent_digest, version):
    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
    from bisheng.knowledge.application.unification_sources import RetiredInventoryRecord
    from bisheng.resource_reference.application.contracts import SourceRootKey, SourceType

    if (
        source_key.source_type != SourceType.WORKFLOW_VERSION
        or source_key.tenant_id != version.tenant_id
        or source_key.source_id != version.flow_id
        or source_key.source_version != str(version.id)
        or not unextractable_workflow_configuration(version)
        or version.is_current not in (None, 0, 1)
    ):
        raise KnowledgeOperationPlanConflictError(reason="unification_invalid_workflow_configuration_changed")
    return RetiredInventoryRecord(
        SourceRootKey(source_key.tenant_id, source_key.source_type, source_key.source_id),
        source_key,
        (INVALID_WORKFLOW_CONFIGURATION, version.flow_type, version.is_current, version.is_delete),
        digest({"data_json": version.data_json}),
        digest({"parent": parent_digest, "version": asdict(version)}),
    )


def invalid_configuration(record):
    return bool(record.lifecycle and record.lifecycle[0] == INVALID_WORKFLOW_CONFIGURATION)
