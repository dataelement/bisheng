"""Read original six-source facts; this stream grants no binding authority.

The operational caller owns the native transaction and global orphan probe.
Only closed records escape; configurations live here solely for extraction
and canonical digests. Nothing freezes a run, writes bindings or marks ready.
"""

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import datetime
from typing import Literal
from weakref import WeakSet

from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.app_publish.domain.schemas.app_manifest import CapabilityDeclaration
from bisheng.app_publish.domain.services.reference_extractor import (
    APP_REFERENCE_EXTRACTOR_VERSION,
    extract_app_reference_requests,
    extract_app_references,
)
from bisheng.app_runtime.domain.constants import AppState
from bisheng.assistant.domain.services.reference_extractor import (
    ASSISTANT_REFERENCE_EXTRACTOR_VERSION,
    extract_assistant_references,
)
from bisheng.channel.domain.services.reference_extractor import (
    CHANNEL_SYNC_REFERENCE_EXTRACTOR_VERSION,
    extract_channel_sync_references,
)
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.knowledge.application.unification_names import UnificationNameIndex
from bisheng.knowledge.domain.repositories.unification_inventory_repository import (
    KnowledgeRow,
    UnificationInventoryRepository,
)
from bisheng.knowledge.domain.repositories.unification_resource_repository import ResourceRow
from bisheng.knowledge.domain.repositories.unification_target_repository import (
    KnowledgeMigrationTargetFact,
    KnowledgeMigrationTargetRepository,
)
from bisheng.knowledge.domain.services.model_reference_extractor import (
    KNOWLEDGE_MODEL_REFERENCE_EXTRACTOR_VERSION,
    extract_knowledge_model_references,
)
from bisheng.llm.domain.repositories.migration_target_repository import (
    ModelMigrationTargetFact,
    ModelMigrationTargetRepository,
)
from bisheng.llm.domain.repositories.model_name_resolution_repository import ModelNameResolutionRepository, NameCatalog
from bisheng.llm.domain.services.default_reference_extractor import (
    MODEL_DEFAULT_REFERENCE_EXTRACTOR_VERSION,
    extract_model_default_references,
)
from bisheng.permission.application.migration_read import PinnedMigrationPermissionReader
from bisheng.resource_reference.application.contracts import (
    SourceKey,
    SourceRootKey,
    SourceType,
    TargetKey,
    TargetType,
    TransactionIdentity,
    normalize_references,
    reference_set_digest,
)
from bisheng.workflow.domain.services.reference_extractor import (
    WORKFLOW_REFERENCE_EXTRACTOR_VERSION,
    extract_workflow_version_references,
)

Lifecycle = tuple[str | int | bool | None, ...]
PhysicalFact = KnowledgeMigrationTargetFact | ModelMigrationTargetFact
_KN_NEUTRAL_FIELDS = frozenset(
    {
        "model_transition_json",
        "model_config_revision",
        "index_generation",
        "processing_config_version",
        "metadata_schema_revision",
        "migration_origin",
    }
)


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class PreparedSourceInventoryContext:
    """Instance-issued, nonpersistent facts for one original SQL transaction."""

    tenant_id: int
    run_id: str
    writer_contract_version: str
    transaction: TransactionIdentity = field(repr=False)
    shared_server_ids: frozenset[int]
    catalog: NameCatalog = field(repr=False)
    knowledge_rows: tuple[KnowledgeRow, ...] = field(repr=False)
    name_index: UnificationNameIndex = field(repr=False)


@dataclass(frozen=True, slots=True)
class RootInventoryRecord:
    root_key: SourceRootKey
    creator_id: int | None
    lifecycle: Lifecycle
    configuration_digest: str
    retained_version_count: int
    business_revision_digest: str
    frozen_index: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class SourceInventoryRecord:
    source_key: SourceKey
    extractor_version: str
    configuration_digest: str
    reference_digest: str
    reference_count: int
    lifecycle: Lifecycle
    business_revision_digest: str
    frozen_index: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class ReferenceInventoryRecord:
    source_key: SourceKey
    slot_key: str
    target: TargetKey
    origin: Literal["explicit_id", "resolved_name"]
    physical_fact: PhysicalFact
    frozen_state: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class RetiredInventoryRecord:
    root_key: SourceRootKey
    source_key: SourceKey | None
    lifecycle: Lifecycle
    configuration_digest: str
    business_revision_digest: str
    frozen_index: str | None = field(default=None, repr=False)


def _blocked(reason):
    raise KnowledgeOperationPlanConflictError(reason=f"unification_sources_{reason}")


def _digest(value):
    def timestamp(item):
        if isinstance(item, datetime):
            return item.isoformat()
        raise TypeError("inventory digests require original JSON or closed SQL scalars")

    data = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False, default=timestamp
    )
    return hashlib.sha256(data.encode()).hexdigest()


def knowledge_business_revision_digest(row: KnowledgeRow | ResourceRow) -> str:
    """Original inventory revision, distinct from online SourceOwner payloads."""
    if type(row) not in (KnowledgeRow, ResourceRow):
        _blocked("knowledge_revision_row_required")
    return _digest(
        {item.name: getattr(row, item.name) for item in fields(KnowledgeRow) if item.name not in _KN_NEUTRAL_FIELDS}
    )


def _flag(value, *, nullable=False):
    if value is None and nullable:
        return False
    if type(value) is not int or value not in (0, 1):
        _blocked("invalid_delete_flag")
    return value == 1


class UnificationSourceInventory:
    def __init__(
        self,
        repository=None,
        *,
        sharing_reader,
        model_names_repository=None,
        knowledge_targets=None,
        model_targets=None,
        original_state=None,
    ):
        if not isinstance(sharing_reader, PinnedMigrationPermissionReader):
            _blocked("original_sharing_reader_required")
        self.repository = repository if repository is not None else UnificationInventoryRepository()
        self.sharing_reader = sharing_reader
        self.model_names = (
            model_names_repository if model_names_repository is not None else ModelNameResolutionRepository()
        )
        self.knowledge_targets = (
            knowledge_targets if knowledge_targets is not None else KnowledgeMigrationTargetRepository()
        )
        self.model_targets = model_targets if model_targets is not None else ModelMigrationTargetRepository()
        from bisheng.knowledge.application.unification_reference_state import OriginalReferenceState

        self.original_state = original_state or OriginalReferenceState()
        self._contexts: WeakSet[PreparedSourceInventoryContext] = WeakSet()

    async def _pages(self, session, method, **kwargs):
        after = None
        while True:
            page = await getattr(self.repository, method)(session, after_id=after, limit=200, **kwargs)
            yield page.items
            if page.next_after is None:
                return
            if after is not None and page.next_after <= after:
                _blocked("non_advancing_page")
            after = page.next_after

    async def _sources(self, session, entries, cache):
        if not entries:
            return
        cache, tombstones, *_ = cache
        active = [entry for entry in entries if not isinstance(entry, RetiredInventoryRecord)]
        unseen = tuple(
            dict.fromkeys(ref.target for _, _, _, refs, _, _, _ in active for ref in refs if ref.target not in cache)
        )
        for owner, keys in (
            (self.model_targets, tuple(key for key in unseen if key.target_type == TargetType.MODEL)),
            (self.knowledge_targets, tuple(key for key in unseen if key.target_type != TargetType.MODEL)),
        ):
            for offset in range(0, len(keys), 200):
                batch = keys[offset : offset + 200]
                facts = await owner.ainspect(session, source_key=active[0][0], targets=batch)
                if len(facts) != len(batch) or tuple(fact.key for fact in facts) != batch:
                    _blocked("incomplete_physical_facts")
                cache.update((fact.key, fact) for fact in facts)
        snapshots = {}
        keys = tuple(entry[0] for entry in active)
        for offset in range(0, len(keys), 200):
            snapshots.update(
                await self.original_state.repository.aload_raw_snapshots(
                    session, source_keys=keys[offset : offset + 200]
                )
            )
        for entry in entries:
            if isinstance(entry, RetiredInventoryRecord):
                yield entry
                continue
            key, extractor, configuration, references, lifecycle, origins, revision = entry
            frozen_index, states = await self.original_state.acapture(
                session,
                source_key=key,
                references=references,
                physical=cache,
                tombstone_cache=tombstones,
                snapshot=snapshots[key],
            )
            yield SourceInventoryRecord(
                key,
                extractor,
                _digest(configuration),
                reference_set_digest(references),
                len(references),
                lifecycle,
                revision,
                frozen_index,
            )
            for ref in references:
                yield ReferenceInventoryRecord(
                    key,
                    ref.slot_key,
                    ref.target,
                    origins.get(ref.slot_key, "explicit_id"),
                    cache[ref.target],
                    states[(ref.slot_key, ref.target.target_type.value, ref.target.target_id)],
                )

    async def _versioned(self, session, tenant, kind, index, cache):
        workflow = kind == SourceType.WORKFLOW_VERSION
        prefix = "workflow" if workflow else "app"
        roots, counts = {}, {}
        async for page in self._pages(session, f"alist_{prefix}_roots"):
            for row in page:
                key = SourceRootKey(tenant, kind, row.id)
                if workflow:
                    deleted = _flag(row.is_delete)
                    lifecycle, creator = (row.flow_type, row.status, row.is_delete), row.user_id
                else:
                    if row.state not in {value.value for value in AppState}:
                        _blocked("unknown_app_state")
                    deleted = row.state == AppState.DELETED.value
                    lifecycle, creator = (row.state, row.current_version_id, row.pending_version_id), row.owner_user_id
                # Discard the root's mirror graph after hashing; never treat it
                # as an additional version or retain all root prompts in memory.
                roots[row.id] = (key, creator, lifecycle, _digest(asdict(row)), deleted)
                counts[row.id] = 0
        cache[2].update(row[0] for row in roots.values() if row[4])
        async for page in self._pages(session, f"alist_{prefix}_versions"):
            entries = []
            for row in page:
                parent = row.flow_id if workflow else row.app_id
                if parent not in roots:
                    _blocked("missing_version_parent")
                root, _, _, _, root_deleted = roots[parent]
                revision = _digest({"root": roots[parent][3], "version": asdict(row)})
                key = SourceKey(tenant, kind, parent, str(row.id))
                if workflow:
                    deleted = _flag(row.is_delete, nullable=True)
                    _flag(row.is_current, nullable=True)
                    lifecycle = (row.flow_type, row.is_current, row.is_delete)
                    payload = {"data": json.loads(row.data_json)}
                    extractor = WORKFLOW_REFERENCE_EXTRACTOR_VERSION
                else:
                    if (
                        row.kind not in {"initial", "iteration"}
                        or row.terminal_state not in {None, "online", "rejected", "withdrawn"}
                        or type(row.version_no) is not int
                        or row.version_no <= 0
                    ):
                        _blocked("invalid_app_version")
                    deleted = False
                    lifecycle = (row.version_no, row.kind, row.terminal_state)
                    payload = {"capabilities": json.loads(row.capabilities_json)}
                    extractor = APP_REFERENCE_EXTRACTOR_VERSION
                if root_deleted or deleted:
                    entries.append(RetiredInventoryRecord(root, key, lifecycle, _digest(payload), revision))
                    continue
                origins = {}
                if workflow:
                    references = extract_workflow_version_references(payload["data"])
                else:
                    declaration = CapabilityDeclaration.model_validate(payload["capabilities"])
                    requests = extract_app_reference_requests(declaration)
                    references = extract_app_references(declaration, resolved_targets=index.resolve(requests))
                    origins = {request.slot_key: "resolved_name" for request in requests if request.target_id is None}
                entries.append(
                    (key, extractor, payload, normalize_references(references), lifecycle, origins, revision)
                )
                counts[parent] += 1
            async for record in self._sources(session, entries, cache):
                yield record
        empty = tuple(value[0] for ident, value in roots.items() if not value[4] and counts[ident] == 0)
        for offset in range(0, len(empty), 200):
            cache[3].update(
                await self.original_state.repository.aload_root_guards(session, root_keys=empty[offset : offset + 200])
            )
        for ident, (root, creator, lifecycle, digest, deleted) in roots.items():
            if deleted:
                yield RetiredInventoryRecord(root, None, lifecycle, digest, digest)
            else:
                yield RootInventoryRecord(root, creator, lifecycle, digest, counts[ident], digest)

    async def _linked(self, session, tenant, kind, cache):
        assistant = kind == SourceType.ASSISTANT
        root_method, child_method, parameter = (
            ("alist_assistants", "alist_assistant_links", "assistant_ids")
            if assistant
            else ("alist_channels", "alist_channel_syncs", "channel_ids")
        )
        async for roots in self._pages(session, root_method):
            children = {row.id: [] for row in roots}
            if not roots:
                continue
            async for page in self._pages(session, child_method, **{parameter: tuple(children)}):
                for child in page:
                    parent = child.assistant_id if assistant else child.channel_id
                    if parent not in children:
                        _blocked("unexpected_link_parent")
                    children[parent].append(child)
            entries, root_records = [], []
            for row in roots:
                root, key = SourceRootKey(tenant, kind, row.id), SourceKey(tenant, kind, row.id, "current")
                links = tuple(asdict(child) for child in children[row.id])
                if assistant:
                    deleted = _flag(row.is_delete)
                    lifecycle = (row.status, row.is_delete)
                    configuration = {"model_name": row.model_name, "links": links}
                    extractor = ASSISTANT_REFERENCE_EXTRACTOR_VERSION
                    references = (
                        ()
                        if deleted
                        else extract_assistant_references(
                            model_name=row.model_name,
                            knowledge_ids=tuple(
                                child.knowledge_id for child in children[row.id] if child.knowledge_id is not None
                            ),
                        )
                    )
                else:
                    deleted = False
                    lifecycle = (row.is_released,)
                    configuration = {"syncs": links}
                    extractor = CHANNEL_SYNC_REFERENCE_EXTRACTOR_VERSION
                    references = extract_channel_sync_references(links)
                digest = _digest(configuration)
                revision = _digest({"root": asdict(row), "links": links})
                if deleted:
                    root_records.append(RetiredInventoryRecord(root, None, lifecycle, digest, revision))
                else:
                    root_records.append(RootInventoryRecord(root, row.user_id, lifecycle, digest, 1, revision))
                    entries.append(
                        (key, extractor, configuration, normalize_references(references), lifecycle, {}, revision)
                    )
            for record in root_records:
                yield record
            async for record in self._sources(session, entries, cache):
                yield record

    async def _configured(self, session, tenant, knowledge, cache):
        entries = []
        for row in knowledge:
            if type(row.type) is not int or row.type not in {0, 1, 2, 3}:
                _blocked("unknown_knowledge_type")
            root = SourceRootKey(tenant, SourceType.KNOWLEDGE, str(row.id))
            configuration = {
                "model": row.model,
                "model_transition": json.loads(row.model_transition_json)
                if row.model_transition_json is not None
                else None,
            }
            lifecycle = (row.type, row.state, row.is_released)
            digest = _digest(configuration)
            revision = knowledge_business_revision_digest(row)
            if row.type == 2:
                yield RetiredInventoryRecord(root, None, lifecycle, digest, revision)
                continue
            key = SourceKey(tenant, SourceType.KNOWLEDGE, str(row.id), "current")
            refs = extract_knowledge_model_references(**configuration)
            yield RootInventoryRecord(root, row.user_id, lifecycle, digest, 1, revision)
            entries.append(
                (
                    key,
                    KNOWLEDGE_MODEL_REFERENCE_EXTRACTOR_VERSION,
                    configuration,
                    normalize_references(refs),
                    lifecycle,
                    {},
                    revision,
                )
            )
        async for record in self._sources(session, entries, cache):
            yield record
        async for page in self._pages(session, "alist_model_defaults"):
            entries = []
            for row in page:
                empty = row.value is None or row.value == ""
                value = row.value if empty else json.loads(row.value)
                configuration, lifecycle = {"key": row.key, "value": value}, (row.key,)
                refs = () if empty else extract_model_default_references(row.key, value)
                root = SourceRootKey(tenant, SourceType.MODEL_DEFAULT, row.key)
                key = SourceKey(tenant, SourceType.MODEL_DEFAULT, row.key, "current")
                revision = _digest(asdict(row))
                yield RootInventoryRecord(root, None, lifecycle, _digest(configuration), 1, revision)
                entries.append(
                    (
                        key,
                        MODEL_DEFAULT_REFERENCE_EXTRACTOR_VERSION,
                        configuration,
                        normalize_references(refs),
                        lifecycle,
                        {},
                        revision,
                    )
                )
            async for record in self._sources(session, entries, cache):
                yield record

    @staticmethod
    def _identity(session, run_id, writer_contract_version):
        tenant = get_current_tenant_id()
        if (
            not isinstance(session, AsyncSession)
            or not session.in_transaction()
            or type(tenant) is not int
            or tenant <= 0
            or is_tenant_filter_bypassed()
        ):
            _blocked("native_tenant_transaction_required")
        for value, maximum in ((run_id, 64), (writer_contract_version, 32)):
            if (
                not isinstance(value, str)
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", value) is None
                or len(value) > maximum
            ):
                _blocked("invalid_run_identity")
        try:
            transaction = TransactionIdentity.capture(session)
        except (TypeError, ValueError):
            _blocked("native_tenant_transaction_required")
        return tenant, transaction

    @staticmethod
    def _current(session, tenant, transaction):
        actual_tenant = get_current_tenant_id()
        if (
            not session.in_transaction()
            or type(actual_tenant) is not int
            or actual_tenant != tenant
            or is_tenant_filter_bypassed()
        ):
            _blocked("iterator_scope_changed")
        try:
            transaction.assert_current(session)
        except (TypeError, ValueError):
            _blocked("iterator_transaction_changed")

    def _context(self, session, context, run_id, writer_contract_version):
        tenant, _ = self._identity(session, run_id, writer_contract_version)
        if (
            not isinstance(context, PreparedSourceInventoryContext)
            or context not in self._contexts
            or (context.tenant_id, context.run_id, context.writer_contract_version)
            != (tenant, run_id, writer_contract_version)
        ):
            _blocked("prepared_context_mismatch")
        self._current(session, tenant, context.transaction)
        return context

    async def aprepare_tenant_context(
        self, session: AsyncSession, *, run_id: str, writer_contract_version: str
    ) -> PreparedSourceInventoryContext:
        tenant, transaction = self._identity(session, run_id, writer_contract_version)

        try:
            await self.repository.avalidate_tenant_orphans(session)
            self._current(session, tenant, transaction)
            shared = await self.sharing_reader.aget_shared_server_ids(session, tenant)
            self._current(session, tenant, transaction)
            catalog = await self.model_names.ainspect_catalog(session, tenant, shared)
            self._current(session, tenant, transaction)
            knowledge = []
            async for page in self._pages(session, "alist_knowledge"):
                self._current(session, tenant, transaction)
                knowledge.extend(page)
            rows = tuple(knowledge)
            context = PreparedSourceInventoryContext(
                tenant,
                run_id,
                writer_contract_version,
                transaction,
                shared,
                catalog,
                rows,
                UnificationNameIndex(catalog, rows),
            )
            self._contexts.add(context)
            return context
        except (TypeError, ValueError, KeyError) as error:
            raise KnowledgeOperationPlanConflictError(reason="unification_sources_malformed_configuration") from error

    async def aiter_tenant_source_records(
        self,
        session: AsyncSession,
        *,
        run_id: str,
        writer_contract_version: str,
        context: PreparedSourceInventoryContext | None = None,
    ):
        if context is None:
            context = await self.aprepare_tenant_context(
                session, run_id=run_id, writer_contract_version=writer_contract_version
            )

        def current():
            self._context(session, context, run_id, writer_contract_version)

        current()
        tenant, index, knowledge = context.tenant_id, context.name_index, context.knowledge_rows
        cache = ({}, {}, set(), {})

        async def prepared(record):
            if isinstance(record, RootInventoryRecord) and record.retained_version_count == 0:
                from bisheng.knowledge.application.unification_reference_state import parse_root_index, sql_value

                state = sql_value({"root_guard": cache[3][record.root_key]})
                parse_root_index(state)
                return replace(
                    record, frozen_index=json.dumps(state, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                )
            if isinstance(record, RetiredInventoryRecord) and (
                record.source_key is None or record.root_key not in cache[2]
            ):
                from bisheng.knowledge.application.unification_reference_state import retired_index

                state = await retired_index(
                    session,
                    repository=self.original_state.repository,
                    legacy=self.original_state.legacy,
                    root_key=record.root_key,
                    source_key=record.source_key,
                )
                current()
                return replace(record, frozen_index=state)
            return record

        try:
            for kind in (SourceType.WORKFLOW_VERSION, SourceType.HOSTED_APP_VERSION):
                async for record in self._versioned(session, tenant, kind, index, cache):
                    current()
                    yield await prepared(record)
            for kind in (SourceType.ASSISTANT, SourceType.CHANNEL_SYNC):
                async for record in self._linked(session, tenant, kind, cache):
                    current()
                    yield await prepared(record)
            async for record in self._configured(session, tenant, knowledge, cache):
                current()
                yield await prepared(record)
            current()
        except (TypeError, ValueError, KeyError) as error:
            raise KnowledgeOperationPlanConflictError(reason="unification_sources_malformed_configuration") from error
