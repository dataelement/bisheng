"""Original M3→M4 entry: registered backfill, full reconciliation, then Coverage."""

import time
from dataclasses import asdict, dataclass

from loguru import logger

from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.knowledge.application.unification_coverage import (
    certify_migration,
    production_coverage_factory,
)
from bisheng.knowledge.application.unification_preflight import source_decision
from bisheng.knowledge.application.unification_progress import report_progress
from bisheng.knowledge.application.unification_reference_plan import UnificationReferencePlanReader
from bisheng.knowledge.application.unification_reference_sources import ReferenceAfterSources
from bisheng.knowledge.application.unification_reference_state import blocked, parse_frozen, sql_value
from bisheng.knowledge.application.unification_sources import (
    APP_REFERENCE_EXTRACTOR_VERSION,
    ASSISTANT_REFERENCE_EXTRACTOR_VERSION,
    CHANNEL_SYNC_REFERENCE_EXTRACTOR_VERSION,
    KNOWLEDGE_MODEL_REFERENCE_EXTRACTOR_VERSION,
    MODEL_DEFAULT_REFERENCE_EXTRACTOR_VERSION,
    WORKFLOW_REFERENCE_EXTRACTOR_VERSION,
)
from bisheng.knowledge.domain.repositories.unification_target_repository import KnowledgeMigrationTargetRepository
from bisheng.knowledge.domain.schemas.unification_conversion import DefaultConversionCommand, ResourceConversionCommand
from bisheng.knowledge.domain.services.unification_fingerprints import canonical, digest
from bisheng.llm.domain.repositories.migration_target_repository import ModelMigrationTargetRepository
from bisheng.resource_reference.application.backfill import RegisteredReferenceBackfill, fingerprint
from bisheng.resource_reference.application.contracts import (
    SourceKey,
    SourceRootKey,
    SourceType,
    TargetKey,
    TargetType,
    TransactionIdentity,
)

_VERSIONS = {
    SourceType.WORKFLOW_VERSION.value: WORKFLOW_REFERENCE_EXTRACTOR_VERSION,
    SourceType.HOSTED_APP_VERSION.value: APP_REFERENCE_EXTRACTOR_VERSION,
    SourceType.ASSISTANT.value: ASSISTANT_REFERENCE_EXTRACTOR_VERSION,
    SourceType.CHANNEL_SYNC.value: CHANNEL_SYNC_REFERENCE_EXTRACTOR_VERSION,
    SourceType.KNOWLEDGE.value: KNOWLEDGE_MODEL_REFERENCE_EXTRACTOR_VERSION,
    SourceType.MODEL_DEFAULT.value: MODEL_DEFAULT_REFERENCE_EXTRACTOR_VERSION,
}


@dataclass(frozen=True, slots=True)
class ReferenceMigrationReport:
    run_id: str
    writer_contract_version: str
    baseline_hash: str
    plan_hash: str
    tenant_ids: tuple[int, ...]
    coverage_epoch: int
    complete: bool


def _seed(frozen, tenant):
    return digest(
        {
            "reference_migration": 1,
            "run_id": frozen.run_id,
            "writer": frozen.writer_contract_version,
            "baseline": frozen.baseline_ref,
            "plan": frozen.plan_ref,
            "tenant_id": tenant,
        }
    )


def _checkpoint(frozen, tenant, ordinal, checksum, complete):
    cursor = canonical(
        {
            "schema_version": 1,
            "run_id": frozen.run_id,
            "writer_contract_version": frozen.writer_contract_version,
            "baseline_hash": frozen.baseline_ref["sha256"],
            "plan_hash": frozen.plan_ref["sha256"],
            "tenant_id": tenant,
            "source_ordinal": ordinal,
        }
    ).decode()
    return {"cursor": cursor, "processed_count": ordinal, "digest": checksum, "complete": complete}


def _validate_progress(goal, total):
    if goal is not None and (
        type(goal) is not dict
        or set(goal) != {"cursor", "processed_count", "digest", "complete"}
        or type(goal["processed_count"]) is not int
        or not 0 <= goal["processed_count"] <= total
        or type(goal["complete"]) is not bool
        or goal["complete"] != (goal["processed_count"] == total)
        or (total and goal["processed_count"] == 0)
    ):
        blocked("reference_checkpoint_invalid")


class ReferenceMigration:
    source_batch_limit = 100
    source_reference_limit = 4096
    source_byte_limit = 4 * 1024 * 1024

    def __init__(self, application, frozen, plan, reader, *, environment):
        self.app, self.frozen, self.plan, self.reader = application, frozen, plan, reader
        self.environment = environment
        self._tail_sources = {}
        self._tail_costs = {}
        semantics = {
            SourceKey(**item["key"]): item
            for item in (plan.reconciliation.semantic_projections if plan.reconciliation else ())
        }
        self.sources, self.backfill = (
            ReferenceAfterSources(
                semantic_projections=semantics,
                root_expectations={item.header.root_key: item.header for item in plan.roots},
            ),
            RegisteredReferenceBackfill(),
        )
        self.conversions, self.resources = {}, {}
        for command in plan.conversions:
            if type(command) is ResourceConversionCommand:
                self.conversions[(command.tenant_id, SourceType.KNOWLEDGE, str(command.knowledge_id))] = command
                self.resources[(command.tenant_id, command.knowledge_id)] = command
            elif type(command) is DefaultConversionCommand:
                self.conversions[(command.tenant_id, SourceType.MODEL_DEFAULT, command.key)] = command

    async def _phase(self, tenant):
        async with self.app._session() as session, session.begin():
            with tenant_execution_scope(1):
                global_run = await self.app._scope_run(session, self.frozen)
                if (
                    global_run.checkpoints.get("converting", {}).get("permission_complete", {}).get("complete")
                    is not True
                ):
                    blocked("permission_publication_incomplete")
            run = await self.app._scope_run(session, self.frozen)
            if run.phase == "converting":
                await self.app.runs.aadvance(
                    session, **self.app._identity(self.frozen), expected_phase="converting", next_phase="backfilling"
                )
                return "backfilling", None
            if run.phase not in {"backfilling", "verifying", "verified", "completed"}:
                blocked("backfill_phase")
            return run.phase, run.checkpoints.get("backfilling", {}).get("references")

    async def _targets(self, session, key, records, *, facts_cache=None, tombstone_cache=None):
        transaction = TransactionIdentity.capture(session)
        keys = tuple(dict.fromkeys(record.target for record in records))
        facts_cache = {} if facts_cache is None else facts_cache
        tombstone_cache = {} if tombstone_cache is None else tombstone_cache
        facts = {target: facts_cache[target] for target in keys if target in facts_cache}
        rrt = {}
        for repository, selected in (
            (
                ModelMigrationTargetRepository(),
                tuple(key for key in keys if key.target_type == TargetType.MODEL and key not in facts),
            ),
            (
                KnowledgeMigrationTargetRepository(),
                tuple(key for key in keys if key.target_type != TargetType.MODEL and key not in facts),
            ),
        ):
            for start in range(0, len(selected), 200):
                batch = selected[start : start + 200]
                actual = await repository.ainspect(session, source_key=key, targets=batch)
                transaction.assert_current(session)
                if tuple(fact.key for fact in actual) != batch:
                    blocked("physical_after_incomplete")
                facts.update((fact.key, fact) for fact in actual)
                facts_cache.update((fact.key, fact) for fact in actual)
        states = [parse_frozen(record.frozen_state) for record in records]
        deletion_keys = set(keys)
        parents = {}
        for record, state in zip(records, states, strict=True):
            if record.target.target_type == TargetType.KNOWLEDGE_FILE:
                parent = record.physical_fact.knowledge_id
                parent = (
                    str(parent)
                    if parent is not None
                    else state["original"]["target_space_id"]
                    if state["original"]
                    else None
                )
                if parent is not None:
                    parents[record.target] = TargetKey(TargetType.KNOWLEDGE_SPACE, parent)
                    deletion_keys.add(parents[record.target])
        for state in states:
            for row in (*state["target_tombstones"], *state["ancestor_tombstones"]):
                deletion_keys.add(TargetKey(row["target_type"], row["target_id"]))
        deletion_keys = tuple(sorted(deletion_keys, key=lambda key: key.lock_order_key))
        rrt.update((target, tombstone_cache[target]) for target in deletion_keys if target in tombstone_cache)
        missing = tuple(target for target in deletion_keys if target not in rrt)
        for start in range(0, len(missing), 200):
            batch = missing[start : start + 200]
            rows = await self.backfill.repository.aload_tombstones(session, targets=batch)
            transaction.assert_current(session)
            for target in batch:
                rrt[target] = []
            for row in rows:
                rrt[TargetKey(row["target_type"], row["target_id"])].append(sql_value(row))
            tombstone_cache.update((target, rrt[target]) for target in batch)
        for record, state in zip(records, states, strict=True):
            before, after = asdict(record.physical_fact), asdict(facts[record.target])
            if before != after:
                # Only the signed Root0→3 conversion changes this physical fact.
                parent = record.physical_fact.knowledge_id if record.target.target_type != TargetType.MODEL else None
                command = self.resources.get((record.physical_fact.target_tenant_id, parent))
                if not (
                    command is not None
                    and before.get("knowledge_type") == 0
                    and after.get("knowledge_type") == 3
                    and before["exists"] is True
                    and after["exists"] is True
                ):
                    blocked("physical_target_changed_after_freeze")
                before["knowledge_type"], before["revision_digest"] = 3, after["revision_digest"]
                if before != after:
                    blocked("physical_target_parent_changed")
            if rrt[record.target] != state["target_tombstones"]:
                blocked("original_deletion_evidence_changed")
        legacy_groups = {}
        for record, state in zip(records, states, strict=True):
            parent = parents.get(record.target)
            if parent is not None and rrt[parent] != state["ancestor_tombstones"]:
                blocked("ancestor_deletion_changed_after_freeze")
            if state["legacy"] is not None:
                group = legacy_groups.setdefault(record.target, {"proof": state["legacy"], "rows": []})
                if group["proof"] != state["legacy"]:
                    blocked("legacy_proof_changed_between_slots")
                group["rows"].append(state["original"])
        if legacy_groups:
            from bisheng.knowledge.domain.repositories.reference_legacy_evidence_repository import (
                KnowledgeLegacyEvidenceRepository,
            )

            for target, value in legacy_groups.items():
                proof = value["proof"]
                actual = await KnowledgeLegacyEvidenceRepository().aload_snapshot_evidence(
                    session, key, target, rows=value["rows"], run_id=proof["run_id"], evidence_key=proof["evidence_key"]
                )
                transaction.assert_current(session)
                if actual != (proof["run_id"], proof["baseline_hash"], proof["evidence_key"]):
                    blocked("legacy_descriptor_changed_after_freeze")
        return facts

    async def _prefetch_targets(self, session, batch):
        """Observe each exact target once per native transaction, not per slot."""
        facts, tombstones, targets, deletion_keys = {}, {}, set(), set()
        for _, records in batch:
            for record in records:
                targets.add(record.target)
                deletion_keys.add(record.target)
                state = parse_frozen(record.frozen_state)
                for row in (*state["target_tombstones"], *state["ancestor_tombstones"]):
                    deletion_keys.add(TargetKey(row["target_type"], row["target_id"]))
                if record.target.target_type == TargetType.KNOWLEDGE_FILE:
                    parent = record.physical_fact.knowledge_id
                    if parent is None and state["original"]:
                        parent = state["original"]["target_space_id"]
                    if parent is not None:
                        deletion_keys.add(TargetKey(TargetType.KNOWLEDGE_SPACE, str(parent)))
        key = batch[0][0].source_key
        for repository, selected in (
            (
                ModelMigrationTargetRepository(),
                tuple(
                    sorted(
                        (target for target in targets if target.target_type == TargetType.MODEL),
                        key=lambda value: value.lock_order_key,
                    )
                ),
            ),
            (
                KnowledgeMigrationTargetRepository(),
                tuple(
                    sorted(
                        (target for target in targets if target.target_type != TargetType.MODEL),
                        key=lambda value: value.lock_order_key,
                    )
                ),
            ),
        ):
            for start in range(0, len(selected), 200):
                group = selected[start : start + 200]
                observed = await repository.ainspect(session, source_key=key, targets=group)
                if tuple(fact.key for fact in observed) != group:
                    blocked("physical_after_incomplete")
                facts.update((fact.key, fact) for fact in observed)
        ordered = tuple(sorted(deletion_keys, key=lambda value: value.lock_order_key))
        for start in range(0, len(ordered), 200):
            group = ordered[start : start + 200]
            observed = await self.backfill.repository.aload_tombstones(session, targets=group)
            tombstones.update((target, []) for target in group)
            for row in observed:
                tombstones[TargetKey(row["target_type"], row["target_id"])].append(sql_value(row))
        return facts, tombstones

    def _templates(self, key, pairs, facts, revision):
        values, counts = (
            [],
            {"valid_count": 0, "invalid_legacy_count": 0, "invalid_deleted_count": 0, "invalid_scope_count": 0},
        )
        for reference, original in pairs:
            decision = source_decision(original, tenant_id=key.tenant_id).data["disposition"]
            state, fact = parse_frozen(original.frozen_state), facts[reference.target]
            old, legacy = state["original"], state["legacy"]
            if decision == "initial_missing":
                legacy = {
                    "run_id": self.frozen.run_id,
                    "evidence_key": digest(
                        {
                            "source": (key.tenant_id, key.source_type.value, key.source_id, key.source_version),
                            "target": (reference.target.target_type.value, reference.target.target_id),
                            "baseline_hash": self.frozen.baseline_ref["sha256"],
                            "fact": asdict(original.physical_fact),
                        }
                    ),
                }
            counts[
                "invalid_legacy_count"
                if legacy
                else "invalid_deleted_count"
                if decision == "existing_invalid_deleted"
                else "invalid_scope_count"
                if decision == "existing_invalid_scope"
                else "valid_count"
            ] += 1
            deletion = state["target_tombstones"] or state["ancestor_tombstones"]
            owner = deletion[0]["target_tenant_id"] if deletion and legacy is None else fact.target_tenant_id
            if owner is None and old is not None:
                owner = old["target_tenant_id"]
            parent = (
                getattr(fact, "knowledge_id", None)
                if reference.target.target_type == TargetType.KNOWLEDGE_FILE
                else None
            )
            parent = str(parent) if parent is not None else old["target_space_id"] if old else None
            if decision == "existing_invalid_scope" and reference.target.target_type == TargetType.KNOWLEDGE_SPACE:
                parent = reference.target.target_id
            values.append(
                {
                    "slot_key": reference.slot_key,
                    "target_type": reference.target.target_type.value,
                    "target_id": reference.target.target_id,
                    "target_tenant_id": owner,
                    "target_space_id": parent,
                    "source_revision": revision,
                    "legacy_invalid_reason": "target_missing" if legacy else None,
                    "legacy_run_id": legacy["run_id"] if legacy else None,
                    "legacy_evidence_key": legacy["evidence_key"] if legacy else None,
                }
            )
        return tuple(values), counts

    async def _records(self, tenant, *, after=0):
        records, entry = [], None
        async for chunk in self.reader.aiter_reference_chunks(self.plan, tenant_id=tenant, after_source_ordinal=after):
            if entry is not None and entry is not chunk.source:
                blocked("source_chunk_changed")
            entry = chunk.source
            records.extend(chunk.records)
            if chunk.complete:
                yield entry.header, tuple(records)
                records, entry = [], None
        if records or entry is not None:
            blocked("partial_source_stream")

    async def _batches(self, tenant, *, after=0):
        batch, references, size = [], 0, 0
        async for header, records in self._records(tenant, after=after):
            item_size = len(canonical(asdict(header))) + sum(len(canonical(asdict(row))) for row in records)
            if batch and (
                len(batch) >= self.source_batch_limit
                or references + len(records) > self.source_reference_limit
                or size + item_size > self.source_byte_limit
            ):
                yield tuple(batch)
                batch, references, size = [], 0, 0
            batch.append((header, records))
            references += len(records)
            size += item_size
        if batch:
            yield tuple(batch)

    async def _census(self, session, tenant):
        await self.sources.acensus(
            session, plan=self.plan, tenant=tenant, reference_repository=self.backfill.repository
        )

    async def _native_current(self, session, tenant, proofs):
        from bisheng.knowledge.application.unification_reference_reconciliation import verify_proven_native_current

        reconciliation = self.plan.reconciliation
        if reconciliation is None or not reconciliation.registered_additions:
            return
        roots = {row.header.root_key for row in self.plan.roots}
        roots.update(row.header.root_key for row in self.plan.retired if row.header.source_key is None)
        for item in reconciliation.registered_additions:
            key = SourceKey(**item["key"])
            if key.tenant_id != tenant:
                continue
            current = await verify_proven_native_current(
                session, expected=item, repository=self.sources.repository, index_repository=self.backfill.repository
            )
            self._tail_sources[key] = current["source_receipt"], current["index_receipt"]
            self._tail_costs[key] = current["valid_count"], current["source_bytes"]
            proof = proofs[key.source_type.value]
            root = SourceRootKey(key.tenant_id, key.source_type, key.source_id)
            if root not in roots:
                proof["root_count"] += 1
                roots.add(root)
            proof["source_count"] += 1
            proof["zero_reference_count"] += current["valid_count"] == 0
            proof["reference_count"] += current["valid_count"]
            proof["valid_count"] += current["valid_count"]
            proof["source_digest"] = digest(
                {"previous": proof["source_digest"], "native_current": item, "proof_refs": reconciliation.proof_refs}
            )
            proof["reference_digest"] = digest(
                {
                    "previous": proof["reference_digest"],
                    "native_current": {name: current[name] for name in ("fact", "targets_digest", "valid_count")},
                }
            )

    async def _retire_item(self, session, header, *, covered, write, before=False):
        from bisheng.knowledge.application.unification_reference_state import (
            PHYSICAL_ROOT_ABSENT,
            parse_retired,
            retired_index,
        )
        from bisheng.knowledge.domain.repositories.reference_legacy_evidence_repository import (
            KnowledgeLegacyEvidenceRepository,
        )

        await self.sources.averify_retired(session, header=header)
        skip = header.source_key is not None and header.root_key in covered
        if skip:
            if header.frozen_index is not None:
                blocked("retired_root_double_inventory")
            after = {"covered_by_retired_root": asdict(header.root_key)}
        else:
            baseline = parse_retired(header.frozen_index)
            actual = parse_retired(
                await retired_index(
                    session,
                    repository=self.backfill.repository,
                    legacy=KnowledgeLegacyEvidenceRepository(),
                    root_key=header.root_key,
                    source_key=header.source_key,
                )
            )
            if before:
                if write or actual != baseline:
                    blocked("retired_original_index_changed")
                return actual
            if write:
                if actual != baseline:
                    blocked("retired_original_index_changed")
                await self.backfill.repository.aclear_registered_retired(
                    session,
                    root_key=header.root_key,
                    source_key=header.source_key,
                    cleanup_empty_root=False,
                    **(
                        {"expected_empty_heads": (baseline["root_head"], *baseline["source_heads"])}
                        if header.lifecycle == PHYSICAL_ROOT_ABSENT
                        else {}
                    ),
                )
                actual = parse_retired(
                    await retired_index(
                        session,
                        repository=self.backfill.repository,
                        legacy=KnowledgeLegacyEvidenceRepository(),
                        root_key=header.root_key,
                        source_key=header.source_key,
                    )
                )
            if (
                actual["source_heads"]
                or actual["raw_count"]
                or actual["legacy"]
                or (header.source_key is None and actual["root_head"] is not None)
            ):
                blocked("retired_after_not_empty")
            after = {**actual, "root_head": None} if header.source_key is not None else actual
        return after

    async def _retire(self, tenant, *, verify_only, skip_committed=False):
        rows = tuple(item.header for item in self.plan.retired if item.header.root_key.tenant_id == tenant)
        covered = {row.root_key for row in rows if row.source_key is None}
        async with self.app._session() as session, session.begin():
            run = await self.app._scope_run(session, self.frozen)
            goal = run.checkpoints.get("backfilling", {}).get("references_retired")
        _validate_progress(goal, len(rows))
        prefix = goal["processed_count"] if goal else 0
        checksum, acknowledged = (
            (goal["digest"] if skip_committed and goal else digest({"retired": _seed(self.frozen, tenant)})),
            goal,
        )
        for batch_start in range(prefix if skip_committed else 0, len(rows), self.source_batch_limit):
            batch = tuple(enumerate(rows[batch_start : batch_start + self.source_batch_limit], batch_start + 1))
            async with self.app._session() as session, session.begin():
                run = await self.app._scope_run(session, self.frozen)
                if run.checkpoints.get("backfilling", {}).get("references_retired") != acknowledged:
                    blocked("retired_checkpoint_changed")
                observed, writes = {}, False
                for ordinal, header in sorted(
                    batch,
                    key=lambda entry: (
                        entry[1].root_key.source_type.value,
                        entry[1].root_key.source_id,
                        entry[1].source_key.source_version if entry[1].source_key else "",
                    ),
                ):
                    write = not verify_only and run.phase == "backfilling" and ordinal > prefix
                    observed[ordinal] = await self._retire_item(session, header, covered=covered, write=write)
                    writes = writes or write
                for ordinal, header in batch:
                    checksum = digest(
                        {
                            "previous": checksum,
                            "root": asdict(header.root_key),
                            "source": asdict(header.source_key) if header.source_key else None,
                            "baseline": header.frozen_index,
                            "business": header.business_revision_digest,
                            "after": observed[ordinal],
                        }
                    )
                    checkpoint = _checkpoint(self.frozen, tenant, ordinal, checksum, ordinal == len(rows))
                    if ordinal == prefix and goal != {**checkpoint, "complete": goal["complete"]}:
                        blocked("retired_committed_prefix_changed")
                if writes:
                    await self.app.runs.acheckpoint(
                        session,
                        **self.app._identity(self.frozen),
                        expected_phase="backfilling",
                        checkpoint_key="references_retired",
                        expected_checkpoint=acknowledged,
                        checkpoint=checkpoint,
                    )
                    acknowledged = checkpoint
            report_progress(
                "reference_retired_verify" if verify_only else "reference_retired",
                tenant_id=tenant,
                processed=batch[-1][0],
                total=len(rows),
                unit="retired_source",
                committed=acknowledged["processed_count"] if acknowledged else 0,
                cursor=acknowledged["cursor"] if acknowledged else None,
            )
        if not rows:
            checkpoint = _checkpoint(self.frozen, tenant, 0, checksum, True)
            if goal is not None and goal != checkpoint:
                blocked("empty_retired_checkpoint_changed")
            if goal is None:
                async with self.app._session() as session, session.begin():
                    run = await self.app._scope_run(session, self.frozen)
                    if verify_only or run.phase != "backfilling":
                        blocked("retired_checkpoint_missing")
                    await self.app.runs.acheckpoint(
                        session,
                        **self.app._identity(self.frozen),
                        expected_phase="backfilling",
                        checkpoint_key="references_retired",
                        expected_checkpoint=None,
                        checkpoint=checkpoint,
                    )
                    acknowledged = checkpoint
        if acknowledged is None or acknowledged["complete"] is not True:
            blocked("retired_stream_incomplete")
        return checksum

    async def _tenant(self, tenant, *, verify_only=False, registration_only=False):
        from bisheng.knowledge.application.unification_reference_state import PHYSICAL_ROOT_ABSENT
        from bisheng.knowledge.application.unification_workflow_retention import invalid_root

        phase, goal = await self._phase(tenant)
        retired_digest = await self._retire(tenant, verify_only=verify_only, skip_committed=registration_only)
        entries = tuple(entry for entry in self.plan.sources if entry.header.source_key.tenant_id == tenant)
        _validate_progress(goal, len(entries))
        if phase != "backfilling" and (goal is None or goal["complete"] is not True):
            blocked("later_phase_without_backfill")
        proofs = {
            kind.value: {
                "extractor_version": _VERSIONS[kind.value],
                "root_count": 0,
                "source_count": 0,
                "zero_reference_count": 0,
                "reference_count": 0,
                "valid_count": 0,
                "invalid_legacy_count": 0,
                "invalid_deleted_count": 0,
                "invalid_scope_count": 0,
                "source_digest": digest({"seed": _seed(self.frozen, tenant), "retired": retired_digest}),
                "reference_digest": _seed(self.frozen, tenant),
            }
            for kind in SourceType
        }
        if self.plan.reconciliation and self.plan.reconciliation.proof_refs:
            for proof in proofs.values():
                proof["source_digest"] = digest(
                    {
                        "previous": proof["source_digest"],
                        "reconciliation_refs": self.plan.reconciliation.proof_refs,
                    }
                )
        for located in self.plan.roots:
            if located.header.root_key.tenant_id == tenant:
                proofs[located.header.root_key.source_type.value]["root_count"] += 1
        for located in self.plan.retired:
            if (
                located.header.root_key.tenant_id == tenant
                and located.header.source_key is None
                and located.header.lifecycle != PHYSICAL_ROOT_ABSENT
                and not invalid_root(located.header)
            ):
                proofs[located.header.root_key.source_type.value]["root_count"] += 1
        checksum, ordinal = _seed(self.frozen, tenant), 0
        prefix = goal["processed_count"] if goal else 0
        acknowledged = goal
        if registration_only:
            checksum, ordinal = (goal["digest"] if goal else checksum), prefix
        last_log = time.monotonic()
        if registration_only:
            logger.info(
                "reference_registration stage=sources tenant={} processed={} total={}", tenant, ordinal, len(entries)
            )
        report_progress(
            "reference_verify" if verify_only else "reference_register",
            tenant_id=tenant,
            processed=ordinal,
            total=len(entries),
            committed=prefix,
            unit="source",
        )
        async for batch in self._batches(tenant, after=prefix if registration_only else 0):
            write = not verify_only and phase == "backfilling" and ordinal >= prefix
            async with self.app._session() as session, session.begin():
                transaction = TransactionIdentity.capture(session)
                run = await self.app._scope_run(session, self.frozen)
                if run.checkpoints.get("backfilling", {}).get("references") != acknowledged:
                    blocked("reference_checkpoint_changed")
                prepared_items, observed = [], []
                target_cache, deletion_cache = await self._prefetch_targets(session, batch)
                # Business roots are acquired in stable order, while the final
                # hash and ordinal retain their original frozen stream order.
                loaded = {}
                batch_reader = getattr(self.sources.repository, "aload_reference_sources", None)
                source_snapshots = (
                    await batch_reader(
                        session, source_keys=tuple(header.source_key for header, _ in batch), for_update=True
                    )
                    if callable(batch_reader)
                    else None
                )
                if source_snapshots is not None and set(source_snapshots) != {header.source_key for header, _ in batch}:
                    blocked("source_batch_incomplete")
                for header, records in sorted(
                    batch,
                    key=lambda pair: (
                        pair[0].source_key.source_type.value,
                        pair[0].source_key.source_id,
                        pair[0].source_key.source_version,
                    ),
                ):
                    key = header.source_key
                    loaded[key] = await self.sources.aload(
                        session,
                        header=header,
                        records=records,
                        conversion=self.conversions.get((tenant, key.source_type, key.source_id)),
                        snapshot=source_snapshots[key] if source_snapshots is not None else None,
                    )
                for header, records in batch:
                    key = header.source_key
                    index = parse_frozen(header.frozen_index, index=True)
                    revision = (index["root_head"]["source_revision"] if index["root_head"] else 0) + 1
                    if index["source_head"] and index["source_head"]["source_revision"] >= revision:
                        blocked("original_root_revision_inconsistent")
                    actual_header, pairs = loaded[key]
                    facts = await self._targets(
                        session, key, records, facts_cache=target_cache, tombstone_cache=deletion_cache
                    )
                    templates, counts = self._templates(key, pairs, facts, revision)
                    prepared_items.append(
                        {
                            "source_key": key,
                            "frozen_index": index,
                            "rows": templates,
                            "extractor_version": actual_header.extractor_version,
                            "reference_digest": actual_header.reference_digest,
                            "root_revision": revision,
                        }
                    )
                    observed.append((actual_header, templates, counts))
                prepared = await self.backfill.aprepare_registered_batch(
                    session,
                    items=tuple(prepared_items),
                    binding=self.app._identity(self.frozen),
                    expected_checkpoint=acknowledged,
                    write=write,
                )
                afters = await self.backfill.aapply_registered_batch(session, prepared=prepared)
                transaction.assert_current(session)
                for (actual_header, templates, counts), after in zip(observed, afters, strict=True):
                    key = actual_header.source_key
                    if verify_only:
                        if source_snapshots is None:
                            blocked("tail_source_batch_port_required")
                        self._tail_sources[key] = self._business_receipt(source_snapshots[key]), after
                        self._tail_costs[key] = (
                            len(templates),
                            len(canonical(prepared.snapshots[key]))
                            + len(
                                canonical(
                                    {
                                        "root": asdict(source_snapshots[key][0]),
                                        "version": asdict(source_snapshots[key][1])
                                        if source_snapshots[key][1]
                                        else None,
                                        "children": tuple(asdict(child) for child in source_snapshots[key][2]),
                                    }
                                )
                            ),
                        )
                    checksum = digest(
                        {
                            "previous": checksum,
                            "source": (key.tenant_id, key.source_type.value, key.source_id, key.source_version),
                            "after": after,
                        }
                    )
                    ordinal += 1
                    if ordinal == prefix and goal != _checkpoint(
                        self.frozen, tenant, ordinal, checksum, goal["complete"]
                    ):
                        blocked("committed_reference_prefix_changed")
                    proof = proofs[key.source_type.value]
                    proof["source_count"] += 1
                    proof["zero_reference_count"] += not templates
                    proof["reference_count"] += len(templates)
                    for name, count in counts.items():
                        proof[name] += count
                    proof["source_digest"] = digest(
                        {
                            "previous": proof["source_digest"],
                            "key": asdict(key),
                            "configuration": actual_header.configuration_digest,
                            "business": actual_header.business_revision_digest,
                        }
                    )
                    proof["reference_digest"] = digest({"previous": proof["reference_digest"], "after": after})
                if write:
                    checkpoint = _checkpoint(self.frozen, tenant, ordinal, checksum, ordinal == len(entries))
                    await self.app.runs.acheckpoint(
                        session,
                        **self.app._identity(self.frozen),
                        expected_phase="backfilling",
                        checkpoint_key="references",
                        expected_checkpoint=acknowledged,
                        checkpoint=checkpoint,
                    )
                    acknowledged = checkpoint
            if ordinal == len(entries) or time.monotonic() - last_log >= 15:
                logger.info(
                    "reference_migration stage={} tenant={} processed={} total={}",
                    "verify" if verify_only else "register",
                    tenant,
                    ordinal,
                    len(entries),
                )
                last_log = time.monotonic()
            report_progress(
                "reference_verify" if verify_only else "reference_register",
                tenant_id=tenant,
                processed=ordinal,
                total=len(entries),
                committed=acknowledged["processed_count"] if acknowledged else 0,
                cursor=acknowledged["cursor"] if acknowledged else None,
                unit="source",
            )
        if not entries and goal is not None and goal != _checkpoint(self.frozen, tenant, 0, checksum, True):
            blocked("empty_source_checkpoint_changed")
        if ordinal != len(entries):
            blocked("source_stream_incomplete")
        async with self.app._session() as session, session.begin():
            if not registration_only:
                await self._native_current(session, tenant, proofs)
                await self._census(session, tenant)
            run = await self.app._scope_run(session, self.frozen)
            if not entries and phase == "backfilling" and not verify_only and goal is None:
                acknowledged = _checkpoint(self.frozen, tenant, 0, checksum, True)
                await self.app.runs.acheckpoint(
                    session,
                    **self.app._identity(self.frozen),
                    expected_phase="backfilling",
                    checkpoint_key="references",
                    expected_checkpoint=None,
                    checkpoint=acknowledged,
                )
            if phase == "backfilling":
                if acknowledged is None or acknowledged["complete"] is not True:
                    blocked("reference_checkpoint_not_complete")
                if verify_only and not registration_only:
                    await self.app.runs.aadvance(
                        session, **self.app._identity(self.frozen), expected_phase="backfilling", next_phase="verifying"
                    )
        return proofs

    @staticmethod
    def _business_receipt(snapshot):
        root, version, children = snapshot
        return digest(
            {
                "root": asdict(root),
                "version": asdict(version) if version else None,
                "children": tuple(asdict(child) for child in children),
            }
        )

    def _tail_batches(self, keys):
        batch, references, size = [], 0, 0
        for key in keys:
            count, byte_size = self._tail_costs[key]
            if batch and (
                len(batch) >= self.source_batch_limit
                or references + count > self.source_reference_limit
                or size + byte_size > self.source_byte_limit
            ):
                yield tuple(batch)
                batch, references, size = [], 0, 0
            batch.append(key)
            references += count
            size += byte_size
        if batch:
            yield tuple(batch)

    async def _verify_tail(self, session):
        """Reject cross-batch drift in the same native transaction as Coverage.

        Stopped services remain required. Existing business/index root latches
        and exact full snapshots detect supported writers changing an earlier
        verification batch; this is not an online linearizability protocol.
        """
        from bisheng.knowledge.domain.repositories.unification_reference_batch_repository import (
            UnificationReferenceBatchRepository,
        )

        native_roots = UnificationReferenceBatchRepository()
        for tenant in self.frozen.tenant_ids:
            with tenant_execution_scope(tenant):
                current_run = await self.app._scope_run(session, self.frozen)
                if tenant == self.frozen.tenant_ids[0] and current_run.phase == "completed":
                    # Normal certification performs these native global gates
                    # below in this same transaction. Completed strict verify
                    # does not call the certifier and needs its own live check.
                    await self.sources.repository.avalidate_global_orphans(session)
                    await self.sources.repository.avalidate_registered_source_tenants(session)
                roots = {
                    item.header.root_key
                    for item in (*self.plan.roots, *self.plan.retired)
                    if item.header.root_key.tenant_id == tenant
                }
                roots.update(
                    SourceRootKey(key.tenant_id, key.source_type, key.source_id)
                    for key in self._tail_sources
                    if key.tenant_id == tenant
                )
                ordered = sorted(roots, key=lambda key: (key.source_type.value, key.source_id))
                for offset in range(0, len(ordered), 200):
                    batch = tuple(ordered[offset : offset + 200])
                    await native_roots.alock_reference_roots(session, root_keys=batch)
                    await self.backfill.repository.alock_roots(session, root_keys=batch)
        for tenant in self.frozen.tenant_ids:
            with tenant_execution_scope(tenant):
                keys = sorted(
                    (key for key in self._tail_sources if key.tenant_id == tenant),
                    key=lambda key: (key.source_type.value, key.source_id, key.source_version),
                )
                processed = 0
                for batch in self._tail_batches(keys):
                    business = await self.sources.repository.aload_reference_sources(session, source_keys=batch)
                    indexes = await self.backfill.repository.aload_raw_snapshots(session, source_keys=batch)
                    if set(business) != set(batch) or set(indexes) != set(batch):
                        blocked("tail_source_batch_incomplete")
                    if any(
                        self._tail_sources[key] != (self._business_receipt(business[key]), fingerprint(indexes[key]))
                        for key in batch
                    ):
                        blocked("tail_source_revision_changed")
                    processed += len(batch)
                    report_progress(
                        "reference_tail",
                        tenant_id=tenant,
                        processed=processed,
                        total=len(keys),
                        unit="source",
                        waiting="database",
                    )
                retired = tuple(item.header for item in self.plan.retired if item.header.root_key.tenant_id == tenant)
                covered = {header.root_key for header in retired if header.source_key is None}
                for header in sorted(
                    retired,
                    key=lambda header: (
                        header.root_key.source_type.value,
                        header.root_key.source_id,
                        header.source_key.source_version if header.source_key else "",
                    ),
                ):
                    await self._retire_item(session, header, covered=covered, write=False)
                await self._census(session, tenant)

    async def arun(self):
        for tenant in self.frozen.tenant_ids:
            with tenant_execution_scope(tenant):
                await self._tenant(tenant, registration_only=True)
        proofs = {}
        for tenant in self.frozen.tenant_ids:
            with tenant_execution_scope(tenant):
                proofs[tenant] = await self._tenant(tenant, verify_only=True)
        if self.plan.rootless_retentions:
            from collections import defaultdict

            retained = defaultdict(list)
            for tenant, proof in self.plan.rootless_retentions:
                retained[tenant].append(proof)
            # Final live SQL + complete Store proof immediately before issuing
            # Coverage, including completed-Run verification/resume. Reuse the
            # already verified frozen control pages; do not rescan the artifacts.
            await self.app._verify_structural_retentions(self.frozen, retained, environment=self.environment)
        async with self.app._session() as session, session.begin():
            actual = await self.app._admit(self.frozen.run_id, self.frozen.writer_contract_version)
            if actual != self.frozen:
                blocked("tail_universe_changed")
            await self._verify_tail(session)
            repository = production_coverage_factory(
                session, writer_contract_version=self.frozen.writer_contract_version
            )
            run = await self.app._scope_run(session, self.frozen)
            if run.phase == "completed":
                ready = await repository.arequire_global_ready()
                from bisheng.knowledge.domain.repositories.unification_coverage_repository import (
                    UnificationCoverageRepository,
                )

                rows = await UnificationCoverageRepository().aload_runs(session)
                if any(
                    row["verification_report"].get("reference_coverage", {}).get("proofs") != proofs[row["tenant_id"]]
                    for row in rows
                    if row["run_id"] == self.frozen.run_id
                ):
                    blocked("completed_certificate_actual_proofs_changed")
                epoch = ready.coverage_epoch
            else:
                epoch = await certify_migration(session, frozen=self.frozen, proofs=proofs)
                await repository.arequire_global_ready()
        return ReferenceMigrationReport(
            self.frozen.run_id,
            self.frozen.writer_contract_version,
            self.frozen.baseline_ref["sha256"],
            self.frozen.plan_ref["sha256"],
            self.frozen.tenant_ids,
            epoch,
            True,
        )


async def run_references(
    application, *, reuse_completed=False, reconciliation_ref=None, semantic_projection_ref=None, **inputs
):
    if reuse_completed:
        await application.arun_permissions(reuse_completed=True, **inputs)
    else:
        await application.arun_permissions(**inputs)
    frozen = await application._admit(inputs["run_id"], inputs["writer_contract_version"])
    reader = UnificationReferencePlanReader(inventory=application.reader, artifact_store=application.store)
    plan = await reader.aprepare(frozen, **{name: inputs[name] for name in ("environment", "backup_ref", "schema_ref")})
    from bisheng.knowledge.application.unification_reference_reconciliation import (
        prepare_full_reconciliation,
        require_reconciliation_candidate,
    )

    if reconciliation_ref is not None:
        await require_reconciliation_candidate(
            application,
            frozen=frozen,
            descriptor=reconciliation_ref,
            environment=inputs["environment"],
            operator_id=inputs["operator_id"],
            plan=plan,
            semantic_projection_ref=semantic_projection_ref,
        )

    plan = await prepare_full_reconciliation(
        application,
        frozen=frozen,
        plan=plan,
        reader=reader,
        semantic_projection_ref=semantic_projection_ref,
        **inputs,
    )
    return await ReferenceMigration(application, frozen, plan, reader, environment=inputs["environment"]).arun()
