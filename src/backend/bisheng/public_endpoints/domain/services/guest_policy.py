"""Publication policy and request-context lifecycle for public v3 calls."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal

from loguru import logger

from bisheng.common.dependencies.user_deps import UserPayload
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
    set_current_permission_actor,
)
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.public_endpoints.domain.context import (
    PublicApiPrincipal,
    reset_current_public_api_principal,
    set_current_public_api_principal,
)
from bisheng.user.domain.models.user import UserDao


class PublicAccessError(Exception):
    """An intentionally small public-facing 403/404 failure."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True, slots=True)
class PublicExecution:
    principal: PublicApiPrincipal
    operator: UserPayload
    session_subject: object
    snapshot: OpenApiExecutionSnapshot


def reject_identity_headers(headers) -> None:
    """Anonymous calls may not assert either v2 identity channel."""

    if headers.get("x-on-behalf-of") is not None or headers.get("x-end-user") is not None:
        logger.warning("public_api.reject reason=identity_header")
        raise PublicAccessError(403, "Identity headers are not accepted by the public API")


async def _load_published_resource(resource_type: Literal["workflow", "assistant"], resource_id: str):
    with bypass_tenant_filter():
        if resource_type == "workflow":
            resource = await FlowDao.aget_flow_by_id(resource_id)
            published = bool(
                resource
                and resource.flow_type == FlowType.WORKFLOW.value
                and resource.status == FlowStatus.ONLINE.value
            )
        else:
            resource = await AssistantDao.aget_one_assistant(resource_id)
            published = bool(
                resource
                and not resource.is_delete
                and resource.status == AssistantStatus.ONLINE.value
            )
    if not published:
        logger.warning("public_api.reject reason=resource_unavailable type={} id={}", resource_type, resource_id)
        raise PublicAccessError(404, "Published resource not found")
    return resource


@asynccontextmanager
async def public_application_execution(resource_id: str) -> AsyncIterator[PublicExecution]:
    """Resolve a published workflow or assistant without exposing which lookup failed."""

    try:
        async with public_execution("workflow", resource_id) as execution:
            yield execution
            return
    except PublicAccessError as workflow_error:
        if workflow_error.status_code != 404:
            raise
    async with public_execution("assistant", resource_id) as execution:
        yield execution


async def _load_default_operator(tenant_id: int) -> UserPayload:
    config = await settings.aget_from_db("default_operator") or {}
    if not bool(config.get("enable_guest_access")):
        logger.warning("public_api.reject reason=guest_disabled tenant_id={}", tenant_id)
        raise PublicAccessError(403, "Guest access is disabled")
    operator_id = config.get("user")
    if not isinstance(operator_id, int) or operator_id <= 0:
        logger.warning("public_api.reject reason=operator_missing tenant_id={}", tenant_id)
        raise PublicAccessError(403, "Guest access is unavailable")

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
        raise PublicAccessError(403, "Guest access is unavailable")
    return UserPayload(
        user_id=user.user_id,
        user_name=user.user_name,
        user_role=[],
        tenant_id=tenant_id,
        is_global_super=False,
    )


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
        principal = PublicApiPrincipal(
            tenant_id=tenant_id,
            operator_user_id=operator.user_id,
            operator_name=operator.user_name,
            resource_type=resource_type,
            resource_id=resource_id,
        )
        actor_token = set_current_permission_actor(
            PermissionActor(
                subject_type="user",
                subject_id=operator.user_id,
                tenant_id=tenant_id,
                super_admin=False,
                tenant_admin_tenant_ids=frozenset(),
            )
        )
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
    "public_application_execution",
    "public_execution",
    "reject_identity_headers",
]
