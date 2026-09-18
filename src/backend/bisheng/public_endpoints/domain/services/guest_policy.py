"""Publication policy and request-context lifecycle for public v3 calls."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal

from loguru import logger

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.public_endpoints import (
    PublicAccessError,
    PublicApplicationOfflineError,
    PublicGuestAccessDisabledError,
    PublicLinkInvalidError,
)
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    visible_tenant_ids,
)
from bisheng.database.models.assistant import AssistantDao, AssistantStatus
from bisheng.database.models.flow import FlowDao, FlowStatus, FlowType
from bisheng.database.models.tenant import TenantDao, UserTenantDao
from bisheng.open_api.domain.context import OpenApiExecutionSnapshot
from bisheng.permission.application.identity import (
    reset_current_permission_actor,
    resolve_permission_actor,
    set_current_permission_actor,
)
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.public_endpoints.domain.context import (
    PublicApiPrincipal,
    reset_current_public_api_principal,
    set_current_public_api_principal,
)
from bisheng.user.domain.models.user import UserDao

# What a lookup found. "missing" and "offline" are deliberately distinct: a
# visitor can act on "the app was taken offline" but not on a generic 404.
PublicationOutcome = Literal["published", "offline", "missing"]


@dataclass(frozen=True, slots=True)
class PublicExecution:
    principal: PublicApiPrincipal
    operator: UserPayload
    session_subject: object
    snapshot: OpenApiExecutionSnapshot


async def _probe_published_resource(
    resource_type: Literal["workflow", "assistant"],
    resource_id: str,
) -> tuple[PublicationOutcome, object | None]:
    """Classify one lookup without raising, so callers can compare both types.

    A type mismatch is ``missing``, never ``offline``: an assistant id probed
    on the workflow side must not make the whole link report "taken offline".
    A deleted assistant is likewise ``missing`` — the link is broken, not the
    app paused.
    """

    with bypass_tenant_filter():
        if resource_type == "workflow":
            resource = await FlowDao.aget_flow_by_id(resource_id)
            if resource is None or resource.flow_type != FlowType.WORKFLOW.value:
                return "missing", None
            if resource.status != FlowStatus.ONLINE.value:
                return "offline", resource
        else:
            resource = await AssistantDao.aget_one_assistant(resource_id)
            if resource is None or resource.is_delete:
                return "missing", None
            if resource.status != AssistantStatus.ONLINE.value:
                return "offline", resource
    return "published", resource


async def _load_published_resource(resource_type: Literal["workflow", "assistant"], resource_id: str):
    """Resolve one published workflow or assistant, or raise the visitor-facing error."""

    outcome, resource = await _probe_published_resource(resource_type, resource_id)
    if outcome == "offline":
        logger.warning("public_api.reject reason=resource_offline type={} id={}", resource_type, resource_id)
        raise PublicApplicationOfflineError()
    if outcome == "missing":
        logger.warning("public_api.reject reason=resource_missing type={} id={}", resource_type, resource_id)
        raise PublicLinkInvalidError()
    return resource


@asynccontextmanager
async def public_application_execution(resource_id: str) -> AsyncIterator[PublicExecution]:
    """Resolve a published workflow or assistant from a bare id.

    Classification happens up front, before the context is entered. An earlier
    version wrapped ``yield`` in try/except, which swallowed any 404 raised by
    the caller's own ``async with`` body and retried the lookup as an
    assistant; keeping the probe outside the context manager removes that.
    """

    workflow_outcome, _ = await _probe_published_resource("workflow", resource_id)
    if workflow_outcome == "published":
        resource_type: Literal["workflow", "assistant"] = "workflow"
    else:
        assistant_outcome, _ = await _probe_published_resource("assistant", resource_id)
        if assistant_outcome == "published":
            resource_type = "assistant"
        elif "offline" in (workflow_outcome, assistant_outcome):
            # Offline wins over missing: one side found the app, it is just paused.
            logger.warning("public_api.reject reason=resource_offline id={}", resource_id)
            raise PublicApplicationOfflineError()
        else:
            logger.warning("public_api.reject reason=resource_missing id={}", resource_id)
            raise PublicLinkInvalidError()

    async with public_execution(resource_type, resource_id) as execution:
        yield execution


async def _load_default_operator(tenant_id: int) -> UserPayload:
    config = await settings.aget_from_db("default_operator") or {}
    if not bool(config.get("enable_guest_access")):
        logger.warning("public_api.reject reason=guest_disabled tenant_id={}", tenant_id)
        raise PublicGuestAccessDisabledError()
    operator_id = config.get("user")
    if not isinstance(operator_id, int) or operator_id <= 0:
        logger.warning("public_api.reject reason=operator_missing tenant_id={}", tenant_id)
        raise PublicGuestAccessDisabledError()

    with bypass_tenant_filter():
        user = await UserDao.aget_user(operator_id)
        membership = await UserTenantDao.aget_user_tenant(operator_id, tenant_id)
        tenant = await TenantDao.aget_by_id(tenant_id)
    if (
        user is None
        or bool(user.delete)
        or membership is None
        or membership.status != "active"
        or tenant is None
        or tenant.status != "active"
    ):
        logger.warning("public_api.reject reason=operator_inactive tenant_id={}", tenant_id)
        raise PublicGuestAccessDisabledError()

    # Guests execute as the configured operator, with that account's real roles
    # and real global-super flag. The operator's permissions ARE the visitor's
    # reach — configuring a super admin here grants visitors a super admin's
    # view, which is why initdb_config says not to. Stripping privilege here
    # instead would silently diverge from what the same link does today.
    #
    # ``tenant_id`` is the resource's tenant, not the operator's active one:
    # ``_check_is_global_super`` ignores tenant entirely, and ``is_tenant_admin``
    # then asks about the tenant this request is actually pinned to.
    return await UserPayload.init_login_user(
        user_id=user.user_id,
        user_name=user.user_name,
        tenant_id=tenant_id,
    )


async def _resolve_guest_actor(operator: UserPayload) -> PermissionActor:
    """Derive the authorization actor from the operator's real identity.

    ``resolve_permission_actor`` returns the ambient actor when one is already
    installed. An anonymous channel must never inherit an upstream identity, so
    the context var is explicitly cleared for the duration of the lookup rather
    than relying on call ordering.
    """

    token = set_current_permission_actor(None)
    try:
        return await resolve_permission_actor(operator)
    except Exception as exc:  # authorization backend unavailable -> fail closed
        logger.warning(
            "public_api.reject reason=actor_unresolved tenant_id={} err={}",
            operator.tenant_id,
            exc,
        )
        raise PublicGuestAccessDisabledError(exception=exc) from exc
    finally:
        reset_current_permission_actor(token)


@asynccontextmanager
async def public_execution(
    resource_type: Literal["workflow", "assistant"],
    resource_id: str,
) -> AsyncIterator[PublicExecution]:
    """Resolve one published resource, then install its strict tenant scope."""

    resource = await _load_published_resource(resource_type, resource_id)
    tenant_id = int(resource.tenant_id)
    tenant_token = current_tenant_id.set(tenant_id)
    visible_token = visible_tenant_ids.set(frozenset({tenant_id}))
    actor_token = None
    public_token = None
    try:
        operator = await _load_default_operator(tenant_id)
        actor = await _resolve_guest_actor(operator)
        principal = PublicApiPrincipal(
            tenant_id=tenant_id,
            operator_user_id=operator.user_id,
            operator_name=operator.user_name,
            resource_type=resource_type,
            resource_id=resource_id,
        )
        actor_token = set_current_permission_actor(actor)
        public_token = set_current_public_api_principal(principal)
        from bisheng.chat_session.domain.session_subject import SessionSubject

        yield PublicExecution(
            principal=principal,
            operator=operator,
            session_subject=SessionSubject.public_v3(
                tenant_id=tenant_id,
                operator_user_id=operator.user_id,
                resource_id=resource_id,
            ),
            snapshot=OpenApiExecutionSnapshot(
                tenant_id=tenant_id,
                actor_kind="natural_person",
                actor_id=operator.user_id,
                authorization_subject_type="user",
                authorization_subject_id=operator.user_id,
                resource_owner_user_id=operator.user_id,
                effective_user_id=operator.user_id,
                mode="S",
                credential_id=None,
                trace_id="public-v3",
                channel="public_v3",
                # Carry the resolved privilege so the Celery leg authorizes
                # against the same facts as this handshake.
                super_admin=actor.super_admin,
                tenant_admin_tenant_ids=actor.tenant_admin_tenant_ids,
            ),
        )
    finally:
        if public_token is not None:
            reset_current_public_api_principal(public_token)
        if actor_token is not None:
            reset_current_permission_actor(actor_token)
        visible_tenant_ids.reset(visible_token)
        current_tenant_id.reset(tenant_token)


__all__ = [
    "PublicAccessError",
    "PublicExecution",
    "PublicationOutcome",
    "public_application_execution",
    "public_execution",
]
