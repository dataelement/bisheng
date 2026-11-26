"""One instance privately issues complete, transaction-bound model-name plans."""

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Literal
from weakref import WeakKeyDictionary, ref

from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.common.errcode.model_face import (
    ModelFaceCapabilityUndeclaredError,
    ModelFaceCatalogUnavailableError,
    ModelFaceModelAmbiguousError,
    ModelFaceModelNotFoundError,
    ModelFaceModelOfflineError,
)
from bisheng.common.errcode.tenant import NoTenantContextError
from bisheng.core.context.tenant import get_visible_tenant_ids, is_management_all_tenants, is_tenant_filter_bypassed
from bisheng.core.database.tenant_filter import _resolve_tenant_id
from bisheng.core.logger import trace_id_var
from bisheng.llm.domain.repositories.model_name_resolution_repository import ModelNameResolutionRepository
from bisheng.llm.domain.services.model_catalog import TENANT_RANGE, CallableModel, ModelRange, ResolvedModel
from bisheng.open_api.application.access_context import get_current_open_api_principal
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.permission.application import PermissionSubject, get_permission_relation_api
from bisheng.permission.application.identity import PermissionActor, get_current_permission_actor
from bisheng.public_endpoints.application.access_context import get_current_public_api_principal
from bisheng.resource_reference.application.contracts import TransactionIdentity, canonical_target_id
from bisheng.resource_reference.application.read_identity import AuthenticatedSourceReadIdentity
from bisheng.resource_reference.application.source_contracts import canonical_payload_json, payload_digest


@dataclass(frozen=True, slots=True)
class FrozenModelIdentity:
    model_id: int
    server_id: int

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in (self.model_id, self.server_id)):
            raise ValueError("frozen model/provider IDs must be positive integers")


@dataclass(frozen=True, slots=True)
class NameResolution:
    requested: str
    resolved: ResolvedModel


@dataclass(frozen=True, slots=True)
class ModelNameInspection:
    requested: str
    resolved: ResolvedModel | None
    status: Literal["valid", "unresolvable", "ambiguous", "offline"]

    def __post_init__(self):
        if (
            not isinstance(self.requested, str)
            or not self.requested
            or "\x00" in self.requested
            or self.status not in {"valid", "unresolvable", "ambiguous", "offline"}
            or (self.status == "valid") != isinstance(self.resolved, ResolvedModel)
            or (self.status != "valid" and self.resolved is not None)
        ):
            raise ValueError("model-name inspection must preserve its requested name and precise finding")


@dataclass(frozen=True, slots=True, eq=False, weakref_slot=True)
class PreparedModelNamePlan:
    tenant_id: int
    requested_names: tuple[str, ...]
    resolutions: tuple[NameResolution, ...]
    _nonce: object = field(default_factory=object, repr=False)


@dataclass(frozen=True, slots=True)
class _Registration:
    original: object
    transaction: TransactionIdentity
    identity: object
    fingerprint: object
    scope: ModelRange
    frozen_models: tuple[FrozenModelIdentity, ...]
    shared_ids: frozenset[int]
    catalog: object
    requested_names: tuple[str, ...]
    resolutions: tuple[NameResolution, ...]
    nonce: object


def _invalid():
    return ResourceReferenceInvalidError(reason="model_name_plan_invalid")


class ModelNameResolutionPort:
    def __init__(self, repository=None, *, sharing=None):
        self.repository = repository if repository is not None else ModelNameResolutionRepository()
        self.sharing = sharing
        self._issued = WeakKeyDictionary()

    @staticmethod
    async def _identity(identity, tenant_id):
        try:
            actual_tenant = _resolve_tenant_id()
        except NoTenantContextError as error:
            raise _invalid() from error
        if type(tenant_id) is not int or tenant_id <= 0 or actual_tenant != tenant_id or is_tenant_filter_bypassed():
            raise _invalid()
        if isinstance(identity, UserPayload):
            return (await AuthenticatedSourceReadIdentity().acapture(identity)).fingerprint
        principal = get_current_open_api_principal()
        if (
            not isinstance(identity, OpenApiPrincipal)
            or principal is not identity
            or identity.tenant_id != tenant_id
            or get_current_public_api_principal() is not None
        ):
            raise _invalid()
        actor = get_current_permission_actor()
        if actor is not None and not isinstance(actor, PermissionActor):
            raise _invalid()
        actor_facts = (
            None
            if actor is None
            else {
                "subject_type": actor.subject_type,
                "subject_id": actor.subject_id,
                "current_tenant_id": actor.current_tenant_id,
                "super_admin": actor.super_admin,
                "tenant_admin_ids": sorted(actor.tenant_admin_tenant_ids),
                "data_scope": actor.data_scope,
            }
        )
        visible = get_visible_tenant_ids()
        return payload_digest(
            canonical_payload_json(
                {
                    "principal": identity.model_dump(mode="json"),
                    "actor": actor_facts,
                    "tenant": tenant_id,
                    "visible": sorted(visible) if visible is not None else None,
                    "management": is_management_all_tenants(),
                    "trace": trace_id_var.get(),
                }
            )
        )

    @staticmethod
    def _assert_transaction(transaction, session):
        try:
            transaction.assert_current(session)
        except (TypeError, ValueError) as error:
            raise _invalid() from error

    async def _shared(self, session, tenant_id):
        if tenant_id == 1:
            return frozenset()
        try:
            if self.sharing is not None:
                ids = await self.sharing.aget_shared_server_ids(session, tenant_id)
            else:
                api = await get_permission_relation_api()
                ids = await api.list_resource_ids(
                    subject=PermissionSubject("tenant", str(tenant_id)),
                    relation="shared_with",
                    resource_type="llm_server",
                )
            if not isinstance(ids, (tuple, frozenset)) or any(
                isinstance(value, bool)
                or not isinstance(value, (str, int))
                or not str(value).isascii()
                or not str(value).isdecimal()
                or int(value) <= 0
                for value in ids
            ):
                raise ValueError("incomplete sharing catalog")
            return frozenset(int(value) for value in ids)
        except Exception as error:
            raise ModelFaceCatalogUnavailableError(exception=error) from error

    @staticmethod
    def _resolve(catalog, requested, scope):
        servers = {server.id: server for server in catalog.servers}
        available = [
            model
            for model in catalog.models
            if model.server_id in catalog.visible_server_ids and model.model_type == "llm"
        ]
        online = [model for model in available if model.online]
        exact = [model for model in online if model.model_name == requested]
        matches = exact or [
            model for model in online if requested == f"{servers[model.server_id].name}/{model.model_name}"
        ]
        if len(matches) > 1:
            raise ModelFaceModelAmbiguousError(
                model=requested,
                candidates=sorted(f"{servers[model.server_id].name}/{model.model_name}" for model in matches),
            )
        if not matches:
            if any(
                not model.online
                and (
                    model.model_name == requested or requested == f"{servers[model.server_id].name}/{model.model_name}"
                )
                for model in available
            ):
                raise ModelFaceModelOfflineError(model=requested)
            raise ModelFaceModelNotFoundError(model=requested)
        model, server = matches[0], servers[matches[0].server_id]
        value = CallableModel(model.id, model.model_name, server.id, server.name, server.type, len(exact) == 1)
        if not scope.allows(value):
            raise ModelFaceCapabilityUndeclaredError(model=requested)
        return ResolvedModel(model.id, server.id, model.model_name, server.name, server.type, value.qualified_name)

    async def aprepare_model_names_current(
        self,
        session,
        tenant_id,
        requested_names,
        *,
        identity,
        frozen_models=(),
        range=None,
    ):
        if not isinstance(session, AsyncSession):
            raise _invalid()
        fingerprint = await self._identity(identity, tenant_id)
        scope = range if range is not None else TENANT_RANGE
        if (
            not isinstance(scope, ModelRange)
            or scope.kind not in {"tenant", "declared"}
            or (
                scope.declared is not None
                and (
                    not isinstance(scope.declared, frozenset)
                    or any(not isinstance(value, str) for value in scope.declared)
                )
            )
            or not isinstance(requested_names, tuple)
            or any(not isinstance(name, str) or not name or "\x00" in name for name in requested_names)
            or not isinstance(frozen_models, tuple)
            or any(not isinstance(item, FrozenModelIdentity) for item in frozen_models)
        ):
            raise _invalid()
        requested_names = tuple(sorted(set(requested_names)))
        frozen_models = tuple(sorted(set(frozen_models), key=lambda item: (item.server_id, item.model_id)))
        prior = TransactionIdentity.capture(session) if session.in_transaction() else None
        shared_ids = await self._shared(session, tenant_id)
        try:
            catalog = await self.repository.aprepare_catalog(session, tenant_id, shared_ids, frozen_models)
        except (ResourceReferenceInvalidError, KnowledgeOperationPlanConflictError):
            raise
        except Exception as error:
            raise ModelFaceCatalogUnavailableError(exception=error) from error
        if prior is not None:
            self._assert_transaction(prior, session)
        if await self._identity(identity, tenant_id) != fingerprint:
            raise _invalid()
        resolutions = tuple(NameResolution(name, self._resolve(catalog, name, scope)) for name in requested_names)
        plan = PreparedModelNamePlan(tenant_id, requested_names, resolutions)
        self._issued[plan] = _Registration(
            ref(plan),
            TransactionIdentity.capture(session),
            identity,
            fingerprint,
            deepcopy(scope),
            frozen_models,
            shared_ids,
            catalog,
            requested_names,
            deepcopy(resolutions),
            plan._nonce,
        )
        return plan

    async def _validate_plan(self, session, tenant_id, *, identity, plan, range=None):
        registered = self._issued.get(plan) if isinstance(plan, PreparedModelNamePlan) else None
        if (
            registered is None
            or registered.original() is not plan
            or registered.identity is not identity
            or plan.tenant_id != tenant_id
            or plan.requested_names != registered.requested_names
            or plan.resolutions != registered.resolutions
            or plan._nonce is not registered.nonce
            or (range if range is not None else TENANT_RANGE) != registered.scope
        ):
            raise _invalid()
        self._assert_transaction(registered.transaction, session)
        if await self._identity(identity, tenant_id) != registered.fingerprint:
            raise _invalid()
        shared_ids = await self._shared(session, tenant_id)
        if shared_ids != registered.shared_ids:
            raise KnowledgeOperationPlanConflictError(reason="model_name_catalog_changed")
        try:
            catalog = await self.repository.arevalidate_catalog(
                session, registered.catalog, shared_ids, registered.frozen_models
            )
        except (ResourceReferenceInvalidError, KnowledgeOperationPlanConflictError):
            raise
        except Exception as error:
            raise ModelFaceCatalogUnavailableError(exception=error) from error
        self._assert_transaction(registered.transaction, session)
        if await self._identity(identity, tenant_id) != registered.fingerprint:
            raise _invalid()
        resolutions = tuple(
            NameResolution(name, self._resolve(catalog, name, registered.scope)) for name in plan.requested_names
        )
        if resolutions != plan.resolutions:
            raise KnowledgeOperationPlanConflictError(reason="model_name_catalog_changed")
        return resolutions

    async def ainspect_model_names_current(self, session, tenant_id, requested, *, identity):
        if (
            not isinstance(session, AsyncSession)
            or not isinstance(requested, tuple)
            or any(not isinstance(name, str) or not name or "\x00" in name for name in requested)
        ):
            raise _invalid()
        fingerprint = await self._identity(identity, tenant_id)
        prior = TransactionIdentity.capture(session) if session.in_transaction() else None
        shared_ids = await self._shared(session, tenant_id)
        try:
            catalog = await self.repository.ainspect_catalog(session, tenant_id, shared_ids)
        except ResourceReferenceInvalidError:
            raise
        except Exception as error:
            raise ModelFaceCatalogUnavailableError(exception=error) from error
        if prior is not None:
            self._assert_transaction(prior, session)
        if await self._identity(identity, tenant_id) != fingerprint:
            raise _invalid()
        findings = []
        for name in requested:
            try:
                resolved = self._resolve(catalog, name, TENANT_RANGE)
            except ModelFaceModelNotFoundError:
                findings.append(ModelNameInspection(name, None, "unresolvable"))
            except ModelFaceModelAmbiguousError:
                findings.append(ModelNameInspection(name, None, "ambiguous"))
            except ModelFaceModelOfflineError:
                findings.append(ModelNameInspection(name, None, "offline"))
            else:
                findings.append(ModelNameInspection(name, resolved, "valid"))
        return tuple(findings)

    async def aresolve_frozen_model_identities(self, session, tenant_id, model_ids, *, identity):
        if not isinstance(session, AsyncSession) or not isinstance(model_ids, tuple):
            raise _invalid()
        try:
            model_ids = tuple(sorted({int(canonical_target_id(value)) for value in model_ids}))
        except (TypeError, ValueError) as error:
            raise _invalid() from error
        fingerprint = await self._identity(identity, tenant_id)
        prior = TransactionIdentity.capture(session) if session.in_transaction() else None
        try:
            rows = await self.repository.aresolve_frozen_model_identities(session, tenant_id, model_ids)
        except ResourceReferenceInvalidError:
            raise
        except Exception as error:
            raise ModelFaceCatalogUnavailableError(exception=error) from error
        if prior is not None:
            self._assert_transaction(prior, session)
        if await self._identity(identity, tenant_id) != fingerprint:
            raise _invalid()
        return tuple(FrozenModelIdentity(model_id, server_id) for model_id, server_id in rows)

    async def assert_plan_current(self, session, tenant_id, *, identity, plan, range=None):
        await self._validate_plan(session, tenant_id, identity=identity, plan=plan, range=range)

    async def resolve_model_names_current(self, session, tenant_id, *, identity, plan, range=None):
        """Revalidate once and return the entire issued plan for this stage.

        The result is data, not a reusable authority: each later source-read or
        locked verification stage must call this method again in its original
        transaction and identity. No sharing/catalog validation is cached.
        """
        return await self._validate_plan(session, tenant_id, identity=identity, plan=plan, range=range)

    async def resolve_model_alias_current(self, session, tenant_id, requested, *, identity, plan, range=None):
        resolutions = await self._validate_plan(session, tenant_id, identity=identity, plan=plan, range=range)
        allowed_aliases = {
            alias for item in resolutions for alias in (item.resolved.model_name, item.resolved.qualified_name)
        }
        if not isinstance(requested, str) or requested not in allowed_aliases:
            raise _invalid()
        registered = self._issued[plan]
        resolved = self._resolve(registered.catalog, requested, registered.scope)
        if (resolved.model_id, resolved.server_id) not in {
            (item.resolved.model_id, item.resolved.server_id) for item in resolutions
        }:
            raise _invalid()
        return resolved

    async def resolve_model_name_current(self, session, tenant_id, requested, *, identity, plan, range=None):
        resolutions = await self._validate_plan(session, tenant_id, identity=identity, plan=plan, range=range)
        match = next((item.resolved for item in resolutions if item.requested == requested), None)
        if match is None:
            raise _invalid()
        return match


_port: ModelNameResolutionPort | None = None


def get_model_name_resolution_port() -> ModelNameResolutionPort:
    global _port
    if _port is None:
        _port = ModelNameResolutionPort()
    return _port
