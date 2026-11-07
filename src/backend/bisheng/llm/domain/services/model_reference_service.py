"""Internal model-removal impact and bounded source disclosure, without execution.

The current request and real model Owner authorize the exact targets. Coverage
must be supplied by a same-session MIG adapter; absence is never readiness.
"""

import hashlib
import json
from dataclasses import dataclass

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
from bisheng.llm.domain.repositories.model_deletion_repository import ModelDeletionRepository
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
from bisheng.resource_reference.application.access import get_reference_binding_runtime
from bisheng.resource_reference.application.contracts import ReferenceState, SourceKey, SourceType, TargetKey
from bisheng.resource_reference.application.read_identity import AuthenticatedSourceReadIdentity
from bisheng.resource_reference.application.source_disclosure import SourceDisclosureRuntime
from bisheng.resource_reference.application.write_runtime import ReferenceBindingRuntime
from bisheng.resource_reference.domain.repositories.coverage_repository import CoverageRepository
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


class ModelReferenceService:
    def __init__(
        self,
        *,
        coverage_factory=None,
        runtime: ReferenceBindingRuntime | None = None,
        disclosure_runtime: SourceDisclosureRuntime | None = None,
    ):
        self.repository = ModelDeletionRepository()
        self.runtime = runtime
        self.coverage_factory = coverage_factory
        self.identity = AuthenticatedSourceReadIdentity()
        self.disclosure_runtime = disclosure_runtime

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

    async def _dataset(self, session, *, identity, server_id, retained_model_ids, delete_server):
        original = await self._authorize(identity)
        stable = await self._stable_identity(identity)
        removal = await self.repository.alock_removal_targets(
            session, server_id=server_id, retained_model_ids=retained_model_ids, delete_server=delete_server
        )
        receipts, scope = (), None
        runtime = self.runtime or await get_reference_binding_runtime()
        if not isinstance(runtime, ReferenceBindingRuntime):
            raise ReferenceCoverageNotReadyError(reason="reference_runtime_unconfigured")
        if removal.targets:
            receipts = await runtime.verifier.averify_owner_targets(session, removal.targets)
            if any(receipt.target.state != ReferenceState.VALID for receipt in receipts):
                raise ResourceReferenceInvalidError(reason="model_removal_target_unavailable")
            scope = runtime.repository.target_owner_scope(session, receipts)
        if self.coverage_factory is None:
            raise ReferenceCoverageNotReadyError(reason="model_reference_coverage_unconfigured")
        coverage = self.coverage_factory(session)
        if not isinstance(coverage, CoverageRepository):
            raise ReferenceCoverageNotReadyError(reason="model_reference_coverage_unconfigured")
        before = await coverage.arequire_global_ready()
        await coverage.arequire_ready()
        owners = {receipt.target.key: receipt.target.target_tenant_id for receipt in receipts}
        sources, slots, observed_tenants = {}, dict.fromkeys(SourceType, 0), set()
        digest, cursor = hashlib.sha256(b"f118-model-inbound-v2\0"), None
        while scope is not None:
            page = await runtime.repository.alist_inbound_for_owner_page(session, scope, after_id=cursor)
            if not page:
                break
            for row in page:
                if type(row.id) is not int or not 0 < row.id < 2**64 or (cursor is not None and row.id <= cursor):
                    raise ReferenceCoverageNotReadyError(reason="reference_inbound_order_invalid")
                if (
                    row.target_tenant_id != owners[TargetKey(row.target_type, row.target_id)]
                    or row.target_space_id is not None
                    or row.legacy_invalid_reason is not None
                ):
                    raise ReferenceCoverageNotReadyError(reason="reference_inbound_target_inconsistent")
                key = SourceKey(row.tenant_id, row.source_type, row.source_id, row.source_version)
                sources[key] = sources.get(key, 0) + 1
                slots[key.source_type] += 1
                observed_tenants.add(row.tenant_id)
                digest.update(row.id.to_bytes(8, "big"))
                digest.update(_binding_digest(row))
                cursor = row.id
        return {
            "original": original,
            "stable": stable,
            "removal": removal,
            "receipts": receipts,
            "coverage": coverage,
            "before": before,
            "sources": sources,
            "slots": slots,
            "tenants": observed_tenants,
            "digest": digest.hexdigest(),
            "blocked": cursor is not None,
        }

    async def _finish(self, identity, facts):
        before = facts["before"]
        await facts["coverage"].arequire_global_ready(
            observed_source_tenant_ids=tuple(sorted(facts["tenants"])),
            expected_epoch=before.coverage_epoch,
            expected_inventory_hash=before.tenant_inventory_hash,
        )
        await facts["coverage"].arequire_ready()
        if (
            await self.identity.acapture(identity) != facts["original"]
            or await self._stable_identity(identity) != facts["stable"]
        ):
            raise ResourceReferenceInvalidError(reason="model_reference_identity_changed")

    @staticmethod
    def _candidates(facts):
        tenant = ReferenceRepository.current_tenant_id()
        return sorted(
            (key for key in facts["sources"] if key.tenant_id == tenant),
            key=lambda key: (key.source_type.value, key.source_id, key.source_version),
        )

    @staticmethod
    def _context(facts, size, delete_server):
        removal, before = facts["removal"], facts["before"]
        return source_context(
            {
                "command": [removal.server_id, removal.retained_model_ids, delete_server],
                "revisions": [
                    removal.server_revision,
                    removal.model_revisions,
                    [
                        (r.target.key.target_type.value, r.target.key.target_id, r.target.target_revision)
                        for r in facts["receipts"]
                    ],
                ],
                "inbound_v2": facts["digest"],
                "coverage": [before.coverage_epoch, before.tenant_inventory_hash],
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
        try:
            size = validate_page_size(source_page_size)
            facts = await self._dataset(
                session,
                identity=identity,
                server_id=server_id,
                retained_model_ids=retained_model_ids,
                delete_server=delete_server,
            )
            candidates = self._candidates(facts)
            counts, qualified, first = dict.fromkeys(SourceType, 0), dict.fromkeys(SourceType, 0), []
            for key in facts["sources"]:
                counts[key.source_type] += 1
            for start in range(0, len(candidates), 200):
                batch = candidates[start : start + 200]
                for offset, item in enumerate(await self._disclose(session, identity, batch)):
                    if item is not None:
                        qualified[item.source.source_type] += 1
                        if start + offset < size:
                            first.append(ModelReferenceSourceEntry(item, facts["sources"][item.source]))
            await self._finish(identity, facts)
            removal, before = facts["removal"], facts["before"]
            return ModelReferenceInspection(
                server_id=removal.server_id,
                targets=removal.targets,
                target_revisions=tuple((r.target.key, r.target.target_revision) for r in facts["receipts"]),
                server_revision=removal.server_revision,
                inbound_digest=facts["digest"],
                source_counts=tuple((kind.value, counts[kind]) for kind in SourceType),
                slot_counts=tuple((kind.value, facts["slots"][kind]) for kind in SourceType),
                restricted_counts=tuple((kind.value, counts[kind] - qualified[kind]) for kind in SourceType),
                qualified_counts=tuple((kind.value, qualified[kind]) for kind in SourceType),
                source_page=self._source_page(first, candidates, 0, size, self._context(facts, size, delete_server)),
                coverage_epoch=before.coverage_epoch,
                inventory_hash=before.tenant_inventory_hash,
                blocked=facts["blocked"],
            )
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
            candidates = self._candidates(facts)
            context = self._context(facts, size, delete_server)
            start = decode_source_cursor(cursor, context=context, candidate_count=len(candidates))
            data = tuple(
                ModelReferenceSourceEntry(item, facts["sources"][item.source])
                for item in await self._disclose(session, identity, candidates[start : start + size])
                if item is not None
            )
            await self._finish(identity, facts)
            return self._source_page(data, candidates, start, size, context)
        except BaseErrorCode:
            raise
        except Exception as error:
            raise ReferenceCoverageNotReadyError(reason="reference_check_failed") from error
