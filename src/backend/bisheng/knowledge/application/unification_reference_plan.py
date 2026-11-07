"""Readonly frozen source closure; these facts grant no binding authority."""

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Literal

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application.unification_conversion_plan import COMMAND_RECORD_TYPES
from bisheng.knowledge.application.unification_inventory_codec import decode_inventory_page
from bisheng.knowledge.application.unification_preflight import source_decision
from bisheng.knowledge.application.unification_source_codec import decode_source_page
from bisheng.knowledge.application.unification_sources import (
    ReferenceInventoryRecord,
    RetiredInventoryRecord,
    RootInventoryRecord,
    SourceInventoryRecord,
)
from bisheng.knowledge.domain.repositories.unification_run_repository import FrozenGlobalInventoryResult
from bisheng.knowledge.domain.services.unification_fingerprints import digest
from bisheng.resource_reference.application.contracts import (
    ReferenceSetDigestAccumulator,
    ReferenceSpec,
    SourceKey,
    SourceRootKey,
)

_DEFERRED = frozenset((*COMMAND_RECORD_TYPES.values(), "permission_plan"))


def _blocked(reason):
    raise KnowledgeOperationPlanConflictError(reason=f"migration_reference_plan_{reason}")


def _root(key):
    return SourceRootKey(key.tenant_id, key.source_type, key.source_id)


def _seed(key):
    return digest(
        {
            "kind": "source_decision_stream_v1",
            "source": (key.tenant_id, key.source_type.value, key.source_id, key.source_version),
        }
    )


def _fold(previous, record):
    return digest({"previous": previous, "record_type": record.record_type, "data": record.data})


@dataclass(frozen=True, slots=True)
class ReferencePageRef:
    section: Literal["sources", "conversion"]
    tenant_id: int
    page_index: int
    record_count: int
    object_key: str
    sha256: str


@dataclass(frozen=True, slots=True)
class RecordPosition:
    page: ReferencePageRef
    record_index: int


@dataclass(frozen=True, slots=True)
class RecordSpan:
    first: RecordPosition
    last: RecordPosition


@dataclass(frozen=True, slots=True)
class SourcePlanEntry:
    header: SourceInventoryRecord
    header_at: RecordPosition
    references: RecordSpan | None
    decisions: RecordSpan | None
    decision_digest: str


@dataclass(frozen=True, slots=True)
class LocatedRoot:
    header: RootInventoryRecord
    at: RecordPosition


@dataclass(frozen=True, slots=True)
class LocatedRetired:
    header: RetiredInventoryRecord
    at: RecordPosition


@dataclass(frozen=True, slots=True)
class FrozenReferencePlan:
    frozen: FrozenGlobalInventoryResult
    pages: tuple[ReferencePageRef, ...]
    sources: tuple[SourcePlanEntry, ...]
    roots: tuple[LocatedRoot, ...]
    retired: tuple[LocatedRetired, ...]


@dataclass(frozen=True, slots=True)
class ReferenceSourceChunk:
    source: SourcePlanEntry
    records: tuple[ReferenceInventoryRecord, ...]
    complete: bool


class _Source:
    def __init__(self, header, at):
        self.header, self.at = header, at
        self.accumulator = ReferenceSetDigestAccumulator()
        self.count, self.last_key, self.first, self.last = 0, None, None, None
        self.decision_digest = _seed(header.source_key)

    def add(self, record, at):
        if record.source_key != self.header.source_key:
            _blocked("reference_source")
        key = (record.slot_key, record.target.target_type.value, record.target.target_id)
        if self.last_key is not None and key <= self.last_key:
            _blocked("reference_order")
        self.accumulator.update(ReferenceSpec(record.slot_key, record.target))
        self.decision_digest = _fold(
            self.decision_digest, source_decision(record, tenant_id=record.source_key.tenant_id)
        )
        self.first, self.last = self.first or at, at
        self.last_key, self.count = key, self.count + 1

    def finish(self):
        if self.count != self.header.reference_count or self.accumulator.hexdigest() != self.header.reference_digest:
            _blocked("reference_set")
        return SourcePlanEntry(
            self.header, self.at, RecordSpan(self.first, self.last) if self.first else None, None, self.decision_digest
        )


class _Decisions:
    def __init__(self, key):
        self.key, self.count, self.last_key = key, 0, None
        self.first, self.last, self.digest = None, None, _seed(key)

    def add(self, record, at):
        value = record.data
        key = (value["slot_key"], value["target_type"], value["target_id"])
        if self.last_key is not None and key <= self.last_key:
            _blocked("decision_order")
        self.count, self.last_key = self.count + 1, key
        self.first, self.last = self.first or at, at
        self.digest = _fold(self.digest, record)


class UnificationReferencePlanReader:
    def __init__(self, *, inventory, artifact_store):
        if inventory.store is not artifact_store:
            _blocked("artifact_store_mismatch")
        self.inventory, self.store = inventory, artifact_store

    async def aprepare(self, frozen, *, environment, backup_ref, schema_ref, current=None):
        current = self._current(current)
        pages, sources, roots, retired = [], {}, {}, []
        active, seen, retired_roots, retired_sources = {}, set(), set(), set()
        decisions, latest_decision = {}, {}

        def close(tenant):
            state = active.pop(tenant, None)
            if state is not None:
                sources[state.header.source_key] = state.finish()

        async for page in self.inventory.aiter_frozen_pages(
            frozen, environment=environment, backup_ref=backup_ref, schema_ref=schema_ref, current=current
        ):
            if page.section not in {"sources", "conversion"}:
                continue
            if page.kind != ("baseline" if page.section == "sources" else "plan"):
                _blocked("section_kind")
            locator = ReferencePageRef(
                page.section,
                page.tenant_id,
                page.page_index,
                page.record_count,
                page.descriptor["object_key"],
                page.descriptor["sha256"],
            )
            if page.tenant_id is not None:
                pages.append(locator)
            if page.section == "sources":
                rows = decode_source_page(
                    page.content, run_id=frozen.run_id, tenant_id=page.tenant_id, page_index=page.page_index
                ).records
            else:
                rows = decode_inventory_page(
                    page.content,
                    run_id=frozen.run_id,
                    section="conversion",
                    scope=page.scope,
                    tenant_id=page.tenant_id,
                    page_index=page.page_index,
                    kind="plan",
                ).records
            for index, record in enumerate(rows):
                current()
                at = RecordPosition(locator, index)
                if page.section == "conversion":
                    if record.record_type in _DEFERRED:
                        continue
                    if record.record_type != "source_decision":
                        _blocked("unknown_conversion_record")
                    value = record.data
                    try:
                        key = SourceKey(
                            value["tenant_id"], value["source_type"], value["source_id"], value["source_version"]
                        )
                    except (TypeError, ValueError) as error:
                        raise KnowledgeOperationPlanConflictError(
                            reason="migration_reference_plan_decision_key"
                        ) from error
                    if key.tenant_id != page.tenant_id:
                        _blocked("decision_tenant")
                    if latest_decision.get(page.tenant_id) != key:
                        if key in decisions:
                            _blocked("decision_reopened")
                        decisions[key] = _Decisions(key)
                        latest_decision[page.tenant_id] = key
                    decisions[key].add(record, at)
                    continue
                if type(record) is ReferenceInventoryRecord:
                    if page.tenant_id not in active:
                        _blocked("reference_without_header")
                    active[page.tenant_id].add(record, at)
                    continue
                close(page.tenant_id)
                if type(record) is SourceInventoryRecord:
                    if record.source_key in seen:
                        _blocked("duplicate_source")
                    seen.add(record.source_key)
                    active[page.tenant_id] = _Source(record, at)
                elif type(record) is RootInventoryRecord:
                    if record.root_key in roots:
                        _blocked("duplicate_root")
                    roots[record.root_key] = LocatedRoot(record, at)
                elif type(record) is RetiredInventoryRecord:
                    key, keys = (
                        (record.source_key, retired_sources) if record.source_key else (record.root_key, retired_roots)
                    )
                    if key in keys:
                        _blocked("duplicate_retired")
                    keys.add(key)
                    retired.append(LocatedRetired(record, at))
                else:
                    _blocked("unknown_source_record")
        for tenant in tuple(active):
            close(tenant)
        counts = Counter(_root(key) for key in sources)
        if (
            set(counts) - roots.keys()
            or roots.keys() & retired_roots
            or sources.keys() & retired_sources
            or set(counts) & retired_roots
        ):
            _blocked("root_source_closure")
        if any(row.header.retained_version_count != counts[key] for key, row in roots.items()):
            _blocked("retained_version_count")
        if any(_root(key) not in roots and _root(key) not in retired_roots for key in retired_sources):
            _blocked("retired_parent")
        if set(decisions) != {key for key, entry in sources.items() if entry.header.reference_count}:
            _blocked("decision_sources")
        entries = []
        for key, entry in sources.items():
            actual = decisions.get(key)
            if actual is not None and (
                actual.count != entry.header.reference_count or actual.digest != entry.decision_digest
            ):
                _blocked("decision_mismatch")
            entries.append(replace(entry, decisions=RecordSpan(actual.first, actual.last) if actual else None))
        current()
        return FrozenReferencePlan(
            deepcopy(frozen), tuple(pages), tuple(entries), tuple(roots.values()), tuple(retired)
        )

    @staticmethod
    def _current(current):
        if current is not None and not callable(current):
            _blocked("invalid_guard")
        return current if current is not None else lambda: None

    async def aiter_reference_chunks(self, plan, *, tenant_id, after_source_ordinal=0, current=None):
        current = self._current(current)
        if (
            type(plan) is not FrozenReferencePlan
            or type(tenant_id) is not int
            or tenant_id not in plan.frozen.tenant_ids
            or type(after_source_ordinal) is not int
            or after_source_ordinal < 0
        ):
            _blocked("invalid_replay_scope")
        entries = tuple(entry for entry in plan.sources if entry.header.source_key.tenant_id == tenant_id)
        if after_source_ordinal > len(entries):
            _blocked("invalid_source_cursor")
        catalog = {(page.tenant_id, page.section, page.page_index): page for page in plan.pages}
        cached, rows = None, ()
        for entry in entries[after_source_ordinal:]:
            current()
            span = entry.references
            if span is None:
                yield ReferenceSourceChunk(entry, (), True)
                continue
            for index in range(span.first.page.page_index, span.last.page.page_index + 1):
                page = catalog[(tenant_id, "sources", index)]
                if cached != page:
                    current()
                    content = await self.store.aload_canonical(
                        {"object_key": page.object_key, "sha256": page.sha256},
                        run_id=plan.frozen.run_id,
                        kind="sources",
                    )
                    current()
                    rows = decode_source_page(
                        content, run_id=plan.frozen.run_id, tenant_id=tenant_id, page_index=index
                    ).records
                    if len(rows) != page.record_count:
                        _blocked("replay_page_count")
                    cached = page
                first = span.first.record_index if index == span.first.page.page_index else 0
                last = span.last.record_index + 1 if index == span.last.page.page_index else len(rows)
                selected = rows[first:last]
                if (
                    not selected
                    or len(selected) > 199
                    or any(
                        type(row) is not ReferenceInventoryRecord or row.source_key != entry.header.source_key
                        for row in selected
                    )
                ):
                    _blocked("replay_source_span")
                current()
                yield ReferenceSourceChunk(entry, selected, index == span.last.page.page_index)
