"""Internal model-removal impact, without execution or source disclosure.

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
from bisheng.database.models.tenant import ROOT_TENANT_ID
from bisheng.llm.domain.repositories.model_deletion_repository import ModelDeletionRepository
from bisheng.permission.application.identity import resolve_permission_actor
from bisheng.resource_reference.application.access import get_reference_binding_runtime
from bisheng.resource_reference.application.contracts import ReferenceState, SourceType, TargetKey
from bisheng.resource_reference.application.read_identity import AuthenticatedSourceReadIdentity
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
    def __init__(self, *, coverage_factory=None, runtime: ReferenceBindingRuntime | None = None):
        self.repository = ModelDeletionRepository()
        self.runtime = runtime
        self.coverage_factory = coverage_factory
        self.identity = AuthenticatedSourceReadIdentity()

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

    async def ainspect_removed_models(
        self, session, *, identity, server_id: int, retained_model_ids, delete_server: bool = False
    ) -> ModelReferenceInspection:
        original = await self._authorize(identity)
        try:
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
            sources = {kind: set() for kind in SourceType}
            slots = dict.fromkeys(SourceType, 0)
            observed_tenants, hashes, cursor = set(), [], None
            while scope is not None:
                page = await runtime.repository.alist_inbound_for_owner_page(session, scope, after_id=cursor)
                if not page:
                    break
                for row in page:
                    kind = SourceType(row.source_type)
                    sources[kind].add((row.tenant_id, row.source_type, row.source_id, row.source_version))
                    slots[kind] += 1
                    observed_tenants.add(row.tenant_id)
                    hashes.append(_binding_digest(row))
                cursor = page[-1].id
            await coverage.arequire_global_ready(
                observed_source_tenant_ids=tuple(sorted(observed_tenants)),
                expected_epoch=before.coverage_epoch,
                expected_inventory_hash=before.tenant_inventory_hash,
            )
            await coverage.arequire_ready()
            if await self.identity.acapture(identity) != original:
                raise ResourceReferenceInvalidError(reason="model_reference_identity_changed")
            # Sorting fixed-size hashes gives a canonical complete multiset
            # digest without retaining ORM pages or depending on row IDs.
            digest = hashlib.sha256(b"f118-model-inbound-v1\x00")
            for value in sorted(hashes):
                digest.update(value)
            counts = tuple((kind.value, len(sources[kind])) for kind in SourceType)
            return ModelReferenceInspection(
                server_id=removal.server_id,
                targets=removal.targets,
                target_revisions=tuple((receipt.target.key, receipt.target.target_revision) for receipt in receipts),
                server_revision=removal.server_revision,
                inbound_digest=digest.hexdigest(),
                source_counts=counts,
                slot_counts=tuple((kind.value, slots[kind]) for kind in SourceType),
                restricted_counts=counts,
                coverage_epoch=before.coverage_epoch,
                inventory_hash=before.tenant_inventory_hash,
                blocked=bool(hashes),
            )
        except BaseErrorCode:
            raise
        except Exception as error:
            raise ReferenceCoverageNotReadyError(reason="reference_check_failed") from error
