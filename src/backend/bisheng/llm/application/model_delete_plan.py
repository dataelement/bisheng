"""Internal model-removal confirmations; no business mutation or publication.

The caller supplies an active native transaction. One owned SAVEPOINT contains
the real impact inspection and the one confirmation INSERT. A plan records no
provider request body and grants no deletion or sharing authority.
"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ReferenceCoverageNotReadyError
from bisheng.core.context.tenant import (
    get_admin_scope_tenant_id,
    get_is_management_api,
    get_visible_tenant_ids,
    is_management_all_tenants,
)
from bisheng.llm.domain.repositories.model_delete_plan_repository import (
    ModelDeleteConfirmation,
    ModelDeletePlanRepository,
    _hash,
)
from bisheng.llm.domain.schemas import LLMModelCreateReq, LLMServerCreateReq
from bisheng.llm.domain.services.model_reference_service import ModelReferenceInspection, ModelReferenceService
from bisheng.open_api.application.access_context import get_current_open_api_principal
from bisheng.permission.application.identity import (
    PermissionActor,
    get_current_permission_actor,
    resolve_permission_actor,
)
from bisheng.public_endpoints.application.access_context import get_current_public_api_principal
from bisheng.resource_reference.application.contracts import TransactionIdentity
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository


@dataclass(frozen=True, slots=True)
class ModelDeletePrecheck:
    inspection: ModelReferenceInspection
    confirmation: ModelDeleteConfirmation


def _changed():
    raise KnowledgeOperationPlanConflictError(reason="model_delete_plan_context_changed")


class _Scope:
    def __init__(self, session):
        if not isinstance(session, AsyncSession) or not session.in_transaction():
            raise ReferenceCoverageNotReadyError(reason="model_delete_plan_active_native_transaction_required")
        self.session = session
        self.tenant_id = ReferenceRepository.current_tenant_id()
        self.transaction = TransactionIdentity.capture(session)
        self.check()

    def check(self):
        try:
            if ReferenceRepository.current_tenant_id() != self.tenant_id or is_management_all_tenants():
                raise ValueError("model plan requires its original concrete tenant")
            self.transaction.assert_current(self.session)
        except (BaseErrorCode, TypeError, ValueError) as error:
            raise ReferenceCoverageNotReadyError(reason="model_delete_plan_transaction_changed") from error

    async def call(self, method, *args, **kwargs):
        self.check()
        value = await method(*args, **kwargs)
        self.check()
        return value


def _identity_facts(identity):
    if not isinstance(identity, UserPayload):
        _changed()
    if get_current_open_api_principal() is not None or get_current_public_api_principal() is not None:
        _changed()
    visible = get_visible_tenant_ids()
    return (
        identity.user_id,
        identity.tenant_id,
        identity.token_version,
        identity.is_global_super,
        tuple(sorted(identity.user_role)),
        deepcopy(identity._runtime_credential_reference),
        get_current_permission_actor(),
        get_admin_scope_tenant_id(),
        get_is_management_api(),
        frozenset(visible) if visible is not None else None,
    )


class ModelDeletePlanApplication:
    def __init__(
        self, *, references: ModelReferenceService, plans: ModelDeletePlanRepository | None = None, ttl_seconds=300
    ):
        if not isinstance(references, ModelReferenceService):
            raise TypeError("a real model reference service is required")
        if plans is not None and not isinstance(plans, ModelDeletePlanRepository):
            raise TypeError("a real model delete plan repository is required")
        if type(ttl_seconds) is not int or ttl_seconds <= 0:
            raise ValueError("a positive confirmation TTL is required")
        self.references = references
        self.plans = plans if plans is not None else ModelDeletePlanRepository()
        self.ttl_seconds = ttl_seconds

    async def _capture(self, scope, identity):
        before = _identity_facts(identity)
        actor = await scope.call(resolve_permission_actor, identity)
        if before != _identity_facts(identity) or not isinstance(actor, PermissionActor):
            _changed()
        reference = {
            "tenant_id": scope.tenant_id,
            "actor_user_id": identity.user_id,
            "credential_reference": deepcopy(before[5]),
            "data_scope": actor.data_scope,
        }
        if get_is_management_api() and get_admin_scope_tenant_id() is not None:
            reference["management_tenant_id"] = get_admin_scope_tenant_id()
        try:
            reference = self.plans._actor(reference, scope.tenant_id)
        except (TypeError, ValueError) as error:
            raise KnowledgeOperationPlanConflictError(reason="model_delete_plan_web_identity_required") from error
        credential = reference["credential_reference"]
        if credential["tenant_id"] != identity.tenant_id or credential["token_version"] != identity.token_version:
            _changed()
        return before, actor, reference

    async def _plan(self, session, *, identity, operation, server_id, retained, command_digest):
        outer = _Scope(session)
        if session.new or session.dirty or session.deleted:
            raise ValueError("model precheck cannot flush pending ORM writes")
        async with session.begin_nested() as savepoint:
            scope = _Scope(session)
            if (
                savepoint.sync_transaction is not scope.transaction.transaction
                or savepoint.sync_transaction.parent is not outer.transaction.transaction
            ):
                raise ReferenceCoverageNotReadyError(reason="model_delete_plan_savepoint_changed")
            original = await self._capture(scope, identity)
            inspection = await scope.call(
                self.references.ainspect_removed_models,
                session,
                identity=identity,
                server_id=server_id,
                retained_model_ids=retained,
                delete_server=operation == "model_delete_server",
            )
            if inspection.check_complete is not True:
                raise ReferenceCoverageNotReadyError(reason="model_delete_plan_inspection_incomplete")
            if operation == "model_update_server" and not inspection.targets:
                _changed()
            if await self._capture(scope, identity) != original:
                _changed()
            if session.new or session.dirty or session.deleted:
                _changed()
            confirmation = await scope.call(
                self.plans.acreate_model_delete_plan,
                session,
                operation=operation,
                actor_reference=original[2],
                command_digest=command_digest,
                targets=inspection.targets,
                target_revisions={
                    **{f"model:{target.target_id}": revision for target, revision in inspection.target_revisions},
                    f"server:{inspection.server_id}": inspection.server_revision,
                },
                inbound_digest=inspection.inbound_digest,
                coverage_epoch=inspection.coverage_epoch,
                inventory_hash=inspection.inventory_hash,
                expires_at=self.plans.clock() + timedelta(seconds=self.ttl_seconds),
            )
            if await self._capture(scope, identity) != original:
                _changed()
            scope.check()
            result = ModelDeletePrecheck(inspection, confirmation)
        outer.check()
        # No new async identity operation after releasing the owned SAVEPOINT.
        if _identity_facts(identity) != original[0]:
            _changed()
        return result

    async def aplan_removed_update(
        self, session: AsyncSession, *, identity: UserPayload, server: LLMServerCreateReq
    ) -> ModelDeletePrecheck:
        if type(server) is not LLMServerCreateReq:
            raise ValueError("the original typed provider update request is required")
        snapshot = server.model_copy(deep=True)
        if (
            type(snapshot.id) is not int
            or snapshot.id <= 0
            or type(snapshot.models) is not list
            or any(type(model) is not LLMModelCreateReq for model in snapshot.models)
        ):
            raise ValueError("an exact provider update and model list are required")
        retained = tuple(
            model.id
            for model in snapshot.models
            if model.id is not None and not (type(model.id) is int and model.id == 0)
        )
        return await self._plan(
            session,
            identity=identity,
            operation="model_update_server",
            server_id=snapshot.id,
            retained=retained,
            command_digest=_hash({"operation": "model_update_server", "server": snapshot.model_dump(mode="json")}),
        )

    async def aplan_server_delete(
        self, session: AsyncSession, *, identity: UserPayload, server_id: int
    ) -> ModelDeletePrecheck:
        if type(server_id) is not int or server_id <= 0:
            raise ValueError("an exact provider identity is required")
        return await self._plan(
            session,
            identity=identity,
            operation="model_delete_server",
            server_id=server_id,
            retained=(),
            command_digest=_hash({"operation": "model_delete_server", "server_id": server_id}),
        )
