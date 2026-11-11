"""Actual six-source after facts for the stopped-service reference migration."""

import json
from dataclasses import asdict, replace

from bisheng.app_publish.domain.schemas.app_manifest import CapabilityDeclaration
from bisheng.app_publish.domain.services.reference_extractor import extract_app_references
from bisheng.assistant.domain.services.reference_extractor import extract_assistant_references
from bisheng.channel.domain.services.reference_extractor import extract_channel_sync_references
from bisheng.knowledge.application.unification_reference_state import (
    PHYSICAL_ROOT_ABSENT,
    blocked,
    validate_inventory_fact,
)
from bisheng.knowledge.application.unification_sources import knowledge_business_revision_digest
from bisheng.knowledge.domain.repositories.unification_inventory_repository import UnificationInventoryRepository
from bisheng.knowledge.domain.services.model_reference_extractor import extract_knowledge_model_references
from bisheng.knowledge.domain.services.unification_fingerprints import digest
from bisheng.llm.domain.services.default_reference_extractor import extract_model_default_references
from bisheng.resource_reference.application.contracts import (
    SourceType,
    normalize_references,
    reference_set_digest,
)
from bisheng.workflow.domain.services.reference_extractor import extract_workflow_version_references


class ReferenceAfterSources:
    def __init__(self, repository=None):
        self.repository = repository or UnificationInventoryRepository()

    async def aload(self, session, *, header, records, conversion=None):
        key = header.source_key
        root, version, children = await self.repository.aload_reference_source(session, source_key=key)
        kind, links = key.source_type, tuple(asdict(child) for child in children)
        if kind == SourceType.WORKFLOW_VERSION:
            if root.is_delete != 0 or version.is_delete not in (None, 0):
                blocked("source_retired_after_freeze")
            lifecycle = version.flow_type, version.is_current, version.is_delete
            configuration = {"data": json.loads(version.data_json)}
            references = extract_workflow_version_references(configuration["data"])
            revision = digest({"root": digest(asdict(root)), "version": asdict(version)})
        elif kind == SourceType.HOSTED_APP_VERSION:
            if root.state == "deleted":
                blocked("source_retired_after_freeze")
            lifecycle = version.version_no, version.kind, version.terminal_state
            configuration = {"capabilities": json.loads(version.capabilities_json)}
            references = extract_app_references(
                CapabilityDeclaration.model_validate(configuration["capabilities"]),
                resolved_targets={record.slot_key: record.target for record in records},
            )
            revision = digest({"root": digest(asdict(root)), "version": asdict(version)})
        elif kind == SourceType.ASSISTANT:
            if root.is_delete != 0:
                blocked("source_retired_after_freeze")
            lifecycle = root.status, root.is_delete
            configuration = {"model_name": root.model_name, "links": links}
            references = extract_assistant_references(
                model_name=root.model_name,
                knowledge_ids=tuple(child.knowledge_id for child in children if child.knowledge_id is not None),
            )
            revision = digest({"root": asdict(root), "links": links})
        elif kind == SourceType.CHANNEL_SYNC:
            lifecycle, configuration = (root.is_released,), {"syncs": links}
            references = extract_channel_sync_references(links)
            revision = digest({"root": asdict(root), "links": links})
        elif kind == SourceType.KNOWLEDGE:
            if root.type not in {0, 1, 3}:
                blocked("source_retired_after_freeze")
            lifecycle = root.type, root.state, root.is_released
            configuration = {
                "model": root.model,
                "model_transition": json.loads(root.model_transition_json) if root.model_transition_json else None,
            }
            references = extract_knowledge_model_references(**configuration)
            revision = knowledge_business_revision_digest(root)
        else:
            lifecycle = (root.key,)
            value = root.value if root.value in (None, "") else json.loads(root.value)
            configuration = {"key": root.key, "value": value}
            references = () if value in (None, "") else extract_model_default_references(root.key, value)
            revision = digest(asdict(root))
        expected_configuration, expected_revision = header.configuration_digest, header.business_revision_digest
        expected_lifecycle, expected_refs = header.lifecycle, header.reference_digest
        original = {(record.slot_key, record.target): record for record in records}
        if conversion is not None:
            if kind == SourceType.KNOWLEDGE:
                if conversion.knowledge_id != int(key.source_id):
                    blocked("knowledge_conversion_identity")
                expected_revision = conversion.after_inventory_business_revision_digest
                expected_lifecycle = conversion.target_type, header.lifecycle[1], conversion.target_is_released
            elif kind == SourceType.MODEL_DEFAULT:
                if conversion.row_id != root.id or conversion.key != key.source_id:
                    blocked("default_conversion_identity")
                expected_configuration = conversion.after_configuration_digest
                expected_revision = conversion.after_business_revision_digest
                expected_refs = conversion.after_refs_digest
                after_keys = {(reference.slot_key, reference.target) for reference in references}
                projected = {identity: record for identity, record in original.items() if identity in after_keys}
                original_slots = {(slot, target.target_id): record for (slot, target), record in original.items()}
                for item in conversion.provenance:
                    record = original_slots.get((item.source_slot, item.target_id))
                    if record is None:
                        blocked("default_provenance")
                    identity = item.target_slot, record.target
                    if identity in projected:
                        blocked("default_provenance_duplicate")
                    projected[identity] = record
                original = projected
            else:
                blocked("unexpected_source_conversion")
        references = normalize_references(tuple(references))
        if (digest(configuration), revision, lifecycle, reference_set_digest(references)) != (
            expected_configuration,
            expected_revision,
            expected_lifecycle,
            expected_refs,
        ):
            blocked("actual_source_after_changed")
        if set(original) != {(ref.slot_key, ref.target) for ref in references}:
            blocked("after_reference_membership")
        return replace(
            header,
            configuration_digest=expected_configuration,
            business_revision_digest=expected_revision,
            lifecycle=expected_lifecycle,
            reference_digest=expected_refs,
            reference_count=len(references),
        ), tuple((ref, original[(ref.slot_key, ref.target)]) for ref in references)

    async def averify_retired(self, session, *, header):
        from bisheng.knowledge.application.unification_workflow_retention import (
            invalid_root,
            invalid_version,
            invalid_workflow_root,
            invalid_workflow_version,
        )
        from bisheng.resource_reference.application.contracts import SourceKey

        if invalid_root(header):
            parent = await self.repository.aload_invalid_workflow_parent(session, root_key=header.root_key)
            actual = invalid_workflow_root(header.root_key, parent)
        elif invalid_version(header):
            parent, version = await self.repository.aload_invalid_workflow_version(
                session, source_key=header.source_key
            )
            actual = invalid_workflow_version(header.source_key, parent, version)
        else:
            actual = None
        if actual is not None:
            if (actual.lifecycle, actual.configuration_digest, actual.business_revision_digest) != (
                header.lifecycle,
                header.configuration_digest,
                header.business_revision_digest,
            ):
                blocked("invalid_workflow_source_changed")
            return

        if header.lifecycle == PHYSICAL_ROOT_ABSENT:
            validate_inventory_fact(header)
            if await self.repository.ainspect_hard_deleted_roots(session, root_keys=(header.root_key,)) != frozenset(
                {header.root_key}
            ):
                blocked("deleted_source_reappeared")
            return
        kind = header.root_key.source_type
        if header.source_key is None and kind in {SourceType.WORKFLOW_VERSION, SourceType.HOSTED_APP_VERSION}:
            root = await self.repository.aload_reference_root(session, root_key=header.root_key)
            if kind == SourceType.WORKFLOW_VERSION and root.is_delete != 1:
                blocked("retired_workflow_reappeared")
            if kind == SourceType.HOSTED_APP_VERSION and root.state != "deleted":
                blocked("retired_app_reappeared")
            configuration = revision = digest(asdict(root))
        else:
            key = header.source_key or SourceKey(header.root_key.tenant_id, kind, header.root_key.source_id, "current")
            root, version, children = await self.repository.aload_reference_source(session, source_key=key)
            links = tuple(asdict(child) for child in children)
            if kind == SourceType.WORKFLOW_VERSION:
                if root.is_delete != 1 and version.is_delete != 1:
                    blocked("retired_workflow_version_reappeared")
                configuration = digest({"data": json.loads(version.data_json)})
                revision = digest({"root": digest(asdict(root)), "version": asdict(version)})
            elif kind == SourceType.HOSTED_APP_VERSION:
                if root.state != "deleted":
                    blocked("retired_app_version_reappeared")
                configuration = digest({"capabilities": json.loads(version.capabilities_json)})
                revision = digest({"root": digest(asdict(root)), "version": asdict(version)})
            elif kind == SourceType.ASSISTANT:
                if root.is_delete != 1:
                    blocked("retired_assistant_reappeared")
                configuration = digest({"model_name": root.model_name, "links": links})
                revision = digest({"root": asdict(root), "links": links})
            elif kind == SourceType.KNOWLEDGE:
                if root.type != 2:
                    blocked("retired_knowledge_reappeared")
                configuration = digest(
                    {
                        "model": root.model,
                        "model_transition": json.loads(root.model_transition_json)
                        if root.model_transition_json
                        else None,
                    }
                )
                revision = knowledge_business_revision_digest(root)
            else:
                blocked("unexpected_retired_source_type")
        if (configuration, revision) != (header.configuration_digest, header.business_revision_digest):
            blocked("retired_business_changed")

    async def acensus(self, session, *, plan, tenant, reference_repository):
        from bisheng.knowledge.application.unification_workflow_retention import invalid_root

        actual_roots, actual_sources, actual_versions = await self.repository.acensus_reference_sources(session)
        expected_sources = frozenset(
            entry.header.source_key for entry in plan.sources if entry.header.source_key.tenant_id == tenant
        )
        expected_roots = {row.header.root_key for row in plan.roots if row.header.root_key.tenant_id == tenant}
        expected_roots.update(
            row.header.root_key
            for row in plan.retired
            if row.header.root_key.tenant_id == tenant
            and row.header.source_key is None
            and row.header.lifecycle != PHYSICAL_ROOT_ABSENT
            and not invalid_root(row.header)
        )
        expected_versions = {
            key
            for key in expected_sources
            if key.source_type in {SourceType.WORKFLOW_VERSION, SourceType.HOSTED_APP_VERSION}
        }
        expected_versions.update(
            row.header.source_key
            for row in plan.retired
            if row.header.root_key.tenant_id == tenant and row.header.source_key is not None
        )
        if (
            set(actual_roots) != expected_roots
            or actual_sources != expected_sources
            or actual_versions != expected_versions
        ):
            blocked("actual_source_universe_changed")
        # Empty version roots have no source to revalidate their original row.
        for row in plan.roots:
            header = row.header
            if header.root_key.tenant_id == tenant and header.retained_version_count == 0:
                if digest(asdict(actual_roots[header.root_key])) != header.configuration_digest:
                    blocked("empty_root_changed")
        empty = tuple(
            row.header
            for row in plan.roots
            if row.header.root_key.tenant_id == tenant and row.header.retained_version_count == 0
        )
        from bisheng.knowledge.application.unification_reference_state import parse_root_index, sql_value

        for offset in range(0, len(empty), 200):
            batch = empty[offset : offset + 200]
            actual = await reference_repository.aload_root_guards(
                session, root_keys=tuple(row.root_key for row in batch)
            )
            if any(
                sql_value(actual[row.root_key]) != parse_root_index(row.frozen_index)["root_guard"] for row in batch
            ):
                blocked("empty_root_guard_changed")
        await reference_repository.aassert_index_universe(
            session, source_keys=tuple(expected_sources), empty_roots=tuple(row.root_key for row in empty)
        )
