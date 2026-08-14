"""Resource permission endpoints (T12b).

POST /api/v1/resources/{resource_type}/{resource_id}/authorize — Grant/revoke permissions.
GET  /api/v1/resources/{resource_type}/{resource_id}/permissions — List resource permissions.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass

from fastapi import APIRouter, Depends, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.permission import (
    PermissionDeniedError,
    PermissionInvalidResourceError,
    PermissionRelationModelNameExistsError,
    PermissionTupleWriteError,
)
from bisheng.common.schemas.api import resp_200
from bisheng.permission.domain.application_permission_template import (
    APPLICATION_PERMISSION_TEMPLATE,
)
from bisheng.permission.domain.channel_permission_template import (
    CHANNEL_PERMISSION_TEMPLATE,
)
from bisheng.permission.domain.knowledge_library_permission_template import (
    KNOWLEDGE_LIBRARY_PERMISSION_TEMPLATE,
)
from bisheng.permission.domain.knowledge_space_permission_template import (
    KNOWLEDGE_SPACE_PERMISSION_TEMPLATE,
)
from bisheng.permission.domain.schemas.permission_schema import (
    VALID_RESOURCE_TYPES,
    AuthorizeRequest,
    PermissionLevel,
    RelationModelCreateRequest,
    RelationModelItem,
    RelationModelUpdateRequest,
    ResourcePermissionItem,
)
from bisheng.permission.domain.services.grant_subject_query_service import (
    GrantSubjectQueryService,
)
from bisheng.permission.domain.services.relation_model_store import (
    binding_key_with_scope as _store_binding_key_with_scope,
)
from bisheng.permission.domain.services.relation_model_store import (
    build_bindings as _store_build_bindings,
)
from bisheng.permission.domain.services.relation_model_store import (
    build_relation_models as _store_build_relation_models,
)
from bisheng.permission.domain.services.relation_model_store import (
    default_relation_models as _store_default_relation_models,
)
from bisheng.permission.domain.services.relation_model_store import (
    get_bindings as _store_get_bindings,
)
from bisheng.permission.domain.services.relation_model_store import (
    get_relation_models as _store_get_relation_models,
)
from bisheng.permission.domain.services.relation_model_store import (
    migrate_legacy_knowledge_library_bindings as _store_migrate_legacy_bindings,
)
from bisheng.permission.domain.services.relation_model_store import (
    normalize_model_dict as _store_normalize_model_dict,
)
from bisheng.permission.domain.services.relation_model_store import (
    normalize_relation_model_name as _store_normalize_relation_model_name,
)
from bisheng.permission.domain.services.relation_model_store import (
    roster_cache_tenant_id as _store_roster_cache_tenant_id,
)
from bisheng.permission.domain.services.relation_model_store import (
    save_bindings as _store_save_bindings,
)
from bisheng.permission.domain.services.relation_model_store import (
    save_relation_models as _store_save_relation_models,
)
from bisheng.permission.domain.services.resource_user_invite_application_service import (
    build_runtime_resource_user_invite_application_service,
)
from bisheng.permission.domain.tool_permission_template import (
    TOOL_PERMISSION_TEMPLATE,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Strong references to in-flight fire-and-forget notification tasks so the event
# loop does not garbage-collect them mid-execution (asyncio caveat).
_pending_notification_tasks: set = set()


def _dispatch_authorize_notifications_in_background(
    *, context, operator_user_id: int, operator_user_name: str | None
) -> None:
    """Fire-and-forget the post-authorize permission notification.

    The notification computes who gained/lost access (per-member OpenFGA checks)
    and sends inbox messages. None of it is part of the authorize business
    result, so it must not block or fail the main flow — exceptions are logged
    and swallowed. The ``context`` already captured the pre-write snapshot
    synchronously, so backgrounding only the *dispatch* keeps before/after
    correctness intact. (The per-member check cost is a separate, later
    optimization.)
    """
    if context is None:
        return

    from bisheng.permission.domain.services.resource_permission_notification_service import (
        ResourcePermissionNotificationService,
    )

    async def _runner() -> None:
        try:
            await ResourcePermissionNotificationService.dispatch_after_authorize(
                context=context,
                operator_user_id=operator_user_id,
                operator_user_name=operator_user_name,
            )
        except Exception:
            logger.exception("post-authorize notification dispatch failed (backgrounded)")

    # create_task snapshots the current contextvars (tenant, request scope), so
    # the dispatch keeps the caller's tenant context even after the response ends.
    task = asyncio.create_task(_runner())
    _pending_notification_tasks.add(task)
    task.add_done_callback(_pending_notification_tasks.discard)


# Grantable role relations mapped to their required minimum level
_GRANT_RELATIONS = {"owner": "owner", "manager": "can_manage", "editor": "can_edit", "viewer": "can_read"}
_GRANT_TIER_VALUES = frozenset({"owner", "manager", "usage"})
_MANAGE_PERMISSION_BY_RESOURCE_TIER = {
    "workflow": {
        "owner": "manage_app_owner",
        "manager": "manage_app_manager",
        "usage": "manage_app_viewer",
    },
    "assistant": {
        "owner": "manage_app_owner",
        "manager": "manage_app_manager",
        "usage": "manage_app_viewer",
    },
    "tool": {
        "owner": "manage_tool_owner",
        "manager": "manage_tool_manager",
        "usage": "manage_tool_viewer",
    },
    "knowledge_library": {
        "owner": "manage_kb_owner",
        "manager": "manage_kb_manager",
        "usage": "manage_kb_viewer",
    },
    "channel": {
        "owner": "manage_channel_owner",
        "manager": "manage_channel_manager",
        "usage": "manage_channel_user",
    },
}
_MANAGE_PERMISSION_BY_RESOURCE = {
    "knowledge_space": "manage_space_relation",
    "folder": "manage_folder_relation",
    "knowledge_file": "manage_file_relation",
}
_PERMISSION_LEVEL_TO_RELATION = {
    PermissionLevel.owner.value: "owner",
    PermissionLevel.can_manage.value: "manager",
    PermissionLevel.can_edit.value: "editor",
    PermissionLevel.can_read.value: "viewer",
}
_PERMISSION_TEMPLATES = (
    KNOWLEDGE_SPACE_PERMISSION_TEMPLATE,
    APPLICATION_PERMISSION_TEMPLATE,
    KNOWLEDGE_LIBRARY_PERMISSION_TEMPLATE,
    TOOL_PERMISSION_TEMPLATE,
    CHANNEL_PERMISSION_TEMPLATE,
)
_RELATION_MODEL_NAME_PREFIX_PAIRS = tuple(
    (template.get("title") or "", item.get("label") or "")
    for template in _PERMISSION_TEMPLATES
    for column in template.get("columns", [])
    for item in column.get("items", [])
)


def _infer_grant_tier_from_relation(relation: str) -> str:
    if relation == "owner":
        return "owner"
    if relation == "manager":
        return "manager"
    return "usage"


def _validate_tier_relation(grant_tier: str, relation: str) -> bool:
    if grant_tier == "owner":
        return relation == "owner"
    if grant_tier == "manager":
        return relation == "manager"
    if grant_tier == "usage":
        return relation in ("editor", "viewer")
    return False


def _is_invalid_owner_subject(subject_type: str | None, relation: str | None) -> bool:
    return relation == "owner" and subject_type != "user"


def _normalize_relation_model_name(name: str | None) -> str:
    return _store_normalize_relation_model_name(name)


def _relation_model_name_exists(models: list[dict], name: str | None, exclude_model_id: str | None = None) -> bool:
    normalized_name = _normalize_relation_model_name(name)
    if not normalized_name:
        return False
    return any(
        m.get("id") != exclude_model_id and _normalize_relation_model_name(m.get("name")) == normalized_name
        for m in models
    )


def _normalize_model_dict(m: dict) -> dict:
    return _store_normalize_model_dict(m)


def _default_relation_models() -> list[dict]:
    return _store_default_relation_models()


def _roster_cache_tenant_id() -> int:
    return _store_roster_cache_tenant_id()


async def _get_relation_models() -> list[dict]:
    """只读; 若库中无记录则初始化默认四条, 禁止每次读取都覆盖已保存的自定义模型。

    F040 (E): served from a process-local cache keyed by the config row's
    ``update_time``; on a version match the parse is skipped. Version unavailable
    (``None``, e.g. first init) → rebuild + no caching (fail-safe)."""
    return await _store_get_relation_models()


async def _build_relation_models() -> list[dict]:
    return await _store_build_relation_models()


async def _save_relation_models(models: list[dict]) -> None:
    await _store_save_relation_models(models)


async def _get_bindings() -> list[dict]:
    """只读; 禁止每次读取都把绑定表写回空数组。

    F040 (E): served from a process-local cache keyed by the config row's
    ``update_time`` — this collapses the repeated DB read + ``json.loads`` + legacy
    scan that every ReBAC read (esp. ``/children`` deep-expansion) otherwise pays.
    Version unavailable (``None``) → rebuild + no caching (fail-safe). The list is
    treated as read-only by all callers, matching the existing per-request memo."""
    return await _store_get_bindings()


async def _build_bindings() -> list[dict]:
    return await _store_build_bindings()


async def _save_bindings(bindings: list[dict]) -> None:
    await _store_save_bindings(bindings)


async def _migrate_legacy_knowledge_library_bindings(bindings: list[dict]) -> list[dict]:
    return await _store_migrate_legacy_bindings(bindings)


def _normalize_binding_include_children(subject_type: str, include_children) -> bool | None:
    if subject_type != "department":
        return None
    return bool(include_children)


def _binding_key_with_scope(
    resource_type: str,
    resource_id: str,
    subject_type: str,
    subject_id: int,
    relation: str,
    include_children,
) -> str:
    return _store_binding_key_with_scope(
        resource_type,
        resource_id,
        subject_type,
        subject_id,
        relation,
        include_children,
    )


def _binding_key(resource_type: str, resource_id: str, subject_type: str, subject_id: int, relation: str) -> str:
    return _binding_key_with_scope(
        resource_type,
        resource_id,
        subject_type,
        subject_id,
        relation,
        None,
    )


def _legacy_binding_key(
    resource_type: str,
    resource_id: str,
    subject_type: str,
    subject_id: int,
    relation: str,
) -> str:
    return f"{resource_type}:{resource_id}:{subject_type}:{subject_id}:{relation}"


def _binding_lookup_keys(
    resource_type: str,
    resource_id: str,
    subject_type: str,
    subject_id: int,
    relation: str,
    include_children,
) -> list[str]:
    return [
        _binding_key_with_scope(
            resource_type,
            resource_id,
            subject_type,
            subject_id,
            relation,
            include_children,
        ),
        _legacy_binding_key(
            resource_type,
            resource_id,
            subject_type,
            subject_id,
            relation,
        ),
    ]


def _binding_from_map(
    bindings_map: dict,
    resource_type: str,
    resource_id: str,
    subject_type: str,
    subject_id: int,
    relation: str,
    include_children,
):
    for key in _binding_lookup_keys(
        resource_type,
        resource_id,
        subject_type,
        subject_id,
        relation,
        include_children,
    ):
        binding = bindings_map.get(key)
        if binding:
            return binding
    return None


async def _apply_binding_metadata_to_permissions(
    permissions: list[ResourcePermissionItem],
    bindings: list[dict],
    model_map: dict,
) -> list[ResourcePermissionItem]:
    """Overlay persisted UI binding metadata onto raw FGA tuple rows.

    Department grants with include_children=True are written as one tuple per
    subtree department. The permission list should expose those concrete rows
    while copying the original parent binding's relation-model metadata to the
    generated child department rows.
    """
    if not bindings:
        return permissions

    item_map = {(p.subject_type, int(p.subject_id), p.relation): p for p in permissions}
    bound_keys = {
        (b.get("subject_type"), int(b.get("subject_id")), b.get("relation"))
        for b in bindings
        if b.get("subject_id") is not None
    }

    for binding in bindings:
        subject_type = binding.get("subject_type")
        if binding.get("subject_id") is None:
            continue
        subject_id = int(binding.get("subject_id"))
        relation = binding.get("relation")
        key = (subject_type, subject_id, relation)
        item = item_map.get(key)
        if item is None:
            item = ResourcePermissionItem(
                subject_type=subject_type,
                subject_id=subject_id,
                subject_name=None,
                relation=relation,
            )
            item_map[key] = item

        binding_include_children = binding.get("include_children")
        binding_model_id = binding.get("model_id")
        binding_model_name = model_map.get(binding_model_id, {}).get("name")
        item.include_children = binding_include_children
        item.model_id = binding_model_id
        item.model_name = binding_model_name

        if subject_type == "department" and binding_include_children:
            try:
                from bisheng.database.models.department import DepartmentDao

                dept = await DepartmentDao.aget_by_id(subject_id)
                subtree_ids = await DepartmentDao.aget_subtree_ids(dept.path) if dept else [subject_id]
            except Exception as e:
                logger.warning("Failed to expand department permission subtree metadata: %s", e)
                subtree_ids = [subject_id]

            for dept_id in subtree_ids:
                child_key = ("department", int(dept_id), relation)
                if child_key == key or child_key in bound_keys:
                    continue
                child_item = item_map.get(child_key)
                if child_item is None:
                    continue
                child_item.include_children = False
                child_item.model_id = binding_model_id
                child_item.model_name = binding_model_name

    return list(item_map.values())


def _tuple_signature(item) -> tuple:
    return (
        getattr(item, "subject_type", None),
        getattr(item, "subject_id", None),
        getattr(item, "relation", None),
        _normalize_binding_include_children(
            getattr(item, "subject_type", None),
            getattr(item, "include_children", None),
        ),
    )


def _management_permission_ids(resource_type: str) -> set[str]:
    direct = _MANAGE_PERMISSION_BY_RESOURCE.get(resource_type)
    if direct:
        return {direct}
    tier_map = _MANAGE_PERMISSION_BY_RESOURCE_TIER.get(resource_type)
    if not tier_map:
        return set()
    return set(tier_map.values())


def _lineage_binding_can_override(resource_type: str) -> bool:
    return resource_type in {"folder", "knowledge_file"}


@dataclass(frozen=True)
class _DepartmentSpaceScope:
    """Authorizable scope of a department knowledge space (F033, design B1).

    ``subtree_dept_ids`` = active departments under the bound department
    (inclusive of the bound department itself). Empty when the bound department
    is archived or missing, which degrades to "no authorizable target".
    """

    department_id: int
    department_path: str | None
    subtree_dept_ids: frozenset[int]


async def _resolve_department_space_scope(
    resource_type: str,
    resource_id: str,
    *,
    load_subtree_ids: bool = True,
) -> "_DepartmentSpaceScope | None":
    """Single judgment source for "is this a department knowledge space".

    Returns the scope when ``resource_type`` is ``knowledge_space`` and the
    space is bound to a department; otherwise ``None``. ``None`` is how the
    grant-subject listing and ``authorize`` call sites fall back to the
    unchanged, tenant-wide behavior for normal spaces and other resources.

    Must not trust any client-supplied flag — judgment is derived purely from
    the ``DepartmentKnowledgeSpace`` binding so direct API calls cannot bypass
    the scope restriction.
    """
    if resource_type != "knowledge_space":
        return None

    from bisheng.database.models.department import DepartmentDao
    from bisheng.knowledge.domain.models.department_knowledge_space import (
        DepartmentKnowledgeSpaceDao,
    )

    try:
        space_id = int(resource_id)
    except (TypeError, ValueError):
        return None

    binding = await DepartmentKnowledgeSpaceDao.aget_by_space_id(space_id)
    if binding is None:
        return None

    department_id = int(binding.department_id)
    dept = await DepartmentDao.aget_by_id(department_id)
    if dept is None or getattr(dept, "status", "active") != "active":
        return _DepartmentSpaceScope(
            department_id=department_id,
            department_path=None,
            subtree_dept_ids=frozenset(),
        )

    department_path = getattr(dept, "path", None)
    subtree_ids = await DepartmentDao.aget_subtree_ids(department_path) if load_subtree_ids and department_path else []
    return _DepartmentSpaceScope(
        department_id=department_id,
        department_path=department_path,
        subtree_dept_ids=frozenset(int(i) for i in subtree_ids),
    )


async def _subtree_user_ids(restrict_dept_ids: frozenset[int], candidate_user_ids: set[int]) -> set[int]:
    """Return the subset of ``candidate_user_ids`` that belong to any department
    in ``restrict_dept_ids`` (membership in the bound subtree)."""
    if not restrict_dept_ids or not candidate_user_ids:
        return set()

    from bisheng.database.models.department import UserDepartmentDao

    rows = await UserDepartmentDao.aget_by_user_ids(list(candidate_user_ids))
    return {
        int(row.user_id)
        for row in rows
        if getattr(row, "department_id", None) is not None and int(row.department_id) in restrict_dept_ids
    }


async def _validate_department_space_grants(scope: _DepartmentSpaceScope, grants):
    """F033, design B6: reject grants that violate a department space's scope.

    Applies to ALL callers including super_admin (the caller invokes this
    outside the ``is_admin()`` management-check bypass). Revokes are not
    validated so historical user-group grants remain removable. Returns a
    response on denial, or ``None`` when every grant is in scope.
    """
    if not grants:
        return None

    candidate_user_ids: set[int] = set()
    for grant in grants:
        if grant.subject_type == "user_group":
            return PermissionDeniedError.return_resp("部门知识空间不支持按用户组授权")
        if grant.subject_type == "department":
            if int(grant.subject_id) not in scope.subtree_dept_ids:
                return PermissionDeniedError.return_resp("只能授权给本部门及子部门")
        elif grant.subject_type == "user":
            candidate_user_ids.add(int(grant.subject_id))

    if candidate_user_ids:
        allowed = await _subtree_user_ids(scope.subtree_dept_ids, candidate_user_ids)
        if not candidate_user_ids.issubset(allowed):
            return PermissionDeniedError.return_resp("只能授权给本部门及子部门的成员")
    return None


async def _has_resource_permission_management_access(
    *,
    resource_type: str,
    resource_id: str,
    login_user: UserPayload,
    use_binding_index: bool = False,
) -> bool:
    from bisheng.permission.domain.services.permission_service import PermissionService

    management_permission_ids = _management_permission_ids(resource_type)
    if management_permission_ids:
        from bisheng.permission.domain.services.fine_grained_permission_service import FineGrainedPermissionService

        if use_binding_index and resource_type in {"knowledge_space", "channel"}:
            effective_permission_ids = (
                await FineGrainedPermissionService.get_effective_permission_ids_from_verified_bindings_async(
                    login_user,
                    resource_type,
                    resource_id,
                )
            )
        else:
            effective_permission_ids = await FineGrainedPermissionService.get_effective_permission_ids_async(
                login_user,
                resource_type,
                resource_id,
                nearest_binding_wins=_lineage_binding_can_override(resource_type),
            )
        return bool(management_permission_ids & effective_permission_ids)

    return await PermissionService.check(
        user_id=login_user.user_id,
        relation="can_edit",
        object_type=resource_type,
        object_id=resource_id,
        login_user=login_user,
    )


def _attach_default_model_metadata(item: ResourcePermissionItem, model_map: dict) -> None:
    model = model_map.get(item.relation)
    if not model:
        return
    item.model_id = model.get("id") or item.relation
    item.model_name = model.get("name")


def _permission_subject_key(item: ResourcePermissionItem) -> tuple[str, int, str]:
    return item.subject_type, int(item.subject_id), item.relation


async def _list_knowledge_space_grant_users(
    *,
    tenant_id: int,
    keyword: str,
    page: int,
    page_size: int,
    restrict_dept_path: str | None = None,
) -> list[dict]:
    return await GrantSubjectQueryService().list_users(
        tenant_id=tenant_id,
        keyword=keyword,
        page=page,
        page_size=page_size,
        restrict_dept_path=restrict_dept_path,
    )


async def _grant_departments_children(
    *, tenant_id: int, parent_id: int | None = None, restrict_root_path: str | None = None
) -> list[dict]:
    return await GrantSubjectQueryService().list_departments_children(
        tenant_id=tenant_id, parent_id=parent_id, restrict_root_path=restrict_root_path
    )


async def _grant_departments_search(
    *, tenant_id: int, keyword: str, limit: int = 50, restrict_root_path: str | None = None
) -> dict:
    return await GrantSubjectQueryService().search_departments(
        tenant_id=tenant_id, keyword=keyword, limit=limit, restrict_root_path=restrict_root_path
    )


async def _grant_departments_path_tree(*, tenant_id: int, dept_id: int, restrict_root_path: str | None = None) -> dict:
    return await GrantSubjectQueryService().get_departments_path_tree(
        tenant_id=tenant_id, dept_id=dept_id, restrict_root_path=restrict_root_path
    )


async def _list_knowledge_space_grant_user_groups(
    *, tenant_id: int, keyword: str, login_user: UserPayload
) -> list[dict]:
    return await GrantSubjectQueryService().list_user_groups(
        tenant_id=tenant_id, keyword=keyword, login_user=login_user
    )


async def _resolve_grant_subject_tenant_id(
    *,
    resource_type: str,
    resource_id: str,
    login_user: UserPayload,
) -> int | None:
    from bisheng.core.context.tenant import get_current_tenant_id
    from bisheng.database.models.tenant import TenantDao
    from bisheng.permission.domain.services.permission_service import PermissionService

    tenant_id = await PermissionService._resolve_resource_tenant(resource_type, resource_id)
    if tenant_id is None:
        tenant_id = get_current_tenant_id() or getattr(login_user, "tenant_id", None)
    if tenant_id is None:
        return None

    tenant = await TenantDao.aget_by_id(int(tenant_id))
    if tenant is None or getattr(tenant, "status", None) != "active":
        return None
    return int(tenant_id)


async def _can_remove_owner_relations(
    *,
    resource_type: str,
    resource_id: str,
    revokes: list,
    grants: list | None = None,
) -> bool:
    """Reject owner revokes that would leave the resource with no owner (INV-2).

    Owner and creator are decoupled, so any owner (including the creator's) may be
    revoked or downgraded as long as at least one owner survives. Owner grants in
    the SAME request count toward the survivors, so a same-request ownership
    transfer (revoke old owner + grant new owner) is allowed even when it targets
    the only existing owner. Removing the last remaining owner is refused so the
    resource is never orphaned.
    """
    from bisheng.permission.domain.services.permission_service import PermissionService

    permissions = await PermissionService.get_resource_permissions(
        object_type=resource_type,
        object_id=resource_id,
    )
    owner_signatures = {_tuple_signature(item) for item in permissions if getattr(item, "relation", None) == "owner"}
    revoke_signatures = {_tuple_signature(item) for item in revokes if getattr(item, "relation", None) == "owner"}
    grant_owner_signatures = {
        _tuple_signature(item) for item in (grants or []) if getattr(item, "relation", None) == "owner"
    }
    remaining_owners = (owner_signatures - revoke_signatures) | grant_owner_signatures
    return len(remaining_owners) > 0


async def _add_implicit_permission_entries(
    *,
    resource_type: str,
    resource_id: str,
    permissions: list[ResourcePermissionItem],
    model_map: dict,
    login_user: UserPayload,
) -> list[ResourcePermissionItem]:
    """Show implicit caller access sources in the permission dialog.

    Some department knowledge spaces remain accessible to the current caller
    through implicit permission shortcuts even when no explicit OpenFGA tuple
    exists to list. The authorization checks already honor those paths; this
    keeps the management dialog aligned with the effective permission model
    without synthesizing department viewer rows that look like stored grants.
    """
    out = list(permissions)
    if resource_type != "knowledge_space" or not str(resource_id).isdigit():
        return out

    try:
        from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpaceDao

        binding = await DepartmentKnowledgeSpaceDao.aget_by_space_id(int(resource_id))
    except Exception as e:
        logger.debug("Could not load department-space binding for %s: %s", resource_id, e)
        return out
    if binding is None:
        return out

    user_has_list_entry = any(
        item.subject_type == "user" and int(item.subject_id) == int(login_user.user_id) for item in out
    )
    if not login_user.is_admin() and not user_has_list_entry:
        from bisheng.permission.domain.services.permission_service import PermissionService

        implicit_level = await PermissionService.get_implicit_permission_level(
            user_id=login_user.user_id,
            object_type=resource_type,
            object_id=resource_id,
            login_user=login_user,
        )
        relation = _PERMISSION_LEVEL_TO_RELATION.get(implicit_level or "")
        if relation:
            user_name = getattr(login_user, "user_name", None)
            if not user_name:
                try:
                    from bisheng.user.domain.models.user import UserDao

                    user = await UserDao.aget_user(login_user.user_id)
                    user_name = getattr(user, "user_name", None) if user else None
                except Exception as e:
                    logger.debug("Could not resolve user %s for permission list: %s", login_user.user_id, e)
            item = ResourcePermissionItem(
                subject_type="user",
                subject_id=login_user.user_id,
                subject_name=user_name,
                relation=relation,
            )
            _attach_default_model_metadata(item, model_map)
            out.append(item)

    return out


async def _add_creator_owner_entry(
    *,
    resource_type: str,
    resource_id: str,
    permissions: list[ResourcePermissionItem],
    model_map: dict,
) -> list[ResourcePermissionItem]:
    """Surface the DB creator as owner, with two regimes by resource type.

    knowledge_space creators are PERMANENT, non-removable owners: ownership is
    backed by the SpaceChannelMember CREATOR row + Knowledge.user_id (which the
    "我创建的" list and file read/write/delete all honor), independent of any FGA
    owner tuple. So the creator must ALWAYS appear as owner and carry is_creator so
    the UI locks the row (mirrors the channel creator).

    Other resource types have no such membership authority — there owner and
    creator are decoupled, and the creator is only a last-resort ownerless safety
    net (INV-2), surfaced only when no owner tuple exists at all. Mirrors the
    check-side fallback in PermissionService._resource_has_active_owner.
    """
    from bisheng.permission.domain.services.permission_service import PermissionService

    creator_id = await PermissionService._get_resource_creator(resource_type, resource_id)
    if creator_id is None:
        return permissions

    creator_id = int(creator_id)
    creator_is_permanent = resource_type == "knowledge_space"

    existing_creator_owner = next(
        (
            item
            for item in permissions
            if item.subject_type == "user" and int(item.subject_id) == creator_id and item.relation == "owner"
        ),
        None,
    )
    if existing_creator_owner is not None:
        # Creator already listed via an owner tuple. Flag it for the permanent
        # regime so the UI locks the row; otherwise leave the list unchanged.
        if creator_is_permanent:
            existing_creator_owner.is_creator = True
        return permissions

    # Creator has no owner tuple. Decoupled types only backfill when the resource
    # would otherwise be ownerless; the permanent (knowledge_space) type always
    # backfills so the creator stays visible as owner even alongside other owners.
    has_any_owner = any(item.subject_type == "user" and item.relation == "owner" for item in permissions)
    if has_any_owner and not creator_is_permanent:
        return permissions

    user_name = None
    try:
        from bisheng.user.domain.models.user import UserDao

        user = await UserDao.aget_user(creator_id)
        user_name = getattr(user, "user_name", None) if user else None
    except Exception as e:
        logger.debug("Could not resolve creator %s for permission list: %s", creator_id, e)

    item = ResourcePermissionItem(
        subject_type="user",
        subject_id=creator_id,
        subject_name=user_name,
        relation="owner",
        is_creator=creator_is_permanent,
    )
    _attach_default_model_metadata(item, model_map)
    return [*permissions, item]


@router.post("/resources/{resource_type}/{resource_id}/authorize")
async def authorize_resource(
    resource_type: str,
    resource_id: str,
    request: AuthorizeRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Grant or revoke permissions on a resource.

    调用方在资源上的档位需覆盖本次操作涉及的「关系模型授权级别」
    (所有者级 / 管理级 / 使用级), 与 PRD 管理应用所有者/管理者/使用者对齐。
    """
    from bisheng.permission.domain.services.resource_authorization_service import (
        ResourceAuthorizationService,
    )

    service = ResourceAuthorizationService(
        get_relation_models=_get_relation_models,
        get_bindings=_get_bindings,
        save_bindings=_save_bindings,
        dispatch_notifications=_dispatch_authorize_notifications_in_background,
    )
    try:
        result = await service.authorize(resource_type, resource_id, request, login_user)
    except PermissionTupleWriteError as error:
        return error.return_resp_instance()
    except BaseErrorCode as error:
        return error.__class__.return_resp(msg=error.message)
    return resp_200(result)


@router.get("/creation-grant-subjects")
async def get_creation_grant_subjects(
    resource_type: str,
    subject_type: str,
    operation: str,
    keyword: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(1000, ge=1, le=2000),
    parent_id: int | None = Query(None),
    department_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Return current-tenant grant subjects for a resource being created."""
    try:
        data = await GrantSubjectQueryService().query_creation_subjects(
            resource_type=resource_type,
            subject_type=subject_type,
            operation=operation,
            login_user=login_user,
            keyword=keyword,
            page=page,
            page_size=page_size,
            parent_id=parent_id,
            department_id=department_id,
            limit=limit,
        )
    except BaseErrorCode as error:
        return error.return_resp_instance()
    return resp_200(data)


@router.get("/resources/{resource_type}/{resource_id}/grant-subjects/users")
async def get_grant_subject_users(
    resource_type: str,
    resource_id: str,
    keyword: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(1000, ge=1, le=2000),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        data = await GrantSubjectQueryService().query_resource_users(
            resource_type=resource_type,
            resource_id=resource_id,
            login_user=login_user,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
    except BaseErrorCode as error:
        return error.__class__.return_resp(msg=error.message)
    return resp_200(data)


# F038/T012: the eager full-tree ``GET .../grant-subjects/departments`` was
# removed — the grant picker uses the lazy ``…/departments/{children,search,
# {id}/path-tree}`` endpoints below instead, so a large org tree never loads at
# once. ``_resolve_grant_subject_tenant_id`` / ``_resolve_department_space_scope``
# are retained; they back the lazy endpoints' shared preamble.


# F038: empty payloads for the lazy grant-subject department endpoints, by shape.
_EMPTY_DEPT_LAYER: list = []
_EMPTY_DEPT_TREE = {"roots": [], "total_matches": 0, "truncated": False}


async def _grant_dept_lazy_preamble(resource_type: str, resource_id: str, login_user):
    """Shared gate for the lazy grant-subject department endpoints.

    Returns ``(error_resp, tenant_id, restrict_root_path, empty)``:
    - ``error_resp`` set → return it immediately (invalid resource / denied);
    - ``empty=True`` → no authorizable target (no tenant, or a department space
      whose bound department is archived/missing) → caller returns the empty shape;
    - otherwise ``restrict_root_path`` is the F033 bound-department path (or
      ``None`` for normal spaces / channels — the same scope as the legacy list).

    F033 is threaded as a PATH (not the id set) so the lazy queries stay
    ``path LIKE`` and avoid DM8's large ``.in_()`` trap (design §5 #1).
    """
    if resource_type not in VALID_RESOURCE_TYPES:
        return PermissionInvalidResourceError.return_resp(), None, None, False
    if not await _has_resource_permission_management_access(
        resource_type=resource_type,
        resource_id=resource_id,
        login_user=login_user,
    ):
        return PermissionDeniedError.return_resp(), None, None, False
    tenant_id = await _resolve_grant_subject_tenant_id(
        resource_type=resource_type,
        resource_id=resource_id,
        login_user=login_user,
    )
    if tenant_id is None:
        return None, None, None, True
    scope = await _resolve_department_space_scope(resource_type, resource_id, load_subtree_ids=False)
    restrict_root_path = None
    if scope is not None:
        if not scope.department_path:
            return None, tenant_id, None, True  # bound dept archived/missing → no target
        restrict_root_path = scope.department_path
    return None, tenant_id, restrict_root_path, False


@router.get("/resources/{resource_type}/{resource_id}/grant-subjects/departments/children")
async def get_grant_subject_departments_children(
    resource_type: str,
    resource_id: str,
    parent_id: int | None = Query(None),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    # GrantSubjectQueryService preserves the existing lazy department response,
    # including each node's member_count field.
    try:
        data = await GrantSubjectQueryService().query_resource_departments(
            resource_type=resource_type,
            resource_id=resource_id,
            login_user=login_user,
            operation="children",
            parent_id=parent_id,
        )
    except BaseErrorCode as error:
        return error.__class__.return_resp(msg=error.message)
    return resp_200(data)


@router.get("/resources/{resource_type}/{resource_id}/grant-subjects/departments/search")
async def search_grant_subject_departments(
    resource_type: str,
    resource_id: str,
    keyword: str = "",
    limit: int = Query(50, ge=1, le=200),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        data = await GrantSubjectQueryService().query_resource_departments(
            resource_type=resource_type,
            resource_id=resource_id,
            login_user=login_user,
            operation="search",
            keyword=keyword,
            limit=limit,
        )
    except BaseErrorCode as error:
        return error.__class__.return_resp(msg=error.message)
    return resp_200(data)


@router.get("/resources/{resource_type}/{resource_id}/grant-subjects/departments/{dept_id:int}/path-tree")
async def get_grant_subject_departments_path_tree(
    resource_type: str,
    resource_id: str,
    dept_id: int,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        data = await GrantSubjectQueryService().query_resource_departments(
            resource_type=resource_type,
            resource_id=resource_id,
            login_user=login_user,
            operation="path_tree",
            department_id=dept_id,
        )
    except BaseErrorCode as error:
        return error.__class__.return_resp(msg=error.message)
    return resp_200(data)


@router.get("/resources/{resource_type}/{resource_id}/grant-subjects/user-groups")
async def get_grant_subject_user_groups(
    resource_type: str,
    resource_id: str,
    keyword: str = "",
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    try:
        data = await GrantSubjectQueryService().query_resource_user_groups(
            resource_type=resource_type,
            resource_id=resource_id,
            login_user=login_user,
            keyword=keyword,
        )
    except BaseErrorCode as error:
        return error.__class__.return_resp(msg=error.message)
    return resp_200(data)


@router.get("/resources/{resource_type}/{resource_id}/permissions")
async def get_resource_permissions(
    resource_type: str,
    resource_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """List all permission entries for a resource.

    Caller must have at least can_edit on the resource (与使用级授权一致)。
    """
    if resource_type not in VALID_RESOURCE_TYPES:
        return PermissionInvalidResourceError.return_resp()

    from bisheng.permission.domain.services.permission_service import PermissionService

    allowed = await _has_resource_permission_management_access(
        resource_type=resource_type,
        resource_id=resource_id,
        login_user=login_user,
        use_binding_index=resource_type == "knowledge_space",
    )
    if not allowed:
        return PermissionDeniedError.return_resp()

    models = await _get_relation_models()
    model_map = {m["id"]: _normalize_model_dict(m) for m in models}
    bindings = [
        b
        for b in await _get_bindings()
        if b.get("resource_type") == resource_type and str(b.get("resource_id")) == str(resource_id)
    ]
    binding_map = {b.get("key"): b for b in bindings if b.get("key")}
    if resource_type == "knowledge_space":
        permissions = await PermissionService.get_resource_permissions_from_bindings(
            bindings,
            model_map,
        )
    else:
        permissions = await PermissionService.get_resource_permissions(
            object_type=resource_type,
            object_id=resource_id,
        )
        visible_permissions = []
        for p in permissions:
            matched = _binding_from_map(
                binding_map,
                resource_type,
                str(resource_id),
                p.subject_type,
                p.subject_id,
                p.relation,
                getattr(p, "include_children", None),
            )
            if matched:
                p.model_id = matched.get("model_id")
                p.model_name = model_map.get(p.model_id, {}).get("name")
                p.include_children = matched.get("include_children")

            visible_permissions.append(p)
        permissions = visible_permissions
        permissions = await _apply_binding_metadata_to_permissions(permissions, bindings, model_map)
    permissions = await _add_creator_owner_entry(
        resource_type=resource_type,
        resource_id=resource_id,
        permissions=permissions,
        model_map=model_map,
    )
    permissions = await _add_implicit_permission_entries(
        resource_type=resource_type,
        resource_id=resource_id,
        permissions=permissions,
        model_map=model_map,
        login_user=login_user,
    )
    from bisheng.permission.domain.services.resource_authorization_service import (
        ResourceAuthorizationService,
    )

    resource_tenant_id = await PermissionService._resolve_resource_tenant(resource_type, resource_id)
    if resource_tenant_id is None:
        from bisheng.core.context.tenant import get_current_tenant_id

        resource_tenant_id = get_current_tenant_id() or login_user.tenant_id
    permissions = await ResourceAuthorizationService().list_pending_permissions(
        tenant_id=int(resource_tenant_id),
        resource_type=resource_type,
        resource_id=resource_id,
        active_permissions=permissions,
    )
    return resp_200(permissions)


@router.post("/resource-user-invites/{request_id}/retry")
async def retry_resource_user_invite(
    request_id: int,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Re-dispatch an approved F045 request whose Permission execution failed."""

    service = build_runtime_resource_user_invite_application_service()
    result = await service.retry_failed_invite(
        tenant_id=int(login_user.tenant_id),
        request_id=request_id,
    )
    return resp_200(result)


@router.get("/relation-models")
async def get_relation_models(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    models = [RelationModelItem(**_normalize_model_dict(m)) for m in await _get_relation_models()]
    return resp_200(models)


@router.get("/relation-models/grantable")
async def get_grantable_relation_models(
    object_type: str,
    object_id: str | None = None,
    creation: bool = False,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """返回当前用户在指定资源上「有权用于授权」的关系模型子集。"""
    if object_type not in VALID_RESOURCE_TYPES:
        return PermissionInvalidResourceError.return_resp()

    from bisheng.permission.domain.services.resource_authorization_service import (
        ResourceAuthorizationService,
    )

    authorization_service = ResourceAuthorizationService(
        get_relation_models=_get_relation_models,
    )
    relation_models = None
    management_permission_ids = _management_permission_ids(object_type)
    if creation:
        try:
            query_service = GrantSubjectQueryService(
                resource_authorization_service=authorization_service,
            )
            await query_service.resolve_creation_tenant_id(login_user)
        except BaseErrorCode as error:
            return error.__class__.return_resp(msg=error.message)
        try:
            relation_models = await authorization_service.get_relation_models()
            caller_permission_ids = await query_service.require_creation_management_access(
                object_type,
                relation_models=relation_models,
            )
        except PermissionDeniedError:
            return resp_200([])
        except BaseErrorCode as error:
            return error.__class__.return_resp(msg=error.message)
    elif object_id is None:
        return PermissionInvalidResourceError.return_resp()
    elif login_user.is_admin():
        raw = [_normalize_model_dict(m) for m in await _get_relation_models()]
        return resp_200([RelationModelItem(**m) for m in raw])
    else:
        caller_permission_ids = set()
    if not creation and management_permission_ids:
        from bisheng.permission.domain.services.fine_grained_permission_service import FineGrainedPermissionService

        caller_permission_ids = await FineGrainedPermissionService.get_effective_permission_ids_async(
            login_user,
            object_type,
            object_id,
            nearest_binding_wins=_lineage_binding_can_override(object_type),
        )
    if management_permission_ids and not (management_permission_ids & caller_permission_ids):
        return resp_200([])

    grantable_models = await authorization_service.grantable_models_for_permissions(
        object_type,
        set(caller_permission_ids),
        relation_models=relation_models,
    )
    out = [RelationModelItem(**_normalize_model_dict(model)) for model in grantable_models]
    return resp_200(out)


@router.post("/relation-models")
async def create_relation_model(
    request: RelationModelCreateRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    if not login_user.is_admin():
        return PermissionDeniedError.return_resp()
    if request.relation not in _GRANT_RELATIONS:
        return PermissionDeniedError.return_resp()
    models = await _get_relation_models()
    if _relation_model_name_exists(models, request.name):
        return PermissionRelationModelNameExistsError.return_resp()
    model_id = f"custom_{uuid.uuid4().hex[:8]}"
    models.append(
        {
            "id": model_id,
            "name": _normalize_relation_model_name(request.name),
            "relation": request.relation,
            "grant_tier": _infer_grant_tier_from_relation(request.relation),
            "permissions": request.permissions or [],
            "permissions_explicit": True,
            "is_system": False,
        }
    )
    await _save_relation_models(models)
    return resp_200({"id": model_id})


@router.put("/relation-models/{model_id}")
async def update_relation_model(
    model_id: str,
    request: RelationModelUpdateRequest,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    if not login_user.is_admin():
        return PermissionDeniedError.return_resp()
    models = await _get_relation_models()
    if request.name is not None and _relation_model_name_exists(models, request.name, exclude_model_id=model_id):
        return PermissionRelationModelNameExistsError.return_resp()
    updated = False
    for m in models:
        if m.get("id") != model_id:
            continue
        if request.name is not None:
            m["name"] = _normalize_relation_model_name(request.name)
        if request.permissions is not None:
            m["permissions"] = request.permissions
            m["permissions_explicit"] = True
        updated = True
        break
    if not updated:
        return PermissionInvalidResourceError.return_resp()
    await _save_relation_models(models)
    return resp_200(None)


@router.delete("/relation-models/{model_id}")
async def delete_relation_model(
    model_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    if not login_user.is_admin():
        return PermissionDeniedError.return_resp()
    models = await _get_relation_models()
    target = next((m for m in models if m.get("id") == model_id), None)
    if target is None:
        return PermissionInvalidResourceError.return_resp()
    if target.get("is_system"):
        return PermissionDeniedError.return_resp()

    # Remove model and revoke all tuples bound to this model.
    remain_models = [m for m in models if m.get("id") != model_id]
    bindings = await _get_bindings()
    to_remove = [b for b in bindings if b.get("model_id") == model_id]

    from bisheng.permission.domain.schemas.permission_schema import AuthorizeRevokeItem
    from bisheng.permission.domain.services.permission_service import PermissionService
    from bisheng.permission.domain.services.resource_permission_notification_service import (
        ResourcePermissionNotificationService,
    )

    notify_contexts = []
    try:
        for b in to_remove:
            if _is_invalid_owner_subject(b.get("subject_type"), b.get("relation")):
                logger.warning(
                    "delete_relation_model skip impossible owner revoke model=%s subject=%s:%s resource=%s:%s",
                    model_id,
                    b.get("subject_type"),
                    b.get("subject_id"),
                    b.get("resource_type"),
                    b.get("resource_id"),
                )
                continue
            revoke_item = AuthorizeRevokeItem(
                subject_type=b.get("subject_type"),
                subject_id=int(b.get("subject_id")),
                relation=b.get("relation"),
                include_children=bool(b.get("include_children")),
            )
            notify_context = await ResourcePermissionNotificationService.build_context(
                resource_type=b.get("resource_type"),
                resource_id=str(b.get("resource_id")),
                grants=[],
                revokes=[revoke_item],
            )
            if notify_context is not None:
                notify_contexts.append(notify_context)
            await PermissionService.authorize(
                object_type=b.get("resource_type"),
                object_id=str(b.get("resource_id")),
                grants=[],
                revokes=[revoke_item],
                enforce_fga_success=True,
            )
    except Exception as e:
        logger.error(
            "delete_relation_model failed to revoke model=%s bindings=%d error=%s", model_id, len(to_remove), e
        )
        return PermissionTupleWriteError.return_resp(data={"exception": str(e)})

    remain_bindings = [b for b in bindings if b.get("model_id") != model_id]
    await _save_relation_models(remain_models)
    await _save_bindings(remain_bindings)
    for notify_context in notify_contexts:
        _dispatch_authorize_notifications_in_background(
            context=notify_context,
            operator_user_id=login_user.user_id,
            operator_user_name=getattr(login_user, "user_name", None),
        )
    return resp_200(None)


@router.get("/rebac-schema")
async def rebac_schema_summary(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """PRD §3.2.3 资源权限模板: 返回当前内置 OpenFGA 模型类型与关系名 (仅超管)。"""
    if not login_user.is_admin():
        return PermissionDeniedError.return_resp()

    from bisheng.core.openfga.authorization_model import MODEL_VERSION, get_authorization_model

    model = get_authorization_model()
    types_out = []
    for td in model.get("type_definitions", []):
        tname = td.get("type")
        rels = sorted((td.get("relations") or {}).keys())
        types_out.append({"type": tname, "relations": rels})
    return resp_200(
        {"schema_version": model.get("schema_version"), "model_version": MODEL_VERSION, "types": types_out},
    )


@router.get("/permission-templates/knowledge-space")
async def get_knowledge_space_permission_template(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Return the canonical backend template for knowledge-space permissions.

    Frontend relation-model editors should consume this endpoint instead of
    hardcoding their own copy so runtime and UI stay aligned.
    """
    if not login_user.is_admin():
        return PermissionDeniedError.return_resp()
    return resp_200(KNOWLEDGE_SPACE_PERMISSION_TEMPLATE)


@router.get("/permission-templates/application")
async def get_application_permission_template(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Return the canonical backend template for application permissions."""
    if not login_user.is_admin():
        return PermissionDeniedError.return_resp()
    return resp_200(APPLICATION_PERMISSION_TEMPLATE)


@router.get("/permission-templates/knowledge-library")
async def get_knowledge_library_permission_template(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Return the canonical backend template for knowledge-library permissions."""
    if not login_user.is_admin():
        return PermissionDeniedError.return_resp()
    return resp_200(KNOWLEDGE_LIBRARY_PERMISSION_TEMPLATE)


@router.get("/permission-templates/tool")
async def get_tool_permission_template(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Return the canonical backend template for tool permissions."""
    if not login_user.is_admin():
        return PermissionDeniedError.return_resp()
    return resp_200(TOOL_PERMISSION_TEMPLATE)


@router.get("/permission-templates/channel")
async def get_channel_permission_template(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Return the canonical backend template for channel permissions."""
    if not login_user.is_admin():
        return PermissionDeniedError.return_resp()
    return resp_200(CHANNEL_PERMISSION_TEMPLATE)
