"""Per-app guest-link switch stored as one config row per application."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from loguru import logger
from pydantic import BaseModel, Field

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.common.models.config import ConfigDao
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.constants import AdminRole
from bisheng.database.models.assistant import AssistantDao
from bisheng.database.models.audit_log import AuditLog, AuditLogDao, EventType, ObjectType, SystemId
from bisheng.database.models.flow import FlowDao, FlowType
from bisheng.database.models.tenant import TenantDao, UserTenantDao
from bisheng.database.models.user_group import UserGroupDao
from bisheng.permission.application.business_authorization import check_business_action
from bisheng.user.domain.models.user import UserDao
from bisheng.user.domain.models.user_role import UserRoleDao

GuestResourceType = Literal["workflow", "assistant"]

_CANDIDATE_PAGE_SIZE = 100


class GuestLinkPatchRequest(BaseModel):
    enabled: bool | None = None
    user_id: int | None = Field(default=None)


@dataclass(frozen=True, slots=True)
class AppGuestLink:
    enabled: bool = True
    user_id: int | None = None
    updated_by: int | None = None


def guest_link_config_key(resource_type: GuestResourceType, resource_id: str) -> str:
    return f"guest_link:{resource_type}:{normalize_app_id(resource_id)}"


def normalize_app_id(raw: str) -> str:
    try:
        return UUID(str(raw)).hex
    except ValueError:
        return str(raw)


def parse_app_guest_link(value: str | None, *, strict: bool) -> AppGuestLink:
    if not value:
        return AppGuestLink()
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        if strict:
            raise
        return AppGuestLink()
    if not isinstance(data, dict):
        if strict:
            raise ValueError("guest_link value is not an object")
        return AppGuestLink()
    enabled = data.get("enabled", True)
    if not isinstance(enabled, bool):
        enabled = bool(enabled)
    raw_uid = data.get("user_id")
    user_id: int | None
    if raw_uid is None:
        user_id = None
    elif isinstance(raw_uid, int) and raw_uid > 0:
        user_id = raw_uid
    else:
        if strict:
            raise ValueError("guest_link user_id is invalid")
        user_id = None
    raw_updated = data.get("updated_by")
    updated_by = raw_updated if isinstance(raw_updated, int) else None
    return AppGuestLink(enabled=enabled, user_id=user_id, updated_by=updated_by)


async def load_app_guest_link(
    resource_type: GuestResourceType,
    resource_id: str,
    *,
    strict: bool = False,
) -> AppGuestLink:
    row = await ConfigDao.aget_config_by_key(guest_link_config_key(resource_type, resource_id))
    value = None if row is None else row.value
    try:
        return parse_app_guest_link(value, strict=strict)
    except (json.JSONDecodeError, ValueError):
        if strict:
            raise
        return AppGuestLink()


async def save_app_guest_link(
    resource_type: GuestResourceType,
    resource_id: str,
    link: AppGuestLink,
    *,
    updated_by: int,
) -> None:
    payload = {
        "enabled": link.enabled,
        "user_id": link.user_id,
        "updated_by": updated_by,
    }
    await ConfigDao.insert_or_update_config(
        guest_link_config_key(resource_type, resource_id),
        json.dumps(payload, ensure_ascii=False),
    )


def delete_app_guest_link(resource_type: GuestResourceType, resource_id: str) -> None:
    ConfigDao.delete_by_key(guest_link_config_key(resource_type, resource_id))


async def _load_resource(resource_type: GuestResourceType, resource_id: str):
    app_id = normalize_app_id(resource_id)
    if resource_type == "workflow":
        resource = await FlowDao.aget_flow_by_id(app_id)
        if resource is None or resource.flow_type != FlowType.WORKFLOW.value:
            raise NotFoundError()
        return resource, int(resource.tenant_id), resource.name, app_id
    resource = await AssistantDao.aget_one_assistant(app_id)
    if resource is None or resource.is_delete:
        raise NotFoundError()
    return resource, int(resource.tenant_id), resource.name, app_id


async def _require_visible(login_user: UserPayload, resource_type: GuestResourceType, resource_id: str) -> None:
    if not await check_business_action(
        login_user,
        resource_type=resource_type,
        resource_id=resource_id,
        action="visible",
    ):
        raise UnAuthorizedError()


async def _require_share(login_user: UserPayload, resource_type: GuestResourceType, resource_id: str) -> None:
    if not await check_business_action(
        login_user,
        resource_type=resource_type,
        resource_id=resource_id,
        action="share",
    ):
        raise UnAuthorizedError()


async def _is_forbidden_operator(user_id: int, tenant_id: int) -> bool:
    from bisheng.permission.application.relation_api import is_tenant_admin
    from bisheng.utils.http_middleware import _check_is_global_super

    try:
        if await _check_is_global_super(user_id):
            return True
        if await is_tenant_admin(user_id, tenant_id):
            return True
    except Exception:
        logger.exception("guest_link operator privilege check failed user_id={} tenant_id={}", user_id, tenant_id)
        return True
    return False


async def _operator_is_live(user_id: int, tenant_id: int) -> bool:
    with bypass_tenant_filter():
        user = await UserDao.aget_user(user_id)
        membership = await UserTenantDao.aget_user_tenant(user_id, tenant_id)
        tenant = await TenantDao.aget_by_id(tenant_id)
    return not (
        user is None
        or bool(user.delete)
        or membership is None
        or membership.status != "active"
        or tenant is None
        or tenant.status != "active"
    )


async def _load_user_name(user_id: int | None) -> str | None:
    if user_id is None:
        return None
    with bypass_tenant_filter():
        user = await UserDao.aget_user(user_id)
    if user is None:
        return None
    return user.user_name


async def _system_default_operator() -> tuple[bool, int | None]:
    from bisheng.common.services.config_service import settings

    config = await settings.aget_from_db("default_operator") or {}
    enabled = bool(config.get("enable_guest_access"))
    operator_id = config.get("user")
    if not isinstance(operator_id, int) or operator_id <= 0:
        return enabled, None
    return enabled, operator_id


async def _validate_new_operator(user_id: int, tenant_id: int) -> None:
    with bypass_tenant_filter():
        user = await UserDao.aget_user(user_id)
        membership = await UserTenantDao.aget_user_tenant(user_id, tenant_id)
    if user is None or bool(user.delete):
        raise UnAuthorizedError()
    if membership is None or membership.status != "active":
        raise UnAuthorizedError()
    if await _is_forbidden_operator(user_id, tenant_id):
        raise UnAuthorizedError()


async def _candidate_users(
    tenant_id: int,
    *,
    pinned_ids: set[int],
) -> list[dict[str, Any]]:
    rows, _total = await UserTenantDao.aget_tenant_users(
        tenant_id,
        page=1,
        page_size=_CANDIDATE_PAGE_SIZE,
    )
    user_ids = [int(row["user_id"]) for row in rows if row.get("user_id")]
    for pinned in pinned_ids:
        if pinned not in user_ids:
            user_ids.append(pinned)
    users = await UserDao.aget_user_by_ids(user_ids) or []
    alive = {int(user.user_id): user for user in users if not bool(user.delete)}
    admin_roles = await UserRoleDao.aget_roles_user([AdminRole])
    admin_ids = {int(role.user_id) for role in admin_roles}

    selectable: list[dict[str, Any]] = []
    seen: set[int] = set()
    remaining: list[int] = []
    for user_id in alive:
        if user_id in admin_ids and user_id not in pinned_ids:
            continue
        remaining.append(user_id)

    flags = await asyncio.gather(*[_is_forbidden_operator(user_id, tenant_id) for user_id in remaining])
    allowed = {user_id for user_id, forbidden in zip(remaining, flags, strict=True) if not forbidden}
    allowed.update(pinned_ids)

    for user_id in remaining:
        if user_id not in allowed or user_id in seen:
            continue
        user = alive.get(user_id)
        if user is None:
            continue
        selectable.append({"user_id": user_id, "user_name": user.user_name})
        seen.add(user_id)

    for pinned in pinned_ids:
        if pinned in seen:
            continue
        user = alive.get(pinned)
        if user is None:
            with bypass_tenant_filter():
                user = await UserDao.aget_user(pinned)
        if user is None:
            continue
        selectable.append({"user_id": pinned, "user_name": user.user_name})
        seen.add(pinned)

    selectable.sort(key=lambda item: item["user_name"] or "")
    return selectable


async def get_guest_link_settings(
    login_user: UserPayload,
    resource_type: GuestResourceType,
    resource_id: str,
) -> dict[str, Any]:
    _resource, tenant_id, _name, app_id = await _load_resource(resource_type, resource_id)
    await _require_visible(login_user, resource_type, app_id)
    stored = await load_app_guest_link(resource_type, app_id, strict=False)
    system_enabled, default_operator_id = await _system_default_operator()
    follow = stored.user_id is None
    operator_id = stored.user_id if stored.user_id is not None else default_operator_id
    default_in_tenant = False
    if default_operator_id is not None:
        default_in_tenant = await _operator_is_live(default_operator_id, tenant_id)
    operator_inactive = False
    operator_is_admin = False
    if operator_id is not None:
        operator_inactive = not await _operator_is_live(operator_id, tenant_id)
        operator_is_admin = await _is_forbidden_operator(operator_id, tenant_id)
    can_edit = await check_business_action(
        login_user,
        resource_type=resource_type,
        resource_id=app_id,
        action="share",
    )
    pinned = {item for item in (default_operator_id, stored.user_id, operator_id) if item}
    candidates = await _candidate_users(tenant_id, pinned_ids=pinned)
    return {
        "enabled": stored.enabled,
        "follow_system_default": follow,
        "user_id": stored.user_id,
        "operator_user_id": operator_id,
        "operator_user_name": await _load_user_name(operator_id),
        "default_operator_user_id": default_operator_id,
        "default_operator_user_name": await _load_user_name(default_operator_id),
        "default_operator_in_tenant": default_in_tenant,
        "system_guest_access": system_enabled,
        "can_edit": can_edit,
        "warnings": {
            "operator_is_admin": operator_is_admin,
            "default_not_in_tenant": follow and not default_in_tenant,
            "operator_inactive": operator_inactive,
        },
        "candidates": candidates,
    }


async def patch_guest_link_settings(
    login_user: UserPayload,
    resource_type: GuestResourceType,
    resource_id: str,
    req: GuestLinkPatchRequest,
) -> dict[str, Any]:
    _resource, tenant_id, resource_name, app_id = await _load_resource(resource_type, resource_id)
    await _require_share(login_user, resource_type, app_id)
    stored = await load_app_guest_link(resource_type, app_id, strict=False)
    enabled = stored.enabled if req.enabled is None else req.enabled
    if "user_id" in req.model_fields_set:
        new_user_id = req.user_id
        if new_user_id is not None and new_user_id != stored.user_id:
            await _validate_new_operator(new_user_id, tenant_id)
    else:
        new_user_id = stored.user_id
    await save_app_guest_link(
        resource_type,
        app_id,
        AppGuestLink(enabled=enabled, user_id=new_user_id, updated_by=login_user.user_id),
        updated_by=login_user.user_id,
    )
    logger.info(
        "guest_link.updated type={} id={} enabled={} user_id={} by={}",
        resource_type,
        app_id,
        enabled,
        new_user_id,
        login_user.user_id,
    )
    settings = await get_guest_link_settings(login_user, resource_type, app_id)
    settings["_audit"] = {
        "tenant_id": tenant_id,
        "object_name": resource_name,
        "enabled": enabled,
        "user_id": new_user_id,
        "object_id": app_id,
    }
    return settings


async def write_guest_link_audit(
    login_user: UserPayload,
    *,
    ip_address: str,
    resource_type: GuestResourceType,
    audit: dict,
) -> None:
    user_groups = await UserGroupDao.aget_user_group(login_user.user_id)
    object_type = ObjectType.WORK_FLOW if resource_type == "workflow" else ObjectType.ASSISTANT
    note = json.dumps(
        {"guest_link": True, "enabled": audit["enabled"], "user_id": audit["user_id"]},
        ensure_ascii=False,
    )
    await AuditLogDao.ainsert_audit_logs(
        [
            AuditLog(
                operator_id=login_user.user_id,
                operator_name=login_user.user_name,
                group_ids=[one.group_id for one in user_groups],
                system_id=SystemId.BUILD.value,
                event_type=EventType.UPDATE_BUILD.value,
                object_type=object_type.value,
                object_id=str(audit["object_id"]),
                object_name=audit["object_name"],
                note=note,
                ip_address=ip_address,
                tenant_id=audit["tenant_id"],
            )
        ]
    )


__all__ = [
    "AppGuestLink",
    "GuestLinkPatchRequest",
    "GuestResourceType",
    "delete_app_guest_link",
    "get_guest_link_settings",
    "guest_link_config_key",
    "load_app_guest_link",
    "normalize_app_id",
    "parse_app_guest_link",
    "patch_guest_link_settings",
    "save_app_guest_link",
    "write_guest_link_audit",
]
