"""Explicit reference registration after completed SQL/permission publication.

This maintenance application skips full completed-stage replay and the second
reference verification pass. It never certifies Coverage or reopens services.
The original baseline/plan remain immutable; bounded differences are frozen in
an additional content-addressed artifact and bound to native Run checkpoints.
"""

import json
import time
from dataclasses import asdict, replace

from loguru import logger

from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.knowledge.application.unification_reference_sources import ReferenceAfterSources
from bisheng.knowledge.application.unification_reference_state import PHYSICAL_ROOT_ABSENT, blocked
from bisheng.knowledge.application.unification_references import ReferenceMigration
from bisheng.knowledge.application.unification_registration_plan import registration_reader
from bisheng.knowledge.application.unification_workflow_retention import invalid_root
from bisheng.knowledge.domain.services.unification_fingerprints import canonical, digest
from bisheng.permission.application.control_state import SqlPermissionControlState
from bisheng.permission.application.migration_read import read_completed_migration_catalog
from bisheng.resource_reference.application.backfill import fingerprint
from bisheng.resource_reference.application.contracts import (
    ReferenceSpec,
    SourceRootKey,
    SourceType,
    TargetKey,
    reference_set_digest,
)
from bisheng.resource_reference.domain.repositories.reference_backfill_repository import ReferenceBackfillRepository


def key_values(key):
    return asdict(key)


def ordered(keys):
    return sorted(keys, key=lambda k: (k.tenant_id, k.source_type.value, k.source_id, getattr(k, "source_version", "")))


async def admit_completed(application, frozen, *, environment, operator_id):
    """Finite native ledger and CURRENT/pin admission, with no tuple scan/write."""
    if type(operator_id) is not int or operator_id < 0:
        blocked("registration_operator")
    expected = None
    for tenant in frozen.tenant_ids:
        with tenant_execution_scope(tenant):
            async with application._session() as session, session.begin():
                row = await application._scope_run(session, frozen)
                if (
                    row.error_code is not None
                    or row.coverage_epoch is not None
                    or row.phase not in {"converting", "backfilling"}
                ):
                    blocked("registration_run_phase")
                cp = row.checkpoints.get("converting", {})
                if any(cp.get(k, {}).get("complete") is not True for k in ("sql_conversion", "permission_namespace")):
                    blocked("registration_prior_stage_incomplete")
                if tenant == 1:
                    if any(
                        cp.get(k, {}).get("complete") is not True
                        for k in ("permission_prepare", "permission_catalog", "permission_fga", "permission_complete")
                    ):
                        blocked("registration_permission_incomplete")
                    expected = json.loads(cp["permission_complete"]["cursor"])
                    binding = expected["binding"]
                    if any(
                        binding.get(k) != v
                        for k, v in {**application._identity(frozen), "operator_id": operator_id}.items()
                    ):
                        blocked("registration_publication_binding")
    if expected is None:
        blocked("registration_global_publication_missing")
    with tenant_execution_scope(1):
        async with application._session() as session, session.begin():
            catalog = await read_completed_migration_catalog(session, environment=environment)
        auth = expected["authorization"]
        if (
            catalog.release.id != expected["draft_id"]
            or catalog.release.commit_checksum != expected["commit_checksum"]
            or any(
                getattr(catalog.authorization, k) != auth[k] for k in ("id", "store_id", "model_id", "model_checksum")
            )
        ):
            blocked("registration_current_publication_changed")
        current = await SqlPermissionControlState().current_catalog()
        if (current.release_id, current.store_id, current.model_id, current.model_checksum) != (
            catalog.release.id,
            catalog.authorization.store_id,
            catalog.authorization.model_id,
            catalog.authorization.model_checksum,
        ):
            blocked("registration_runtime_catalog_changed")
    return {
        "catalog_id": current.release_id,
        "store_id": current.store_id,
        "model_id": current.model_id,
        "model_checksum": current.model_checksum,
        "commit_checksum": expected["commit_checksum"],
    }


async def added_fact(session, key, repository, index_repository):
    """Retain a post-freeze source only when native registration matches truth."""
    from bisheng.channel.domain.services.reference_extractor import (
        CHANNEL_SYNC_REFERENCE_EXTRACTOR_VERSION,
        extract_channel_sync_references,
    )
    from bisheng.workflow.domain.services.reference_extractor import (
        WORKFLOW_REFERENCE_EXTRACTOR_VERSION,
        extract_workflow_version_references,
    )

    root, version, children = await repository.aload_reference_source(session, source_key=key)
    if key.source_type == SourceType.WORKFLOW_VERSION:
        if root.is_delete != 0 or version.is_delete not in (None, 0):
            blocked("registration_added_source_retired")
        extractor = WORKFLOW_REFERENCE_EXTRACTOR_VERSION
        refs = extract_workflow_version_references(json.loads(version.data_json))
    elif key.source_type == SourceType.CHANNEL_SYNC:
        extractor = CHANNEL_SYNC_REFERENCE_EXTRACTOR_VERSION
        refs = extract_channel_sync_references(tuple(asdict(c) for c in children), skip_legacy_folders=True)
    else:
        blocked("registration_added_source_type")
    head, source, rows = await index_repository.aload_raw_snapshot(session, source_key=key, for_update=False)
    actual_refs = tuple(ReferenceSpec(r["slot_key"], TargetKey(r["target_type"], r["target_id"])) for r in rows)
    expected_digest = reference_set_digest(tuple(refs))
    if (
        head is None
        or source is None
        or source["record_kind"] != "source"
        or source["extractor_version"] != extractor
        or source["digest_version"] != "sha256-reference-set-v1"
        or not source["ready"]
        or not source["effective"]
        or head["record_kind"] != "root_guard"
        or head["ready"]
        or head["effective"]
        or head["source_revision"] <= 0
        or source["source_revision"] <= 0
        or source["source_revision"] > head["source_revision"]
        or source["digest"] != expected_digest
        or reference_set_digest(actual_refs) != expected_digest
        or any(r["source_revision"] != source["source_revision"] for r in rows)
    ):
        blocked("registration_added_source_not_registered")
    return {
        "key": key_values(key),
        "business": digest(
            {
                "root": asdict(root),
                "version": asdict(version) if version else None,
                "children": [asdict(c) for c in children],
            }
        ),
        "index": fingerprint((head, source, rows)),
        "reference_count": len(refs),
    }


async def differences(application, plan):
    repository, index_repository = ReferenceAfterSources().repository, ReferenceBackfillRepository()
    overrides, added = [], []
    roots_by_key = {row.header.root_key: row.header for row in plan.roots}
    for tenant in plan.frozen.tenant_ids:
        expected_sources = {r.header.source_key for r in plan.sources if r.header.source_key.tenant_id == tenant}
        expected_roots = {k for k in roots_by_key if k.tenant_id == tenant}
        expected_roots.update(
            r.header.root_key
            for r in plan.retired
            if r.header.root_key.tenant_id == tenant
            and r.header.source_key is None
            and r.header.lifecycle != PHYSICAL_ROOT_ABSENT
            and not invalid_root(r.header)
        )
        expected_versions = {
            k for k in expected_sources if k.source_type in {SourceType.WORKFLOW_VERSION, SourceType.HOSTED_APP_VERSION}
        }
        expected_versions.update(
            r.header.source_key
            for r in plan.retired
            if r.header.root_key.tenant_id == tenant and r.header.source_key is not None
        )
        with tenant_execution_scope(tenant):
            async with application._session() as session, session.begin():
                actual_roots, actual_sources, actual_versions = await repository.acensus_reference_sources(session)
                extra = actual_sources - expected_sources
                extra_roots = (
                    {SourceRootKey(k.tenant_id, k.source_type, k.source_id) for k in extra} if extra else set()
                )
                if (
                    expected_sources - actual_sources
                    or expected_roots - set(actual_roots)
                    or set(actual_roots) - expected_roots != extra_roots
                    or actual_versions
                    != expected_versions | {k for k in extra if k.source_type == SourceType.WORKFLOW_VERSION}
                    or len(extra) + len(added) > 100
                ):
                    blocked("registration_unexpected_universe_drift")
                for key in ordered(extra):
                    added.append(await added_fact(session, key, repository, index_repository))
                for entry in plan.sources:
                    h = entry.header
                    if h.source_key.tenant_id != tenant or h.source_key.source_type not in {
                        SourceType.HOSTED_APP_VERSION,
                        SourceType.CHANNEL_SYNC,
                    }:
                        continue
                    root, version, children = await repository.aload_reference_source(session, source_key=h.source_key)
                    original_root = roots_by_key[
                        SourceRootKey(tenant, h.source_key.source_type, h.source_key.source_id)
                    ]
                    if h.source_key.source_type == SourceType.HOSTED_APP_VERSION:
                        if (
                            root.owner_user_id != original_root.creator_id
                            or root.state == "deleted"
                            or (root.state, root.current_version_id, root.pending_version_id) != original_root.lifecycle
                        ):
                            blocked("registration_app_identity_changed")
                        revision = digest({"root": digest(asdict(root)), "version": asdict(version)})
                    else:
                        if root.user_id != original_root.creator_id or (root.is_released,) != original_root.lifecycle:
                            blocked("registration_channel_identity_changed")
                        revision = digest({"root": asdict(root), "links": tuple(asdict(c) for c in children)})
                    # Native source reader still checks configuration, lifecycle and
                    # complete reference membership. Only this exact revision varies.
                    if revision != h.business_revision_digest:
                        if sum(r["key"]["source_type"] == h.source_key.source_type for r in overrides) >= 100:
                            blocked("registration_timestamp_drift_limit")
                        overrides.append(
                            {"key": key_values(h.source_key), "before": h.business_revision_digest, "after": revision}
                        )
    return {"overrides": overrides, "added": added}


def overlay(plan, delta):
    changes = {
        tuple(row["key"][k] for k in ("tenant_id", "source_type", "source_id", "source_version")): row
        for row in delta["overrides"]
    }

    def entry(row):
        h = row.header
        item = changes.get(
            (
                h.source_key.tenant_id,
                h.source_key.source_type.value,
                h.source_key.source_id,
                h.source_key.source_version,
            )
        )
        if item is None:
            return row
        if item["before"] != h.business_revision_digest:
            blocked("registration_delta_baseline_changed")
        return replace(row, header=replace(h, business_revision_digest=item["after"]))

    return replace(plan, sources=tuple(entry(row) for row in plan.sources))


async def run_registration(application, *, apply=False, **inputs):
    started = time.monotonic()
    frozen = await application._admit(inputs["run_id"], inputs["writer_contract_version"])
    publication = await admit_completed(
        application, frozen, environment=inputs["environment"], operator_id=inputs["operator_id"]
    )
    logger.info("reference_registration stage=read_plan prior_sql_permissions=completed_reused")
    reader = registration_reader(application.store)
    plan = await reader.aprepare(frozen, **{k: inputs[k] for k in ("environment", "backup_ref", "schema_ref")})
    delta = await differences(application, plan)
    # Validate all bounded app differences before the first write, including
    # actual configuration/lifecycle/reference membership, not just a new hash.
    overlaid = overlay(plan, delta)
    migration = ReferenceMigration(application, frozen, overlaid, reader, environment=inputs["environment"])
    changed = {tuple(r["key"].values()) for r in delta["overrides"]}
    validation_plan = replace(
        overlaid,
        sources=tuple(
            entry for entry in overlaid.sources if tuple(key_values(entry.header.source_key).values()) in changed
        ),
    )
    validation = ReferenceMigration(application, frozen, validation_plan, reader, environment=inputs["environment"])
    for tenant in frozen.tenant_ids:
        with tenant_execution_scope(tenant):
            async for header, records in validation._records(tenant):
                async with application._session() as session, session.begin():
                    await validation.sources.aload(session, header=header, records=records)
    payload = {
        "registration_contract": 1,
        **application._identity(frozen),
        "environment": inputs["environment"],
        "operator_id": inputs["operator_id"],
        "publication": publication,
        **delta,
    }
    descriptor = None
    with tenant_execution_scope(1):
        async with application._session() as session, session.begin():
            run = await application._scope_run(session, frozen)
            checkpoint = run.checkpoints.get("backfilling", {}).get("registration_plan")
        extension_ref = None
        if checkpoint is not None:
            descriptor = json.loads(checkpoint["cursor"])
            stored = json.loads(
                await application.store.aload_canonical(descriptor, run_id=frozen.run_id, kind="verification")
            )
            original = stored["records"][0]
            if checkpoint["digest"] != digest(original) or checkpoint["complete"] is not True:
                blocked("registration_delta_changed")
            extension_ref = await bind_channel_extension(
                application, frozen, plan, original, payload, descriptor, checkpoint["digest"], apply=apply
            )
        if apply and checkpoint is None:
            descriptor = await application.store.aput_canonical(
                run_id=frozen.run_id,
                kind="verification",
                content=canonical(
                    {"schema_version": 1, "run_id": frozen.run_id, "kind": "verification", "records": [payload]}
                ),
            )
            # Enter the original native phase before binding the delta proof.
            await migration._phase(1)
            async with application._session() as session, session.begin():
                await application.runs.acheckpoint(
                    session,
                    **application._identity(frozen),
                    expected_phase="backfilling",
                    checkpoint_key="registration_plan",
                    expected_checkpoint=None,
                    checkpoint={
                        "cursor": canonical(descriptor).decode(),
                        "processed_count": 1,
                        "digest": digest(payload),
                        "complete": True,
                    },
                )
    if apply:
        for tenant in frozen.tenant_ids:
            with tenant_execution_scope(tenant):
                await migration._tenant(tenant, registration_only=True)
        # Recheck only the bounded extras and CURRENT pointer, never rescan all
        # sources, targets, completed SQL or the FGA store after registration.
        await admit_completed(application, frozen, environment=inputs["environment"], operator_id=inputs["operator_id"])
        for item in delta["added"]:
            from bisheng.resource_reference.application.contracts import SourceKey

            key = SourceKey(**item["key"])
            with tenant_execution_scope(key.tenant_id):
                async with application._session() as session, session.begin():
                    if (
                        await added_fact(session, key, migration.sources.repository, migration.backfill.repository)
                        != item
                    ):
                        blocked("registration_added_changed")
    result = {
        "mode": "register_references" if apply else "preview_reference_registration",
        "run_id": frozen.run_id,
        "tenant_ids": list(frozen.tenant_ids),
        "source_count": len(plan.sources),
        "retired_count": len(plan.retired),
        "app_revision_differences": sum(
            r["key"]["source_type"] == SourceType.HOSTED_APP_VERSION for r in delta["overrides"]
        ),
        "channel_revision_differences": sum(
            r["key"]["source_type"] == SourceType.CHANNEL_SYNC for r in delta["overrides"]
        ),
        "registration_extension_ref": extension_ref,
        "retained_added_sources": len(delta["added"]),
        "registration_plan_ref": descriptor,
        "registration_complete": apply,
        "full_verification_deferred": True,
        "ready": False,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }
    logger.info("reference_registration result={}", json.dumps(result))
    return result


async def bind_channel_extension(application, frozen, plan, original, payload, base_ref, base_digest, *, apply):
    """Append only uncommitted channel timestamp facts to an existing proof."""
    async with application._session() as session, session.begin():
        run = await application._scope_run(session, frozen)
        checkpoint = run.checkpoints.get("backfilling", {}).get("registration_plan_extension")
    if json.loads(canonical(payload)) == original:
        if checkpoint is not None:
            blocked("registration_extension_facts_disappeared")
        return None
    original_keys = {
        tuple(r["key"][k] for k in ("tenant_id", "source_type", "source_id", "source_version"))
        for r in original["overrides"]
    }
    additions = [
        r
        for r in payload["overrides"]
        if r["key"]["source_type"] == SourceType.CHANNEL_SYNC
        and tuple(r["key"][k] for k in ("tenant_id", "source_type", "source_id", "source_version")) not in original_keys
    ]
    equivalent = {**payload, "overrides": [r for r in payload["overrides"] if r not in additions]}
    if not additions or json.loads(canonical(equivalent)) != original:
        blocked("registration_delta_changed")
    prefixes = {}
    for tenant in frozen.tenant_ids:
        with tenant_execution_scope(tenant):
            async with application._session() as session, session.begin():
                run = await application._scope_run(session, frozen)
                cp = run.checkpoints.get("backfilling", {}).get("references", {})
                prefixes[str(tenant)] = {"processed_count": cp.get("processed_count", 0), "digest": cp.get("digest")}
    if checkpoint is not None:
        ref = json.loads(checkpoint["cursor"])
        artifact = json.loads(await application.store.aload_canonical(ref, run_id=frozen.run_id, kind="verification"))
        recorded = artifact["records"][0]
        if (
            checkpoint["digest"] != digest(recorded)
            or checkpoint["complete"] is not True
            or recorded
            != {
                **application._identity(frozen),
                "registration_contract": 2,
                "base_plan_ref": base_ref,
                "base_digest": base_digest,
                "overrides": json.loads(canonical(additions)),
                "resume_prefixes": recorded.get("resume_prefixes"),
            }
        ):
            blocked("registration_extension_changed")
        for tenant, before in recorded["resume_prefixes"].items():
            current = prefixes[tenant]
            if current["processed_count"] < before["processed_count"] or (
                current["processed_count"] == before["processed_count"]
                and before["digest"] is not None
                and current != before
            ):
                blocked("registration_extension_prefix_changed")
        return ref
    addition_keys = {
        tuple(r["key"][k] for k in ("tenant_id", "source_type", "source_id", "source_version")) for r in additions
    }
    ordinals = dict.fromkeys(frozen.tenant_ids, 0)
    for entry in plan.sources:
        key = entry.header.source_key
        ordinals[key.tenant_id] += 1
        if (
            tuple(key_values(key).values()) in addition_keys
            and ordinals[key.tenant_id] <= prefixes[str(key.tenant_id)]["processed_count"]
        ):
            blocked("registration_extension_touches_committed_source")
    if not apply:
        return None
    record = {
        **application._identity(frozen),
        "registration_contract": 2,
        "base_plan_ref": base_ref,
        "base_digest": base_digest,
        "overrides": additions,
        "resume_prefixes": prefixes,
    }
    ref = await application.store.aput_canonical(
        run_id=frozen.run_id,
        kind="verification",
        content=canonical({"schema_version": 1, "run_id": frozen.run_id, "kind": "verification", "records": [record]}),
    )
    async with application._session() as session, session.begin():
        await application.runs.acheckpoint(
            session,
            **application._identity(frozen),
            expected_phase="backfilling",
            checkpoint_key="registration_plan_extension",
            expected_checkpoint=None,
            checkpoint={
                "cursor": canonical(ref).decode(),
                "processed_count": 1,
                "digest": digest(record),
                "complete": True,
            },
        )
    return ref
