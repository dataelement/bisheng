"""Internal model-removal impact and bounded source disclosure, without execution.

Real model ownership authorizes the exact targets. Saved reverse hints are
optional review data and have no role in authorizing or freezing deletion.
"""

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from types import SimpleNamespace

from loguru import logger
from sqlalchemy import inspect as inspect_orm
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.common.errcode.llm_tenant import LLMModelSharedReadonlyError
from bisheng.core.context.tenant import (
    get_admin_scope_tenant_id,
    get_is_management_api,
    get_visible_tenant_ids,
    is_management_all_tenants,
)
from bisheng.database.models.tenant import ROOT_TENANT_ID
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.llm.domain.repositories.model_deletion_repository import ModelDeletionRepository
from bisheng.llm.domain.repositories.model_provider_operation_repository import ModelProviderOperationRepository
from bisheng.llm.domain.services.model_reference_cursor import (
    ModelReferenceSourceEntry,
    ModelReferenceSourcePage,
    decode_source_cursor,
    encode_source_cursor,
    source_context,
    validate_page_size,
)
from bisheng.open_api.application.access_context import get_current_open_api_principal
from bisheng.permission.application.identity import resolve_permission_actor
from bisheng.public_endpoints.application.access_context import get_current_public_api_principal
from bisheng.resource_reference.application.contracts import (
    SourceKey,
    SourceType,
    TargetKey,
    TransactionIdentity,
)
from bisheng.resource_reference.application.read_identity import AuthenticatedSourceReadIdentity
from bisheng.resource_reference.application.source_disclosure import SourceDisclosureRuntime
from bisheng.resource_reference.application.write_runtime import ReferenceBindingRuntime
from bisheng.resource_reference.domain.repositories.reference_hint_repository import ReferenceHintRepository
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository


@dataclass(frozen=True, slots=True)
class ModelReferenceInspection:
    server_id: int
    targets: tuple[TargetKey, ...]
    target_revisions: tuple[tuple[TargetKey, str], ...]
    server_revision: str
    inbound_digest: str
    source_counts: tuple[tuple[str, int], ...]
    slot_counts: tuple[tuple[str, int], ...]
    restricted_counts: tuple[tuple[str, int], ...]
    qualified_counts: tuple[tuple[str, int], ...]
    source_page: ModelReferenceSourcePage
    coverage_epoch: int
    inventory_hash: str
    blocked: bool
    check_complete: bool = True


@dataclass(frozen=True, slots=True)
class PreparedModelRemoval:
    inspection: ModelReferenceInspection


def _binding_digest(row) -> bytes:
    value = tuple(
        getattr(row, field)
        for field in (
            "tenant_id",
            "source_type",
            "source_id",
            "source_version",
            "slot_key",
            "target_type",
            "target_id",
            "target_tenant_id",
            "target_space_id",
            "source_revision",
            "legacy_invalid_reason",
            "legacy_run_id",
            "legacy_evidence_key",
        )
    )
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()).digest()


class _InspectionScope:
    """One inspection's original lock transaction, never a cross-page grant."""

    def __init__(self, session):
        if not isinstance(session, AsyncSession):
            raise ReferenceCoverageNotReadyError(reason="model_reference_native_session_required")
        self.session = session
        self.tenant_id = ReferenceRepository.current_tenant_id()
        self.transaction = TransactionIdentity.capture(session) if session.in_transaction() else None

    def check(self):
        if ReferenceRepository.current_tenant_id() != self.tenant_id:
            raise ReferenceCoverageNotReadyError(reason="model_reference_tenant_changed")
        if self.transaction is not None:
            self.transaction.assert_current(self.session)

    def pin(self):
        # Pin the original native transaction before any target lock. A fresh
        # Session checks out its own connection without issuing an extra SQL.
        self.check()
        if self.transaction is None:
            self.transaction = TransactionIdentity.capture(self.session)

    async def call(self, method, *args, **kwargs):
        self.check()
        result = await method(*args, **kwargs)
        self.check()
        return result


class ModelReferenceService:
    def __init__(
        self,
        *,
        coverage_factory=None,
        runtime: ReferenceBindingRuntime | None = None,
        disclosure_runtime: SourceDisclosureRuntime | None = None,
        session_factory=None,
    ):
        self.repository = ModelDeletionRepository()
        self.runtime = runtime
        self.coverage_factory = coverage_factory
        self.identity = AuthenticatedSourceReadIdentity()
        self.disclosure_runtime = disclosure_runtime
        self.sessions = session_factory

    async def _authorize(self, identity):
        tenant = ReferenceRepository.current_tenant_id()
        if not isinstance(identity, UserPayload):
            raise LLMModelSharedReadonlyError()
        actor = await resolve_permission_actor(identity)
        if (
            (actor.subject_type, actor.subject_id, actor.tenant_id) != ("user", identity.user_id, identity.tenant_id)
            or (not actor.super_admin and (tenant != actor.tenant_id or tenant not in actor.tenant_admin_tenant_ids))
            or (tenant == ROOT_TENANT_ID and not actor.super_admin)
        ):
            raise LLMModelSharedReadonlyError()
        return await self.identity.acapture(identity)

    async def _stable_identity(self, identity):
        """Hash original runtime facts, excluding only the per-request trace.

        This does not narrow the Core to the web-only delete-plan credential
        shape. No raw credential or principal is persisted or placed in a URL.
        """
        actor = await resolve_permission_actor(identity)
        visible = get_visible_tenant_ids()
        principal, public = get_current_open_api_principal(), get_current_public_api_principal()
        principal_value = principal.model_dump(mode="json") if principal is not None else None
        if principal_value is not None:
            # A frozenset's iteration order is not stable across processes.
            principal_value["scopes"] = sorted(principal.scopes)
        return source_context(
            {
                "user": [
                    identity.user_id,
                    identity.tenant_id,
                    identity.is_global_super,
                    sorted(identity.user_role),
                    identity.token_version,
                    identity._runtime_credential_reference,
                ],
                "actor": [
                    actor.subject_type,
                    actor.subject_id,
                    actor.tenant_id,
                    actor.super_admin,
                    sorted(actor.tenant_admin_tenant_ids),
                    actor.data_scope,
                ],
                "scope": [
                    ReferenceRepository.current_tenant_id(),
                    sorted(visible) if visible is not None else None,
                    get_is_management_api(),
                    get_admin_scope_tenant_id(),
                    is_management_all_tenants(),
                ],
                "open": principal_value,
                "public": public.model_dump(mode="json") if public is not None else None,
            }
        )

    @staticmethod
    def _execution_pin(session, execution, identity, removal):
        if execution is None:
            return None
        if (
            type(execution) is not KnowledgeOperationPlan
            or inspect_orm(execution).session is not session.sync_session
            or not inspect_orm(execution).persistent
            or execution.operation not in {"model_update_server", "model_delete_server"}
            or execution.model_execution_state not in {"RESERVED", "SHARING_COMPLETE"}
            or execution.model_server_id != removal.server_id
            or execution.tenant_id != removal.owner_tenant_id
            or execution.actor_user_id != identity.user_id
            or execution.actor_reference.get("management_tenant_id")
            != (get_admin_scope_tenant_id() if get_is_management_api() else None)
        ):
            raise ResourceReferenceInvalidError(reason="model_deletion_execution_untrusted")
        ModelProviderOperationRepository().validate(execution)
        if execution.target_manifest != [
            {"target_type": "model", "target_id": target.target_id} for target in removal.targets
        ]:
            raise ResourceReferenceInvalidError(reason="model_deletion_execution_targets_changed")
        return (
            execution.id,
            execution.operation_id,
            execution.request_hash,
            execution.plan_digest,
            execution.model_execution_state,
            deepcopy(execution.model_execution_metadata),
        )

    async def _dataset(self, session, *, identity, server_id, retained_model_ids, delete_server, execution=None):
        guard = _InspectionScope(session)
        original = await guard.call(self._authorize, identity)
        stable = await guard.call(self._stable_identity, identity)
        if guard.transaction is None:
            if not session.in_transaction():
                await guard.call(session.connection)
            guard.pin()
        removal = await guard.call(
            self.repository.alock_removal_targets,
            session,
            server_id=server_id,
            retained_model_ids=retained_model_ids,
            delete_server=delete_server,
            legacy_operation_id=execution.operation_id if execution is not None and execution.impact else None,
        )
        execution_pin = self._execution_pin(session, execution, identity, removal)
        before = SimpleNamespace(coverage_epoch=0, tenant_inventory_hash="")
        return {
            "guard": guard,
            "original": original,
            "stable": stable,
            "removal": removal,
            "execution": execution,
            "execution_pin": execution_pin,
            "receipts": (),
            "runtime": None,
            "before": before,
            "sources": {},
            "slots": dict.fromkeys(SourceType, 0),
            "tenants": set(),
            "digest": "",
            "blocked": False,
            "complete": True,
        }

    @asynccontextmanager
    async def _hint_session(self, business_session):
        factory = self.sessions
        if factory is None:
            from sqlmodel.ext.asyncio.session import AsyncSession as HintSession

            def factory():
                return HintSession(business_session.bind, expire_on_commit=False)

        async with factory() as session, session.begin():
            yield session

    async def _hints(self, session, identity, facts):
        try:
            async with asyncio.timeout(2), self._hint_session(session) as hint_session:
                rows = await ReferenceHintRepository().aread(hint_session, facts["removal"].targets)
                digest = hashlib.sha256()
                for row in rows:
                    try:
                        key = SourceKey(row.tenant_id, row.source_type, row.source_id, row.source_version)
                    except (TypeError, ValueError) as error:
                        raise ReferenceCoverageNotReadyError(reason="malformed_reference_hint") from error
                    facts["sources"][key] = facts["sources"].get(key, 0) + 1
                    facts["slots"][key.source_type] += 1
                    digest.update(_binding_digest(row))
                facts["digest"] = digest.hexdigest()
                facts["blocked"] = bool(rows)
                candidates = self._candidates(facts)
                disclosed = []
                for offset in range(0, len(candidates), 200):
                    disclosed.extend(await self._disclose(hint_session, identity, candidates[offset : offset + 200]))
                return tuple(disclosed)
        except (TimeoutError, SQLAlchemyError, ReferenceCoverageNotReadyError) as error:
            logger.warning(
                "Model reference hints unavailable server={} error={}", facts["removal"].server_id, type(error).__name__
            )
            facts.update(sources={}, slots=dict.fromkeys(SourceType, 0), complete=False, blocked=False)
            return ()

    async def _finish(self, identity, facts):
        guard = facts["guard"]
        if (
            await self.identity.acapture(identity) != facts["original"]
            or await self._stable_identity(identity) != facts["stable"]
        ):
            raise ResourceReferenceInvalidError(reason="model_reference_identity_changed")
        if self._execution_pin(guard.session, facts["execution"], identity, facts["removal"]) != facts["execution_pin"]:
            raise ResourceReferenceInvalidError(reason="model_deletion_execution_changed")
        guard.check()

    @staticmethod
    def _candidates(facts):
        tenant = ReferenceRepository.current_tenant_id()
        return sorted(
            (key for key in facts["sources"] if key.tenant_id == tenant),
            key=lambda key: (key.source_type.value, key.source_id, key.source_version),
        )

    @staticmethod
    def _context(facts, size, delete_server):
        removal = facts["removal"]
        return source_context(
            {
                "command": [removal.server_id, removal.retained_model_ids, delete_server],
                "revisions": [removal.server_revision, removal.model_revisions],
                "inbound": facts["digest"],
                "identity": facts["stable"],
                "page_size": size,
            }
        )

    async def _disclose(self, session, identity, keys):
        if not keys:
            return ()
        runtime = self.disclosure_runtime
        if runtime is None:
            from bisheng.resource_reference.disclosure_composition import get_runtime

            runtime = get_runtime()
        if not isinstance(runtime, SourceDisclosureRuntime):
            raise ReferenceCoverageNotReadyError(reason="source_disclosure_runtime_unconfigured")
        return await runtime.adisclose_sources(session, identity=identity, source_keys=tuple(keys))

    @staticmethod
    def _source_page(data, candidates, start, size, context):
        end = min(start + size, len(candidates))
        more = end < len(candidates)
        return ModelReferenceSourcePage(
            tuple(data), size, more, encode_source_cursor(end, context=context) if more else None
        )

    async def ainspect_removed_models(
        self,
        session,
        *,
        identity,
        server_id: int,
        retained_model_ids,
        delete_server: bool = False,
        source_page_size: int = 50,
    ) -> ModelReferenceInspection:
        return (
            await self._aprepare_removed_models(
                session,
                identity=identity,
                server_id=server_id,
                retained_model_ids=retained_model_ids,
                delete_server=delete_server,
                source_page_size=source_page_size,
            )
        ).inspection

    async def _aprepare_removed_models(
        self,
        session,
        *,
        identity,
        server_id: int,
        retained_model_ids,
        delete_server: bool = False,
        source_page_size: int = 50,
        execution=None,
        include_hints=True,
    ) -> PreparedModelRemoval:
        try:
            size = validate_page_size(source_page_size)
            facts = await self._dataset(
                session,
                identity=identity,
                server_id=server_id,
                retained_model_ids=retained_model_ids,
                delete_server=delete_server,
                execution=execution,
            )
            guard = facts["guard"]
            guard.check()
            candidates = self._candidates(facts)
            counts, qualified, first = dict.fromkeys(SourceType, 0), dict.fromkeys(SourceType, 0), []
            for key in facts["sources"]:
                counts[key.source_type] += 1
            disclosed = await self._hints(session, identity, facts) if include_hints else ()
            candidates = self._candidates(facts)
            for key in facts["sources"]:
                counts[key.source_type] += 1
            for offset, item in enumerate(disclosed):
                if item is not None:
                    qualified[item.source.source_type] += 1
                    if offset < size:
                        first.append(ModelReferenceSourceEntry(item, facts["sources"][item.source]))
            await self._finish(identity, facts)
            removal, before = facts["removal"], facts["before"]
            inspection = ModelReferenceInspection(
                server_id=removal.server_id,
                targets=removal.targets,
                target_revisions=tuple((key, dict(removal.target_revisions)[key.target_id]) for key in removal.targets),
                server_revision=removal.server_revision,
                inbound_digest=facts["digest"],
                source_counts=tuple((kind.value, counts[kind]) for kind in SourceType) if facts["complete"] else (),
                slot_counts=tuple((kind.value, facts["slots"][kind]) for kind in SourceType)
                if facts["complete"]
                else (),
                restricted_counts=tuple((kind.value, counts[kind] - qualified[kind]) for kind in SourceType)
                if facts["complete"]
                else (),
                qualified_counts=tuple((kind.value, qualified[kind]) for kind in SourceType)
                if facts["complete"]
                else (),
                source_page=self._source_page(first, candidates, 0, size, self._context(facts, size, delete_server)),
                coverage_epoch=before.coverage_epoch,
                inventory_hash=before.tenant_inventory_hash,
                blocked=facts["blocked"],
                check_complete=facts["complete"],
            )
            return PreparedModelRemoval(inspection)
        except BaseErrorCode:
            raise
        except Exception as error:
            raise ReferenceCoverageNotReadyError(reason="reference_check_failed") from error

    async def alist_removed_model_sources(
        self,
        session,
        *,
        identity,
        server_id: int,
        retained_model_ids,
        cursor: str,
        delete_server: bool = False,
        page_size: int = 50,
    ) -> ModelReferenceSourcePage:
        try:
            size = validate_page_size(page_size)
            facts = await self._dataset(
                session,
                identity=identity,
                server_id=server_id,
                retained_model_ids=retained_model_ids,
                delete_server=delete_server,
            )
            guard = facts["guard"]
            guard.check()
            disclosed = await self._hints(session, identity, facts)
            if not facts["complete"]:
                raise ReferenceCoverageNotReadyError(reason="reference_hints_unavailable")
            candidates = self._candidates(facts)
            context = self._context(facts, size, delete_server)
            start = decode_source_cursor(cursor, context=context, candidate_count=len(candidates))
            data = tuple(
                ModelReferenceSourceEntry(item, facts["sources"][item.source])
                for item in disclosed[start : start + size]
                if item is not None
            )
            await self._finish(identity, facts)
            return self._source_page(data, candidates, start, size, context)
        except BaseErrorCode:
            raise
        except Exception as error:
            raise ReferenceCoverageNotReadyError(reason="reference_check_failed") from error
