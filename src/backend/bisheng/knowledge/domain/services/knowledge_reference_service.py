"""Knowledge deletion impact and bounded disclosure of actual saved sources.

The public inspection owns short target transactions. Its detached result is
review data, not a target receipt or permission to execute a deletion.
"""

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from hashlib import sha256

from fastapi.encoders import jsonable_encoder
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.cursor import CursorDecodeError, decode_cursor, encode_cursor
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.application.direct_delete_reference_query import DirectDeleteReferenceQuery
from bisheng.knowledge.application.space_delete_reference_query import SpaceDeleteReferenceQuery
from bisheng.knowledge.domain.schemas.direct_delete_scope import DeleteSelection
from bisheng.permission.application.business_authorization import batch_check_business_actions, require_business_action
from bisheng.resource_reference.application.access import get_reference_binding_runtime
from bisheng.resource_reference.application.contracts import SourceType
from bisheng.resource_reference.application.read_identity import AuthenticatedSourceReadIdentity
from bisheng.resource_reference.application.source_disclosure import SourceDisclosure, SourceDisclosureRuntime


def impact_digest(value):
    raw = json.dumps(
        jsonable_encoder(value), sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    return sha256(raw.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class KnowledgeReferenceSourceEntry:
    disclosure: SourceDisclosure
    matched_slot_count: int


@dataclass(frozen=True, slots=True)
class KnowledgeReferenceSourcePage:
    data: tuple[KnowledgeReferenceSourceEntry, ...]
    page_size: int
    has_more: bool
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class KnowledgeReferenceInspection:
    space_id: int
    whole_space: bool
    inbound_digest: str
    scope_digest: str
    source_counts: tuple[tuple[str, int], ...]
    slot_counts: tuple[tuple[str, int], ...]
    restricted_counts: tuple[tuple[str, int], ...]
    source_page: KnowledgeReferenceSourcePage
    coverage_epoch: int
    inventory_hash: str
    blocked: bool
    check_complete: bool = True
    facts: object = field(default=None, repr=False)


class KnowledgeReferenceService:
    def __init__(
        self, *, coverage_factory=None, runtime=None, disclosure_runtime=None, session_factory=get_async_db_session
    ):
        self.coverage_factory, self.runtime = coverage_factory, runtime
        self.disclosure_runtime, self.sessions = disclosure_runtime, session_factory
        self.identity = AuthenticatedSourceReadIdentity()

    @staticmethod
    def _size(value):
        if type(value) is not int or not 1 <= value <= 200:
            raise ResourceReferenceInvalidError(reason="knowledge_reference_page_size_invalid")
        return value

    async def _authorize(self, identity, space_id, selections, whole_space):
        if (
            type(space_id) is not int
            or space_id <= 0
            or type(whole_space) is not bool
            or type(selections) is not tuple
            or any(type(row) is not DeleteSelection for row in selections)
            or (whole_space and selections)
        ):
            raise ResourceReferenceInvalidError(reason="knowledge_reference_selection_invalid")
        original = await self.identity.acapture(identity)
        stable = await self.identity.astable_capture(identity)
        if whole_space:
            await require_business_action(
                identity, resource_type="knowledge_space", resource_id=space_id, action="delete"
            )
        else:
            for kind in ("folder", "knowledge_file"):
                ids = sorted({row.resource_id for row in selections if row.resource_type == kind})
                for offset in range(0, len(ids), 200):
                    page = tuple(ids[offset : offset + 200])
                    actual = await batch_check_business_actions(
                        identity, resource_type=kind, resource_ids=page, actions=("delete",)
                    )
                    if any("delete" not in actual.get(str(ident), ()) for ident in page):
                        raise PermissionDeniedError(reason="knowledge_reference_delete_action_required")
        await self._current(identity, original, stable)
        return original, stable

    async def _current(self, identity, original, stable):
        if (
            await self.identity.acapture(identity) != original
            or await self.identity.astable_capture(identity) != stable
            or get_current_tenant_id() != original.request_tenant_id
            or is_tenant_filter_bypassed()
        ):
            raise ResourceReferenceInvalidError(reason="knowledge_reference_identity_changed")

    async def _load(self, *, identity, space_id, selections, whole_space):
        original, stable = await self._authorize(identity, space_id, selections, whole_space)
        if not callable(self.coverage_factory):
            raise ReferenceCoverageNotReadyError(reason="knowledge_reference_coverage_unconfigured")
        runtime = self.runtime or await get_reference_binding_runtime()
        query_type = SpaceDeleteReferenceQuery if whole_space else DirectDeleteReferenceQuery
        query = query_type(runtime=runtime, coverage_factory=self.coverage_factory)
        async with self.sessions() as session:
            if not isinstance(session, AsyncSession) or session.in_transaction():
                raise ReferenceCoverageNotReadyError(reason="knowledge_reference_owned_session_required")
            async with session.begin():
                if whole_space:
                    facts = await query.acollect_space(session, space_id=space_id)
                else:
                    facts = await query.acollect(session, space_id=space_id, selections=selections)
        await self._current(identity, original, stable)
        return facts, original, stable

    async def _disclose(self, identity, keys):
        if not keys:
            return ()
        runtime = self.disclosure_runtime
        if runtime is None:
            from bisheng.resource_reference.disclosure_composition import get_runtime

            runtime = get_runtime()
        if not isinstance(runtime, SourceDisclosureRuntime):
            raise ReferenceCoverageNotReadyError(reason="knowledge_source_disclosure_unconfigured")
        async with self.sessions() as session, session.begin():
            return await runtime.adisclose_sources(session, identity=identity, source_keys=tuple(keys))

    @staticmethod
    def _dataset(facts, stable, size, whole_space):
        slots = Counter(row.source for row in facts.references)
        candidates = tuple(key for key in facts.sources if key.tenant_id == stable.request_tenant_id)
        inbound = impact_digest([asdict(row) for row in facts.references])
        scope = impact_digest(asdict(facts.scope))
        context = impact_digest(
            (scope, inbound, whole_space, facts.coverage_epoch, facts.inventory_hash, stable.fingerprint, size)
        )
        return slots, candidates, inbound, scope, context

    @staticmethod
    def _page(data, candidates, start, size, context):
        end = min(start + size, len(candidates))
        more = end < len(candidates)
        return KnowledgeReferenceSourcePage(
            tuple(data), size, more, encode_cursor([end], context=context) if more else None
        )

    async def ainspect(self, *, identity, space_id, selections=(), whole_space=False, source_page_size=50):
        try:
            size = self._size(source_page_size)
            facts, original, stable = await self._load(
                identity=identity, space_id=space_id, selections=selections, whole_space=whole_space
            )
            slots, candidates, inbound, scope, context = self._dataset(facts, stable, size, whole_space)
            qualified, first = Counter(), []
            for start in range(0, len(candidates), 200):
                page = await self._disclose(identity, candidates[start : start + 200])
                await self._current(identity, original, stable)
                for offset, item in enumerate(page):
                    if item is not None:
                        qualified[item.source.source_type.value] += 1
                        if start + offset < size:
                            first.append(KnowledgeReferenceSourceEntry(item, slots[item.source]))
            await self._current(identity, original, stable)
            return KnowledgeReferenceInspection(
                space_id,
                whole_space,
                inbound,
                scope,
                facts.source_counts,
                facts.slot_counts,
                tuple(
                    (kind.value, dict(facts.source_counts)[kind.value] - qualified[kind.value]) for kind in SourceType
                ),
                self._page(first, candidates, 0, size, context),
                facts.coverage_epoch,
                facts.inventory_hash,
                bool(facts.references),
                facts=facts,
            )
        except BaseErrorCode:
            raise
        except Exception as error:
            raise ReferenceCoverageNotReadyError(reason="knowledge_reference_check_failed") from error

    async def alist_sources(self, *, identity, space_id, cursor, selections=(), whole_space=False, page_size=50):
        try:
            size = self._size(page_size)
            facts, original, stable = await self._load(
                identity=identity, space_id=space_id, selections=selections, whole_space=whole_space
            )
            slots, candidates, _, _, context = self._dataset(facts, stable, size, whole_space)
            try:
                if type(cursor) is not str or not 1 <= len(cursor) <= 2048:
                    raise ValueError("bounded knowledge source cursor required")
                (start,) = decode_cursor(cursor, expected_key_len=1, expected_context=context)
                if (
                    type(start) is not int
                    or not 0 <= start < len(candidates)
                    or encode_cursor([start], context=context) != cursor
                ):
                    raise ValueError("invalid knowledge source ordinal")
            except (CursorDecodeError, ValueError, TypeError, AttributeError, IndexError) as error:
                raise ResourceReferenceInvalidError(reason="knowledge_reference_cursor_invalid") from error
            result = await self._disclose(identity, candidates[start : start + size])
            await self._current(identity, original, stable)
            data = [KnowledgeReferenceSourceEntry(item, slots[item.source]) for item in result if item is not None]
            return self._page(data, candidates, start, size, context)
        except BaseErrorCode:
            raise
        except Exception as error:
            raise ReferenceCoverageNotReadyError(reason="knowledge_reference_check_failed") from error
