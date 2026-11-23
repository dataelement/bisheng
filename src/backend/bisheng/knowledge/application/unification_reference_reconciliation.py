"""Closed offline reference observations; none of these facts grant authority."""

import json
import re
from dataclasses import asdict, fields, replace

from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope
from bisheng.knowledge.application.unification_reference_plan import ReferenceReconciliation
from bisheng.knowledge.application.unification_reference_state import blocked, sql_value
from bisheng.knowledge.domain.repositories import unification_inventory_repository as rows
from bisheng.knowledge.domain.services.unification_fingerprints import canonical, digest
from bisheng.resource_reference.application.backfill import fingerprint
from bisheng.resource_reference.application.contracts import SourceKey, SourceType, TargetKey, TargetType

SEMANTICS = "f118-source-semantics-v1"
DIRECTORY = "f118-source-semantics-directory-v1"
_FIELDS = {
    rows.WorkflowRootRow: "id tenant_id user_id flow_type status is_delete update_time data_json",
    rows.WorkflowVersionRow: "id flow_id tenant_id flow_type is_current is_delete update_time data_json",
    rows.AppRootRow: "id tenant_id owner_user_id state current_version_id pending_version_id update_time",
    rows.AppVersionRow: "id app_id tenant_id version_no kind terminal_state update_time capabilities_json",
    rows.AssistantRow: "id tenant_id user_id status is_delete update_time model_name",
    rows.AssistantLinkRow: "id assistant_id tenant_id knowledge_id tool_id flow_id update_time",
    rows.ChannelRow: "id tenant_id user_id is_released update_time",
    rows.ChannelSyncRow: "id channel_id tenant_id sub_channel_name knowledge_space_id folder_id is_enabled user_id update_time",
    rows.KnowledgeRow: "id tenant_id type name user_id state is_released auth_type is_shared model model_transition_json model_config_revision index_generation index_name collection_name processing_config_version metadata_schema_revision migration_origin update_time",
    rows.DefaultRow: "id tenant_id key value update_time",
}
_LAYOUT = {
    SourceType.WORKFLOW_VERSION: (rows.WorkflowRootRow, rows.WorkflowVersionRow, None),
    SourceType.HOSTED_APP_VERSION: (rows.AppRootRow, rows.AppVersionRow, None),
    SourceType.ASSISTANT: (rows.AssistantRow, None, rows.AssistantLinkRow),
    SourceType.CHANNEL_SYNC: (rows.ChannelRow, None, rows.ChannelSyncRow),
    SourceType.KNOWLEDGE: (rows.KnowledgeRow, None, None),
    SourceType.MODEL_DEFAULT: (rows.DefaultRow, None, None),
}


def _hash(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _key(value):
    if type(value) is not dict or set(value) != {"tenant_id", "source_type", "source_id", "source_version"}:
        blocked("reconciliation_source_key")
    try:
        return SourceKey(**value)
    except (ValueError, TypeError) as error:
        from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError

        raise KnowledgeOperationPlanConflictError(
            reason="migration_reference_state_reconciliation_source_key"
        ) from error


def _row(value, expected, *, clock=False):
    if expected is None:
        if value is not None:
            blocked("semantic_row_layout")
        return None
    if type(value) is not expected or {field.name for field in fields(value)} != set(_FIELDS[expected].split()):
        blocked("semantic_row_layout")
    observed = sql_value(asdict(value))
    return {name: item for name, item in observed.items() if not clock or name != "update_time"}


async def collect_semantics(session, *, source_keys, repository=None):
    """Collect one <=200-source tenant page from the supplied raw/after port."""
    tenant = get_current_tenant_id()
    if (
        type(source_keys) is not tuple
        or len(source_keys) > 200
        or len(set(source_keys)) != len(source_keys)
        or any(type(key) is not SourceKey or key.tenant_id != tenant for key in source_keys)
    ):
        blocked("semantic_source_scope")
    repository = repository or rows.UnificationInventoryRepository()
    batch_reader = getattr(repository, "aload_reference_sources", None)
    snapshots = await batch_reader(session, source_keys=source_keys) if source_keys and callable(batch_reader) else None
    if snapshots is not None and set(snapshots) != set(source_keys):
        blocked("semantic_source_batch_incomplete")
    observed = []
    for key in source_keys:
        root, version, children = (
            snapshots[key]
            if snapshots is not None
            else await repository.aload_reference_source(session, source_key=key)
        )
        observed.append(snapshot_semantics(key, root, version, children))
    return {"schema_version": 1, "semantic_contract": SEMANTICS, "tenant_id": tenant, "sources": observed}


def snapshot_semantics(key, root, version, children):
    root_type, version_type, child_type = _LAYOUT[key.source_type]
    root_before, version_before = _row(root, root_type), _row(version, version_type)
    links = [_row(child, child_type) for child in children]
    semantic = {
        "root": _row(root, root_type, clock=True),
        "version": _row(version, version_type, clock=True),
        "children": links,
    }
    return {
        "key": asdict(key),
        "semantic_digest": digest(semantic),
        "business_digest": digest({"root": root_before, "version": version_before, "children": links}),
    }


async def load_semantics(store, frozen, descriptor):
    """Validate the complete bounded directory DAG, leaf scopes and key closure."""
    if descriptor is None:
        return {}
    result, visited = {}, set()

    async def visit(ref, depth=0):
        if (
            type(ref) is not dict
            or set(ref) != {"object_key", "sha256"}
            or type(ref["object_key"]) is not str
            or not _hash(ref["sha256"])
        ):
            blocked("semantic_directory_descriptor")
        if depth > 64 or ref.get("object_key") in visited:
            blocked("semantic_directory_graph")
        visited.add(ref.get("object_key"))
        envelope = json.loads(await store.aload_canonical(ref, run_id=frozen.run_id, kind="verification"))
        if len(envelope["records"]) != 1:
            blocked("semantic_directory_envelope")
        value = envelope["records"][0]
        if type(value) is not dict or type(value.get("schema_version")) is not int or value.get("schema_version") != 1:
            blocked("semantic_directory_schema")
        start = set(result)
        if value.get("semantic_contract") == DIRECTORY:
            if (
                set(value) != {"schema_version", "semantic_contract", "pages"}
                or type(value["pages"]) is not list
                or not 1 <= len(value["pages"]) <= 128
            ):
                blocked("semantic_directory_schema")
            for page in value["pages"]:
                if (
                    type(page) is not dict
                    or set(page) != {"tenant_id", "source_count", "ref"}
                    or type(page["source_count"]) is not int
                    or page["source_count"] < 0
                    or (
                        page["tenant_id"] is not None
                        and (type(page["tenant_id"]) is not int or page["tenant_id"] not in frozen.tenant_ids)
                    )
                ):
                    blocked("semantic_directory_page")
                keys = await visit(page["ref"], depth + 1)
                if len(keys) != page["source_count"] or (
                    page["tenant_id"] is not None and any(key.tenant_id != page["tenant_id"] for key in keys)
                ):
                    blocked("semantic_directory_count")
        elif value.get("semantic_contract") == SEMANTICS:
            if (
                set(value) != {"schema_version", "semantic_contract", "tenant_id", "sources"}
                or value["tenant_id"] not in frozen.tenant_ids
                or type(value["tenant_id"]) is not int
                or type(value["sources"]) is not list
                or len(value["sources"]) > 200
            ):
                blocked("semantic_leaf_schema")
            for item in value["sources"]:
                if (
                    type(item) is not dict
                    or set(item) != {"key", "semantic_digest", "business_digest"}
                    or not _hash(item["semantic_digest"])
                    or not _hash(item["business_digest"])
                ):
                    blocked("semantic_leaf_row")
                key = _key(item["key"])
                if key.tenant_id != value["tenant_id"] or key in result:
                    blocked("semantic_leaf_duplicate_or_scope")
                result[key] = item
        else:
            blocked("semantic_directory_contract")
        return set(result) - start

    await visit(descriptor)
    return result


async def prepare_full_reconciliation(application, *, frozen, plan, reader, semantic_projection_ref=None, **inputs):
    """Consume exact native registration proofs without altering frozen ordinals."""
    from bisheng.knowledge.application.unification_registration import differences, prepare_registration

    with tenant_execution_scope(1):
        async with application._session() as session, session.begin():
            run = await application._scope_run(session, frozen)
            checkpoint = run.checkpoints.get("backfilling", {}).get("registration_plan")
    semantics = await load_semantics(application.store, frozen, semantic_projection_ref)
    if semantics and set(semantics) != {entry.header.source_key for entry in plan.sources}:
        blocked("semantic_source_universe")
    delta = await differences(application, plan)
    if checkpoint is None and not any(delta.values()):
        return replace(plan, reconciliation=ReferenceReconciliation(semantic_projections=tuple(semantics.values())))
    migration, _, descriptor, extension = await prepare_registration(
        application,
        frozen=frozen,
        reader=reader,
        plan=plan,
        delta=delta,
        apply=True,
        allow_verified=True,
        **inputs,
    )
    return replace(
        migration.plan,
        reconciliation=ReferenceReconciliation(
            proof_refs=tuple(ref for ref in (descriptor, extension) if ref is not None),
            registered_additions=tuple(delta["added"]),
            semantic_projections=tuple(semantics.values()),
        ),
    )


async def verify_proven_native_current(session, *, expected, repository, index_repository):
    """Verify an exact registered addition; unknown historical mutations reject."""
    from bisheng.knowledge.application.unification_registration import added_fact
    from bisheng.knowledge.domain.repositories.unification_target_repository import KnowledgeMigrationTargetRepository
    from bisheng.llm.domain.repositories.migration_target_repository import ModelMigrationTargetRepository

    key = _key(expected["key"])
    business = await repository.aload_reference_source(session, source_key=key)
    snapshot = await index_repository.aload_raw_snapshot(session, source_key=key)
    actual = await added_fact(
        session, key, repository, index_repository, business_snapshot=business, index_snapshot=snapshot
    )
    if actual != expected:
        blocked("registration_added_changed")
    _, _, bindings = snapshot
    targets = tuple(
        sorted(
            {TargetKey(row["target_type"], row["target_id"]) for row in bindings},
            key=lambda target: target.lock_order_key,
        )
    )
    facts = {}
    for owner, selected in (
        (ModelMigrationTargetRepository(), tuple(t for t in targets if t.target_type == TargetType.MODEL)),
        (KnowledgeMigrationTargetRepository(), tuple(t for t in targets if t.target_type != TargetType.MODEL)),
    ):
        for start in range(0, len(selected), 200):
            batch = selected[start : start + 200]
            observed = await owner.ainspect(session, source_key=key, targets=batch)
            if tuple(fact.key for fact in observed) != batch:
                blocked("native_current_targets_incomplete")
            facts.update((fact.key, fact) for fact in observed)
    for row in bindings:
        target = TargetKey(row["target_type"], row["target_id"])
        fact = facts[target]
        if (
            not fact.exists
            or row["target_tenant_id"] != fact.target_tenant_id
            or any(row[name] is not None for name in ("legacy_invalid_reason", "legacy_run_id", "legacy_evidence_key"))
        ):
            blocked("native_current_target_changed")
        if target.target_type == TargetType.MODEL:
            if (
                not fact.server_exists
                or fact.server_tenant_id != fact.target_tenant_id
                or fact.target_tenant_id not in {1, key.tenant_id}
                or row["target_space_id"] is not None
            ):
                blocked("native_current_target_scope")
        elif (
            not fact.space_exists
            or fact.space_tenant_id != fact.target_tenant_id
            or fact.target_tenant_id != key.tenant_id
            or fact.knowledge_type not in {0, 1, 3}
        ):
            blocked("native_current_target_scope")
        elif target.target_type == TargetType.KNOWLEDGE_FILE and row["target_space_id"] != str(fact.knowledge_id):
            blocked("native_current_target_parent")
    return {
        "fact": actual,
        "targets_digest": digest([asdict(facts[target]) for target in targets]),
        "valid_count": len(bindings),
        "source_receipt": actual["business"],
        "index_receipt": actual["index"],
        "source_bytes": len(canonical(snapshot))
        + len(
            canonical(
                {
                    "root": asdict(business[0]),
                    "version": asdict(business[1]) if business[1] else None,
                    "children": [asdict(child) for child in business[2]],
                }
            )
        ),
    }


async def inspect_reference_reconciliation(
    application, *, frozen, environment, operator_id=None, plan=None, semantic_projection_ref=None
):
    """Read-only complete observation for root's immutable candidate/CAS protocol.

    Aggregate chains cover every observed source; raw configurations are neither
    returned nor copied into the small candidate manifest. Missing mutation
    evidence remains a diagnostic and never becomes a native-current receipt.
    """
    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
    from bisheng.knowledge.application.unification_reference_plan import UnificationReferencePlanReader
    from bisheng.knowledge.application.unification_references import ReferenceMigration
    from bisheng.knowledge.application.unification_registration import differences, overlay, prepare_registration

    reader = UnificationReferencePlanReader(inventory=application.reader, artifact_store=application.store)
    if plan is None:
        plan = await reader.aprepare(frozen, environment=environment, backup_ref=None, schema_ref=None)
    with tenant_execution_scope(1):
        async with application._session() as session, session.begin():
            run = await application._scope_run(session, frozen)
            checkpoint = run.checkpoints.get("backfilling", {}).get("registration_plan")
            publication_checkpoint = run.checkpoints.get("converting", {}).get("permission_complete")
            publication = (
                json.loads(publication_checkpoint["cursor"])
                if publication_checkpoint and publication_checkpoint.get("complete") is True
                else None
            )
    actor = publication["binding"]["operator_id"] if operator_id is None and publication else operator_id
    diagnostics, observations = [], []
    try:
        delta = await differences(application, plan)
        if checkpoint is not None:
            if publication is None:
                blocked("registration_before_publication")
            migration, _, descriptor, extension = await prepare_registration(
                application,
                frozen=frozen,
                reader=reader,
                plan=plan,
                delta=delta,
                apply=False,
                allow_verified=True,
                environment=environment,
                operator_id=actor,
                backup_ref=None,
                schema_ref=None,
            )
        else:
            migration, descriptor, extension = (
                ReferenceMigration(application, frozen, overlay(plan, delta), reader, environment=environment),
                None,
                None,
            )
    except KnowledgeOperationPlanConflictError as error:
        return {
            "manifest": None,
            "diagnostics": [
                {"reason": error.kwargs.get("reason"), "classification": "maintenance_reconciliation_required"}
            ],
            "observations": [],
            "checked_before": publication is None,
        }
    semantics = await load_semantics(application.store, frozen, semantic_projection_ref)
    if semantics and set(semantics) != {entry.header.source_key for entry in plan.sources}:
        blocked("semantic_source_universe")
    migration.sources.semantic_projections = semantics
    for tenant in frozen.tenant_ids:
        source_chain, index_chain, ordinal = digest({"tenant": tenant}), digest({"tenant": tenant}), 0
        with tenant_execution_scope(tenant):
            async with application._session() as session, session.begin():
                run = await application._scope_run(session, frozen)
                progress = run.checkpoints.get("backfilling", {}).get("references")
                prefix = progress["processed_count"] if progress else 0
                retirement = run.checkpoints.get("backfilling", {}).get("references_retired")
                retired_prefix = retirement["processed_count"] if retirement else 0
            retired = tuple(item.header for item in plan.retired if item.header.root_key.tenant_id == tenant)
            covered = {header.root_key for header in retired if header.source_key is None}
            for start in range(0, len(retired), 100):
                async with application._session() as session, session.begin():
                    await application._scope_run(session, frozen)
                    for retired_ordinal, header in enumerate(retired[start : start + 100], start + 1):
                        try:
                            after = await migration._retire_item(
                                session, header, covered=covered, write=False, before=retired_ordinal > retired_prefix
                            )
                            source_chain = digest(
                                {
                                    "previous": source_chain,
                                    "retired": asdict(header.root_key),
                                    "source": asdict(header.source_key) if header.source_key else None,
                                    "business": header.business_revision_digest,
                                }
                            )
                            index_chain = digest(
                                {"previous": index_chain, "retired": retired_ordinal, "snapshot": after}
                            )
                        except KnowledgeOperationPlanConflictError as error:
                            diagnostics.append(
                                {
                                    "root": asdict(header.root_key),
                                    "reason": error.kwargs.get("reason"),
                                    "classification": "maintenance_reconciliation_required",
                                }
                            )
            async for batch in migration._batches(tenant):
                async with application._session() as session, session.begin():
                    await application._scope_run(session, frozen)
                    snapshots = await migration.backfill.repository.aload_raw_snapshots(
                        session, source_keys=tuple(h.source_key for h, _ in batch)
                    )
                    semantic_page = await collect_semantics(
                        session,
                        source_keys=tuple(h.source_key for h, _ in batch),
                        repository=migration.sources.repository,
                    )
                    actual_semantics = {_key(item["key"]): item for item in semantic_page["sources"]}
                    for header, records in batch:
                        key = header.source_key
                        try:
                            conversion = migration.conversions.get((tenant, key.source_type, key.source_id))
                            try:
                                actual_header, pairs = await migration.sources.aload(
                                    session,
                                    header=header,
                                    records=records,
                                    conversion=conversion if publication else None,
                                )
                            except KnowledgeOperationPlanConflictError:
                                if publication or conversion is None:
                                    raise
                                # SQL may be partially committed. Accept only
                                # the original BEFORE or the exact native
                                # conversion AFTER, never a fresh baseline.
                                actual_header, pairs = await migration.sources.aload(
                                    session, header=header, records=records, conversion=conversion
                                )
                            facts = await migration._targets(session, key, records)
                            from bisheng.knowledge.application.unification_reference_state import parse_frozen

                            index = parse_frozen(header.frozen_index, index=True)
                            revision = (index["root_head"]["source_revision"] if index["root_head"] else 0) + 1
                            templates, _ = migration._templates(key, pairs, facts, revision)
                            migration.backfill._check(
                                {
                                    "source_key": key,
                                    "frozen_index": index,
                                    "root_revision": revision,
                                    "rows": templates,
                                    "extractor_version": actual_header.extractor_version,
                                    "reference_digest": actual_header.reference_digest,
                                },
                                snapshots[key],
                                before=ordinal >= prefix,
                            )
                            if (
                                key in semantics
                                and (tenant, key.source_type, key.source_id) not in migration.conversions
                                and semantics[key]["semantic_digest"] != actual_semantics[key]["semantic_digest"]
                            ):
                                blocked("semantic_source_changed")
                            planned_business = getattr(
                                conversion,
                                "after_inventory_business_revision_digest",
                                getattr(
                                    conversion, "after_business_revision_digest", actual_header.business_revision_digest
                                ),
                            )
                            source_chain = digest(
                                {
                                    "previous": source_chain,
                                    "key": asdict(key),
                                    "business": planned_business
                                    if conversion is not None
                                    else actual_semantics[key]["semantic_digest"]
                                    if key in semantics
                                    else actual_header.business_revision_digest,
                                    "semantic": digest(asdict(conversion))
                                    if conversion is not None
                                    else actual_semantics[key]["semantic_digest"],
                                }
                            )
                            index_chain = digest(
                                {"previous": index_chain, "key": asdict(key), "snapshot": fingerprint(snapshots[key])}
                            )
                        except KnowledgeOperationPlanConflictError as error:
                            diagnostics.append(
                                {
                                    "key": asdict(key),
                                    "reason": error.kwargs.get("reason"),
                                    "classification": "maintenance_reconciliation_required",
                                }
                            )
                        ordinal += 1
            for added in delta["added"]:
                if added["key"]["tenant_id"] == tenant:
                    async with application._session() as session, session.begin():
                        current = await verify_proven_native_current(
                            session,
                            expected=added,
                            repository=migration.sources.repository,
                            index_repository=migration.backfill.repository,
                        )
                    source_chain = digest(
                        {
                            "previous": source_chain,
                            "native_current": {
                                name: current[name] for name in ("fact", "targets_digest", "valid_count")
                            },
                        }
                    )
            observations.append(
                {
                    "tenant_id": tenant,
                    "source_count": ordinal,
                    "processed_count": prefix,
                    "retired_count": len(retired),
                    "retired_processed_count": retired_prefix,
                    "retired_checkpoint_digest": digest(retirement),
                    "source_digest": source_chain,
                    "index_digest": index_chain,
                    "checkpoint_digest": digest(progress),
                }
            )
    manifest = {
        "schema_version": 1,
        "reference_contract": "f118-reference-reconciliation-v1",
        "binding": application._identity(frozen),
        "environment": environment,
        "tenant_ids": list(frozen.tenant_ids),
        "registration_plan_ref": descriptor,
        "extension_ref": extension,
        "tenant_observations": observations,
        "additions": delta["added"],
    }
    return {
        "manifest": manifest if not diagnostics else None,
        "diagnostics": diagnostics,
        "observations": observations,
        "checked_before": publication is None,
    }


async def require_reconciliation_candidate(
    application, *, frozen, descriptor, environment, operator_id, plan, semantic_projection_ref=None
):
    envelope = json.loads(
        await application.store.aload_canonical(descriptor, run_id=frozen.run_id, kind="verification")
    )
    if len(envelope["records"]) != 1:
        blocked("reconciliation_candidate_schema")
    expected = envelope["records"][0]
    current = await inspect_reference_reconciliation(
        application,
        frozen=frozen,
        environment=environment,
        operator_id=operator_id,
        plan=plan,
        semantic_projection_ref=semantic_projection_ref,
    )
    validate_reference_candidate(expected, current, frozen=frozen, environment=environment)
    return expected


def validate_reference_candidate(expected, current, *, frozen, environment):
    """Pure candidate comparison against one complete native current observation."""
    if (
        type(expected) is not dict
        or set(expected)
        != {
            "schema_version",
            "reference_contract",
            "binding",
            "environment",
            "tenant_ids",
            "registration_plan_ref",
            "extension_ref",
            "tenant_observations",
            "additions",
        }
        or type(expected["schema_version"]) is not int
        or expected["schema_version"] != 1
        or expected["reference_contract"] != "f118-reference-reconciliation-v1"
        or expected["binding"]
        != {
            "run_id": frozen.run_id,
            "writer_contract_version": frozen.writer_contract_version,
            "baseline_hash": frozen.baseline_ref["sha256"],
            "plan_hash": frozen.plan_ref["sha256"],
        }
        or expected["environment"] != environment
        or expected["tenant_ids"] != list(frozen.tenant_ids)
        or type(expected["tenant_ids"]) is not list
        or any(type(tenant) is not int for tenant in expected["tenant_ids"])
    ):
        blocked("reconciliation_candidate_identity")
    if type(expected["tenant_observations"]) is not list or len(expected["tenant_observations"]) != len(
        frozen.tenant_ids
    ):
        blocked("reconciliation_candidate_tenant_changed")
    for tenant, observation in zip(frozen.tenant_ids, expected["tenant_observations"], strict=True):
        if (
            type(observation) is not dict
            or set(observation)
            != {
                "tenant_id",
                "source_count",
                "processed_count",
                "retired_count",
                "retired_processed_count",
                "retired_checkpoint_digest",
                "source_digest",
                "index_digest",
                "checkpoint_digest",
            }
            or type(observation["tenant_id"]) is not int
            or observation["tenant_id"] != tenant
        ):
            blocked("reconciliation_candidate_observation_schema")
        if (
            any(
                type(observation[name]) is not int or observation[name] < 0
                for name in ("source_count", "processed_count", "retired_count", "retired_processed_count")
            )
            or observation["processed_count"] > observation["source_count"]
            or observation["retired_processed_count"] > observation["retired_count"]
            or any(
                not _hash(observation[name])
                for name in ("retired_checkpoint_digest", "source_digest", "index_digest", "checkpoint_digest")
            )
        ):
            blocked("reconciliation_candidate_observation_schema")
    for name in ("registration_plan_ref", "extension_ref"):
        ref = expected[name]
        if ref is not None and (
            type(ref) is not dict
            or set(ref) != {"object_key", "sha256"}
            or not _hash(ref["sha256"])
            or ref["object_key"] != f"f118/unification/{frozen.run_id}/verification/{ref['sha256']}.json"
        ):
            blocked("reconciliation_candidate_proof_schema")
    if type(expected["additions"]) is not list:
        blocked("reconciliation_candidate_additions_schema")
    added_keys = set()
    for item in expected["additions"]:
        if (
            type(item) is not dict
            or set(item) != {"key", "business", "index", "reference_count"}
            or not _hash(item["business"])
            or not _hash(item["index"])
            or type(item["reference_count"]) is not int
            or item["reference_count"] < 0
        ):
            blocked("reconciliation_candidate_additions_schema")
        key = _key(item["key"])
        if key.tenant_id not in frozen.tenant_ids or key in added_keys:
            blocked("reconciliation_candidate_additions_scope")
        added_keys.add(key)
    if current["diagnostics"] or current["manifest"] is None:
        blocked("reconciliation_candidate_current_changed")
    actual = current["manifest"]
    if any(
        actual[name] != expected[name]
        for name in ("schema_version", "reference_contract", "binding", "environment", "tenant_ids", "additions")
    ):
        blocked("reconciliation_candidate_current_changed")
    for name in ("registration_plan_ref", "extension_ref"):
        if expected[name] is not None and actual[name] != expected[name]:
            blocked("reconciliation_candidate_proof_changed")
    if len(actual["tenant_observations"]) != len(expected["tenant_observations"]):
        blocked("reconciliation_candidate_tenant_changed")
    for before, after in zip(expected["tenant_observations"], actual["tenant_observations"], strict=True):
        if (
            any(before[name] != after[name] for name in ("tenant_id", "source_count", "retired_count", "source_digest"))
            or after["processed_count"] < before["processed_count"]
            or after["retired_processed_count"] < before["retired_processed_count"]
        ):
            blocked("reconciliation_candidate_current_changed")
        # Native registration changes only indexes and the atomic commit
        # cursor. inspect above independently validates every original BEFORE
        # or committed AFTER; unchanged cursors must retain the exact snapshot.
        if (
            before["processed_count"] == after["processed_count"]
            and before["retired_processed_count"] == after["retired_processed_count"]
        ):
            if before["index_digest"] != after["index_digest"]:
                blocked("reconciliation_candidate_index_changed")
            for count, checksum in (
                ("source_count", "checkpoint_digest"),
                ("retired_count", "retired_checkpoint_digest"),
            ):
                if before[checksum] != after[checksum] and not (
                    before[count] == 0 and before[checksum] == digest(None)
                ):
                    blocked("reconciliation_candidate_index_changed")
    return None
