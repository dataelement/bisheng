"""Resource permission endpoints (T12b).

POST /api/v1/resources/{resource_type}/{resource_id}/authorize — Grant/revoke permissions.
GET  /api/v1/resources/{resource_type}/{resource_id}/permissions — List resource permissions.
"""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass

from fastapi import APIRouter, Depends, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.permission import (
    PermissionDeniedError,
    PermissionInvalidResourceError,
    PermissionLastOwnerError,
    PermissionRelationModelNameExistsError,
    PermissionTupleWriteError,
)
from bisheng.common.models.config import ConfigDao
from bisheng.common.schemas.api import resp_200
from bisheng.permission.domain.application_permission_template import (
    APPLICATION_PERMISSION_TEMPLATE,
)
from bisheng.permission.domain.application_permission_template import (
    default_permission_ids_for_relation as default_application_permissions,
)
from bisheng.permission.domain.channel_permission_template import (
    CHANNEL_PERMISSION_TEMPLATE,
)
from bisheng.permission.domain.channel_permission_template import (
    default_permission_ids_for_relation as default_channel_permissions,
)
from bisheng.permission.domain.knowledge_library_permission_template import (
    KNOWLEDGE_LIBRARY_PERMISSION_TEMPLATE,
)
from bisheng.permission.domain.knowledge_library_permission_template import (
    default_permission_ids_for_relation as default_knowledge_library_permissions,
)
from bisheng.permission.domain.knowledge_space_permission_template import (
    KNOWLEDGE_SPACE_PERMISSION_TEMPLATE,
)
from bisheng.permission.domain.knowledge_space_permission_template import (
    default_permission_ids_for_relation as default_knowledge_space_permissions,
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
from bisheng.permission.domain.tool_permission_template import (
    TOOL_PERMISSION_TEMPLATE,
)
from bisheng.permission.domain.tool_permission_template import (
    default_permission_ids_for_relation as default_tool_permissions,
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
_RELATION_MODELS_KEY = "permission_relation_models_v1"
_RELATION_MODEL_BINDINGS_KEY = "permission_relation_model_bindings_v1"
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
    text = (name or "").strip()
    for title, label in _RELATION_MODEL_NAME_PREFIX_PAIRS:
        if title and label and text == f"{title}{label}":
            return label
    return text


def _relation_model_name_exists(models: list[dict], name: str | None, exclude_model_id: str | None = None) -> bool:
    normalized_name = _normalize_relation_model_name(name)
    if not normalized_name:
        return False
    return any(
        m.get("id") != exclude_model_id and _normalize_relation_model_name(m.get("name")) == normalized_name
        for m in models
    )


def _normalize_model_dict(m: dict) -> dict:
    out = dict(m)
    out["name"] = _normalize_relation_model_name(out.get("name"))
    gt = out.get("grant_tier")
    if gt not in _GRANT_TIER_VALUES:
        out["grant_tier"] = _infer_grant_tier_from_relation(out.get("relation") or "")
    if not _validate_tier_relation(out["grant_tier"], out.get("relation") or ""):
        out["grant_tier"] = _infer_grant_tier_from_relation(out.get("relation") or "")
    if "permissions_explicit" not in out:
        permissions = out.get("permissions") or []
        if out.get("is_system"):
            out["permissions_explicit"] = False
        else:
            out["permissions_explicit"] = bool(permissions)
    return out


def _default_relation_models() -> list[dict]:
    return [
        {
            "id": "owner",
            "name": "所有者",
            "relation": "owner",
            "grant_tier": "owner",
            "permissions": [],
            "permissions_explicit": False,
            "is_system": True,
        },
        {
            "id": "manager",
            "name": "可管理",
            "relation": "manager",
            "grant_tier": "manager",
            "permissions": [],
            "permissions_explicit": False,
            "is_system": True,
        },
        {
            "id": "editor",
            "name": "可编辑",
            "relation": "editor",
            "grant_tier": "usage",
            "permissions": [],
            "permissions_explicit": False,
            "is_system": True,
        },
        {
            "id": "viewer",
            "name": "可查看",
            "relation": "viewer",
            "grant_tier": "usage",
            "permissions": [],
            "permissions_explicit": False,
            "is_system": True,
        },
    ]


async def _get_relation_models() -> list[dict]:
    """只读；若库中无记录则初始化默认四条，禁止每次读取都覆盖已保存的自定义模型。"""
    row = await ConfigDao.aget_config_by_key(_RELATION_MODELS_KEY)
    if not row or not (row.value or "").strip():
        models = _default_relation_models()
        await _save_relation_models(models)
        return models
    try:
        models = json.loads(row.value or "[]")
    except Exception:
        models = _default_relation_models()
        await _save_relation_models(models)
        return models
    if not models:
        models = _default_relation_models()
        await _save_relation_models(models)
        return models
    return models


async def _save_relation_models(models: list[dict]) -> None:
    await ConfigDao.insert_or_update_config(
        _RELATION_MODELS_KEY,
        json.dumps(models, ensure_ascii=False),
    )


async def _get_bindings() -> list[dict]:
    """只读；禁止每次读取都把绑定表写回空数组。"""
    row = await ConfigDao.aget_config_by_key(_RELATION_MODEL_BINDINGS_KEY)
    if not row or not (row.value or "").strip():
        return []
    try:
        bindings = json.loads(row.value or "[]")
    except Exception:
        return []
    normalized = await _migrate_legacy_knowledge_library_bindings(bindings)
    if normalized != bindings:
        await _save_bindings(normalized)
    return normalized


async def _save_bindings(bindings: list[dict]) -> None:
    await ConfigDao.insert_or_update_config(
        _RELATION_MODEL_BINDINGS_KEY,
        json.dumps(bindings, ensure_ascii=False),
    )


async def _migrate_legacy_knowledge_library_bindings(bindings: list[dict]) -> list[dict]:
    legacy_ids = {
        int(binding.get("resource_id"))
        for binding in bindings
        if binding.get("resource_type") == "knowledge_space" and str(binding.get("resource_id", "")).isdigit()
    }
    if not legacy_ids:
        return bindings

    from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum

    knowledge_rows = await KnowledgeDao.aget_list_by_ids(sorted(legacy_ids))
    knowledge_type_map = {row.id: row.type for row in knowledge_rows}

    normalized: list[dict] = []
    for binding in bindings:
        migrated = dict(binding)
        resource_type = migrated.get("resource_type")
        resource_id = migrated.get("resource_id")
        if resource_type == "knowledge_space" and str(resource_id).isdigit():
            knowledge_type = knowledge_type_map.get(int(resource_id))
            if knowledge_type is not None and knowledge_type != KnowledgeTypeEnum.SPACE.value:
                migrated["resource_type"] = "knowledge_library"
                migrated["key"] = _binding_key_with_scope(
                    "knowledge_library",
                    str(resource_id),
                    migrated.get("subject_type"),
                    int(migrated.get("subject_id")),
                    migrated.get("relation"),
                    migrated.get("include_children"),
                )
        normalized.append(migrated)
    return normalized


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
    normalized = _normalize_binding_include_children(subject_type, include_children)
    scope = "-" if normalized is None else ("1" if normalized else "0")
    return f"{resource_type}:{resource_id}:{subject_type}:{subject_id}:{relation}:{scope}"


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


def _default_permission_ids_for_relation(resource_type: str, relation: str) -> set[str]:
    if resource_type in {"workflow", "assistant"}:
        return default_application_permissions(relation)
    if resource_type == "tool":
        return default_tool_permissions(relation)
    if resource_type == "channel":
        return default_channel_permissions(relation)
    if resource_type == "knowledge_library":
        return default_knowledge_library_permissions(relation)
    if resource_type in {"knowledge_space", "folder", "knowledge_file"}:
        return default_knowledge_space_permissions(relation)
    return set()


def _resource_permission_universe(resource_type: str) -> set[str]:
    # The owner defaults cover the full canonical permission set for each
    # resource type, so they can be used as the scope filter for explicit
    # relation-model permissions persisted in DB.
    return _default_permission_ids_for_relation(resource_type, "owner")


def _permission_ids_for_model(resource_type: str, relation: str, model: dict | None) -> set[str]:
    if model is None:
        return _default_permission_ids_for_relation(resource_type, relation)
    scope = _resource_permission_universe(resource_type)
    permissions = model.get("permissions") or []
    if model.get("permissions_explicit") is True:
        return set(permissions) & scope
    if model.get("is_system"):
        return _default_permission_ids_for_relation(resource_type, model.get("relation") or relation)
    return set(permissions)


def _model_matches_relation(relation: str, model: dict | None) -> bool:
    return model is None or model.get("relation") == relation


def _can_grant_relation_model(
    *,
    resource_type: str,
    relation: str,
    model: dict | None,
    caller_permission_ids: set[str],
) -> bool:
    if not _model_matches_relation(relation, model):
        return False

    tier_map = _MANAGE_PERMISSION_BY_RESOURCE_TIER.get(resource_type)
    if tier_map:
        grant_tier = (
            model.get("grant_tier")
            if model and model.get("grant_tier") in _GRANT_TIER_VALUES
            else _infer_grant_tier_from_relation(relation)
        )
        required_manage_permissions = {permission_id for tier, permission_id in tier_map.items() if tier == grant_tier}

        # Custom or explicitly edited models may themselves carry management
        # permissions. Require the caller to already hold those management
        # capabilities so a "usage" grant cannot smuggle owner-management power.
        if model and (not model.get("is_system") or model.get("permissions_explicit") is True):
            model_permission_ids = _permission_ids_for_model(resource_type, relation, model)
            required_manage_permissions.update(model_permission_ids & set(tier_map.values()))

        return bool(required_manage_permissions) and required_manage_permissions.issubset(caller_permission_ids)

    model_permission_ids = _permission_ids_for_model(resource_type, relation, model)
    return model_permission_ids.issubset(caller_permission_ids)


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
    subtree_dept_ids: frozenset[int]


async def _resolve_department_space_scope(resource_type: str, resource_id: str) -> "_DepartmentSpaceScope | None":
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
        return _DepartmentSpaceScope(department_id=department_id, subtree_dept_ids=frozenset())

    subtree_ids = await DepartmentDao.aget_subtree_ids(dept.path)
    return _DepartmentSpaceScope(
        department_id=department_id,
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
) -> bool:
    from bisheng.permission.domain.services.permission_service import PermissionService

    management_permission_ids = _management_permission_ids(resource_type)
    if management_permission_ids:
        from bisheng.permission.domain.services.fine_grained_permission_service import FineGrainedPermissionService

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
    restrict_dept_ids: frozenset[int] | None = None,
) -> list[dict]:
    from sqlmodel import select

    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.core.database import get_async_db_session
    from bisheng.database.models.department import DepartmentDao, UserDepartment, UserDepartmentDao
    from bisheng.database.models.tenant import Tenant, UserTenant
    from bisheng.user.domain.models.user import User

    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            stmt = (
                select(User)
                .join(UserTenant, UserTenant.user_id == User.user_id)
                .join(Tenant, Tenant.id == UserTenant.tenant_id)
                .where(
                    UserTenant.tenant_id == tenant_id,
                    UserTenant.status == "active",
                    Tenant.status == "active",
                    User.delete == 0,
                )
                .order_by(User.user_id.desc())
            )
            # F033: department knowledge space -> only members of the bound
            # department subtree (a user is visible if ANY of their departments
            # is in the subtree). Filter at SQL level so pagination stays correct.
            if restrict_dept_ids is not None:
                stmt = (
                    stmt.join(UserDepartment, UserDepartment.user_id == User.user_id)
                    .where(UserDepartment.department_id.in_(restrict_dept_ids))
                    .distinct()
                )
            if keyword:
                # Prefix match (``keyword%``) so the user_name index (Field(index=True))
                # can be used — a leading-wildcard ``%keyword%`` forces a full scan of the
                # users table (~160ms over 150k rows on the DM8 load-test tenant).
                stmt = stmt.where(User.user_name.like(f"{keyword}%"))
            if page and page_size:
                stmt = stmt.offset((page - 1) * page_size).limit(page_size)
            result = await session.exec(stmt)
            active_users = list(result.all())

    if not active_users:
        return []

    user_ids = [int(user.user_id) for user in active_users if getattr(user, "user_id", None) is not None]
    dept_rows = await UserDepartmentDao.aget_by_user_ids(user_ids)
    primary_rows = [row for row in dept_rows if int(getattr(row, "is_primary", 0) or 0) == 1]
    # F038 perf: resolve the full-path label for ONLY the primary departments shown on
    # this page (+ their ancestors), never the whole tenant department table. On the 50k-
    # department load-test tenant, aget_active_by_tenant loaded ~50k rows in ~2.8s on DM8
    # and was ~94% of this endpoint's latency — yet dept_map only labels <= page_size users.
    primary_dept_ids = {
        int(row.department_id) for row in primary_rows if getattr(row, "department_id", None) is not None
    }
    primary_depts = await DepartmentDao.aget_by_ids(list(primary_dept_ids)) if primary_dept_ids else []
    dept_map = {int(dept.id): dept for dept in primary_depts if getattr(dept, "id", None) is not None}
    ancestor_ids = {
        i for dept in primary_depts for i in _grant_path_ids(getattr(dept, "path", None)) if i not in dept_map
    }
    if ancestor_ids:
        for ancestor in await DepartmentDao.aget_by_ids(list(ancestor_ids)) or []:
            if getattr(ancestor, "id", None) is not None:
                dept_map[int(ancestor.id)] = ancestor
    primary_by_user = {
        int(row.user_id): dept_map.get(int(row.department_id))
        for row in primary_rows
        if getattr(row, "user_id", None) is not None and getattr(row, "department_id", None) is not None
    }

    def _department_display_path(dept) -> str | None:
        if dept is None:
            return None
        path_ids: list[int] = []
        for part in str(getattr(dept, "path", "") or "").split("/"):
            part = part.strip()
            if part.isdigit():
                path_ids.append(int(part))
        labels = [getattr(dept_map.get(dept_id), "name", f"#{dept_id}") for dept_id in path_ids]
        current_name = getattr(dept, "name", None)
        if current_name and current_name not in labels:
            labels.append(current_name)
        return "/".join(labels) if labels else current_name

    return [
        {
            "user_id": int(user.user_id),
            "user_name": user.user_name,
            "external_id": getattr(user, "external_id", None),
            "primary_department_path": _department_display_path(
                primary_by_user.get(int(user.user_id)),
            ),
        }
        for user in active_users
    ]


# --------------------------------------------------------------------------- #
# F038: lazy variants of the grant-subject department tree (browse one layer /
# search / locate). Visible scope = the TENANT ROOT SUBTREE minus child-tenant
# mount subtrees, optionally clamped
# to a bound department's subtree (F033) — but never loads the whole tree. The
# F033 restriction is passed as a PATH PREFIX (``restrict_root_path``) rather than
# an id set, so it stays a ``path LIKE`` predicate and never hits DM8's large
# ``.in_()`` serialization trap (design §5 #1). The channel picker is the
# ``restrict_root_path=None`` case (decision 3: same scope helper, no admin scope).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _GrantDeptScope:
    """Resolved browse scope for the grant-subject department tree.

    ``positive_prefix`` — materialized-path prefix of the visible subtree root
    (tenant root, or the F033 bound department); ``None`` falls back to a
    ``tenant_id`` filter when the tenant has no root department.
    ``exclude_prefixes`` — child-tenant mount subtrees carved out (ROOT tenant only).
    """

    positive_prefix: str | None
    exclude_prefixes: tuple[str, ...]
    tenant_id: int


def _grant_path_ids(path: str | None) -> list[int]:
    """Ancestor→self id chain from a materialized path ``/10/11/12/`` → ``[10, 11, 12]``."""
    out: list[int] = []
    for part in (path or "").split("/"):
        part = part.strip()
        if part:
            try:
                out.append(int(part))
            except ValueError:
                continue
    return out


def _grant_in_scope(dept, scope: "_GrantDeptScope") -> bool:
    """Whether ``dept`` is inside the visible scope (positive prefix / tenant
    fallback, and not under any excluded child-mount subtree)."""
    path = getattr(dept, "path", None)
    if scope.positive_prefix is not None:
        if not (path and path.startswith(scope.positive_prefix)):
            return False
    elif int(getattr(dept, "tenant_id", 0) or 0) != scope.tenant_id:
        return False
    return not any(path and path.startswith(ex) for ex in scope.exclude_prefixes)


def _apply_grant_scope(stmt, scope: "_GrantDeptScope", Department):
    """Push the visible scope into a ``select(Department...)`` statement."""
    if scope.positive_prefix is not None:
        stmt = stmt.where(Department.path.like(f"{scope.positive_prefix}%"))
    else:
        stmt = stmt.where(Department.tenant_id == scope.tenant_id)
    for ex in scope.exclude_prefixes:
        stmt = stmt.where(~Department.path.like(f"{ex}%"))
    return stmt


def _grant_dept_node(dept, *, has_children: bool = False, matched: bool = False) -> dict:
    return {
        "id": int(dept.id),
        "dept_id": dept.dept_id,
        "name": dept.name,
        "parent_id": int(dept.parent_id) if getattr(dept, "parent_id", None) is not None else None,
        "path": dept.path,
        "sort_order": int(getattr(dept, "sort_order", 0) or 0),
        "source": dept.source,
        "status": dept.status,
        "has_children": has_children,
        "matched": matched,
        "children": [],
    }


async def _resolve_grant_dept_scope(session, tenant_id: int, restrict_root_path: str | None):
    """Resolve ``_GrantDeptScope`` for ``tenant_id``; ``None`` when the tenant is
    missing/inactive (callers return empty). Scope = tenant root subtree minus
    child-tenant mount subtrees (the canonical grant-subject visible set)."""
    from sqlmodel import select

    from bisheng.database.models.department import Department
    from bisheng.database.models.tenant import ROOT_TENANT_ID, Tenant

    tenant = (await session.exec(select(Tenant).where(Tenant.id == tenant_id, Tenant.status == "active"))).first()
    if tenant is None:
        return None

    root_dept = None
    if getattr(tenant, "root_dept_id", None):
        root_dept = (
            await session.exec(
                select(Department).where(
                    Department.id == int(tenant.root_dept_id),
                    Department.status == "active",
                )
            )
        ).first()

    exclude: list[str] = []
    if root_dept is not None and tenant_id == ROOT_TENANT_ID:
        child_roots = (
            await session.exec(
                select(Department.path).where(
                    Department.is_tenant_root == 1,
                    Department.mounted_tenant_id.is_not(None),
                    Department.mounted_tenant_id != ROOT_TENANT_ID,
                    Department.status == "active",
                )
            )
        ).all()
        exclude = [p for p in child_roots if p]

    if root_dept is not None:
        positive = restrict_root_path or root_dept.path
    else:
        positive = restrict_root_path  # may be None → tenant_id fallback
    return _GrantDeptScope(positive_prefix=positive, exclude_prefixes=tuple(exclude), tenant_id=tenant_id)


async def _grant_children_existence(session, parent_ids: list[int], scope: "_GrantDeptScope", Department) -> set[int]:
    """Which of ``parent_ids`` (one rendered layer) have ≥1 visible child — one
    ``DISTINCT parent_id`` query, no N+1. ``parent_ids`` is a single layer so the
    ``.in_()`` stays small."""
    if not parent_ids:
        return set()
    from sqlmodel import select

    stmt = select(Department.parent_id).where(
        Department.parent_id.in_(parent_ids),
        Department.status == "active",
    )
    stmt = _apply_grant_scope(stmt, scope, Department).distinct()
    rows = (await session.exec(stmt)).all()
    out: set[int] = set()
    for r in rows:
        val = r[0] if isinstance(r, (list, tuple)) else r
        if val is not None:
            out.add(int(val))
    return out


async def _grant_build_pruned(
    session, seeds, matched_ids: set[int], scope: "_GrantDeptScope", Department
) -> list[dict]:
    """Minimal forest of ``seeds`` + their in-scope ancestors (clamped to the
    positive prefix so names above it never leak); ``matched_ids`` flagged."""
    if not seeds:
        return []
    from sqlmodel import select

    needed: set[int] = set()
    for d in seeds:
        needed.update(_grant_path_ids(d.path))
    if not needed:
        return []
    rows = list(
        (
            await session.exec(select(Department).where(Department.id.in_(list(needed)), Department.status == "active"))
        ).all()
    )
    visible = [d for d in rows if _grant_in_scope(d, scope)]
    if not visible:
        return []
    existence = await _grant_children_existence(session, [int(d.id) for d in visible], scope, Department)
    nodes = {
        int(d.id): _grant_dept_node(d, has_children=int(d.id) in existence, matched=int(d.id) in matched_ids)
        for d in visible
    }
    roots: list[dict] = []
    for d in visible:
        pid = int(d.parent_id) if getattr(d, "parent_id", None) is not None else None
        if pid is not None and pid in nodes:
            nodes[pid]["children"].append(nodes[int(d.id)])
        else:
            roots.append(nodes[int(d.id)])

    def _sort(layer: list[dict]):
        layer.sort(key=lambda n: (n["sort_order"], n["id"]))
        for n in layer:
            _sort(n["children"])

    _sort(roots)
    return roots


async def _grant_departments_children(
    *, tenant_id: int, parent_id: int | None = None, restrict_root_path: str | None = None
) -> list[dict]:
    """One visible layer of the grant-subject department tree (AC-24). No
    ``parent_id`` → root layer (the scope root). Out-of-scope/missing parent →
    empty (no leak)."""
    from sqlmodel import select

    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.core.database import get_async_db_session
    from bisheng.database.models.department import Department

    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            scope = await _resolve_grant_dept_scope(session, tenant_id, restrict_root_path)
            if scope is None:
                return []
            if parent_id is None:
                if scope.positive_prefix is not None:
                    root_ids = _grant_path_ids(scope.positive_prefix)
                    if not root_ids:
                        return []
                    root = (
                        await session.exec(
                            select(Department).where(Department.id == root_ids[-1], Department.status == "active")
                        )
                    ).first()
                    depts = [root] if root is not None and _grant_in_scope(root, scope) else []
                else:
                    stmt = select(Department).where(Department.parent_id.is_(None), Department.status == "active")
                    stmt = _apply_grant_scope(stmt, scope, Department)
                    depts = list((await session.exec(stmt.order_by(Department.sort_order, Department.id))).all())
            else:
                parent = (
                    await session.exec(
                        select(Department).where(Department.id == parent_id, Department.status == "active")
                    )
                ).first()
                if parent is None or not _grant_in_scope(parent, scope):
                    return []
                stmt = select(Department).where(Department.parent_id == parent_id, Department.status == "active")
                stmt = _apply_grant_scope(stmt, scope, Department)
                depts = list((await session.exec(stmt.order_by(Department.sort_order, Department.id))).all())

            depts = [d for d in depts if d is not None]
            if not depts:
                return []
            existence = await _grant_children_existence(session, [int(d.id) for d in depts], scope, Department)
            return [_grant_dept_node(d, has_children=int(d.id) in existence) for d in depts]


async def _grant_departments_search(
    *, tenant_id: int, keyword: str, limit: int = 50, restrict_root_path: str | None = None
) -> dict:
    """Server-side name search within the grant scope → pruned tree (AC-26).
    Blank keyword returns empty without a query; ``truncated`` set over ``limit``."""
    kw = (keyword or "").strip()
    if not kw:
        return {"roots": [], "total_matches": 0, "truncated": False}
    limit = max(1, min(limit, 200))

    from sqlmodel import select

    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.core.database import get_async_db_session
    from bisheng.database.models.department import Department

    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            scope = await _resolve_grant_dept_scope(session, tenant_id, restrict_root_path)
            if scope is None:
                return {"roots": [], "total_matches": 0, "truncated": False}
            stmt = select(Department).where(Department.name.like(f"%{kw}%"), Department.status == "active")
            stmt = _apply_grant_scope(stmt, scope, Department)
            matched = list(
                (await session.exec(stmt.order_by(Department.sort_order, Department.id).limit(limit + 1))).all()
            )
            truncated = len(matched) > limit
            matched = matched[:limit]
            matched_ids = {int(d.id) for d in matched}
            roots = await _grant_build_pruned(session, matched, matched_ids, scope, Department)
            return {"roots": roots, "total_matches": len(matched), "truncated": truncated}


async def _grant_departments_path_tree(*, tenant_id: int, dept_id: int, restrict_root_path: str | None = None) -> dict:
    """Locate/reveal a department within the grant scope (AC-26). Out-of-scope or
    missing target → empty roots (no leak)."""
    from sqlmodel import select

    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.core.database import get_async_db_session
    from bisheng.database.models.department import Department

    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            scope = await _resolve_grant_dept_scope(session, tenant_id, restrict_root_path)
            if scope is None:
                return {"roots": [], "total_matches": 0, "truncated": False}
            target = (
                await session.exec(select(Department).where(Department.id == dept_id, Department.status == "active"))
            ).first()
            if target is None or not _grant_in_scope(target, scope):
                return {"roots": [], "total_matches": 0, "truncated": False}
            roots = await _grant_build_pruned(session, [target], {int(target.id)}, scope, Department)
            return {"roots": roots, "total_matches": 1, "truncated": False}


async def _list_knowledge_space_grant_user_groups(
    *,
    tenant_id: int,
    keyword: str,
    login_user,
) -> list[dict]:
    from sqlmodel import select

    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.core.database import get_async_db_session
    from bisheng.database.models.group import Group
    from bisheng.database.models.tenant import Tenant
    from bisheng.database.models.user_group import UserGroupDao
    from bisheng.user_group.domain.services.user_group_service import (
        _can_view_all_groups,
    )

    viewer_group_ids: set[int] = set()
    can_view_all = await _can_view_all_groups(login_user)
    if not can_view_all:
        raw_visible_group_ids = await UserGroupDao.aget_user_visible_group_ids(
            login_user.user_id,
        )
        viewer_group_ids = {
            int(x[0]) if isinstance(x, tuple) else int(x) for x in raw_visible_group_ids or [] if x is not None
        }

    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            stmt = (
                select(Group)
                .join(Tenant, Tenant.id == Group.tenant_id)
                .where(
                    Group.tenant_id == tenant_id,
                    Tenant.status == "active",
                )
                .order_by(Group.update_time.desc())
                .limit(2000)
            )
            if not can_view_all:
                if viewer_group_ids:
                    stmt = stmt.where(
                        (Group.visibility == "public")
                        | (Group.create_user == login_user.user_id)
                        | (Group.id.in_(viewer_group_ids))
                    )
                else:
                    stmt = stmt.where((Group.visibility == "public") | (Group.create_user == login_user.user_id))
            if keyword:
                stmt = stmt.where(Group.group_name.like(f"%{keyword}%"))
            result = await session.exec(stmt)
            groups = list(result.all())
    return [
        {
            "id": int(group.id),
            "group_name": group.group_name,
        }
        for group in groups
        if getattr(group, "id", None) is not None
    ]


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
    （所有者级 / 管理级 / 使用级），与 PRD 管理应用所有者/管理者/使用者对齐。
    """
    if resource_type not in VALID_RESOURCE_TYPES:
        return PermissionInvalidResourceError.return_resp()
    if resource_type == "channel":
        return PermissionDeniedError.return_resp()
    if any(_is_invalid_owner_subject(grant.subject_type, grant.relation) for grant in (request.grants or [])):
        return PermissionDeniedError.return_resp("部门或用户组无法成为所有者")

    # F033: department knowledge space restricts grants to the bound department
    # subtree / its members and forbids user-group grants. Applies to ALL
    # identities (incl. super_admin), so it sits outside the is_admin() bypass.
    department_scope = await _resolve_department_space_scope(resource_type, resource_id)
    if department_scope is not None:
        denial = await _validate_department_space_grants(department_scope, request.grants or [])
        if denial is not None:
            return denial

    from bisheng.permission.domain.services.permission_service import PermissionService

    if not login_user.is_admin():
        raw_models = await _get_relation_models()
        model_map = {m["id"]: _normalize_model_dict(m) for m in raw_models}
        binding_map = {
            b.get("key"): b
            for b in await _get_bindings()
            if b.get("resource_type") == resource_type and str(b.get("resource_id")) == str(resource_id)
        }
        management_permission_ids = _management_permission_ids(resource_type)
        caller_permission_ids = set()
        if management_permission_ids:
            from bisheng.permission.domain.services.fine_grained_permission_service import FineGrainedPermissionService

            caller_permission_ids = await FineGrainedPermissionService.get_effective_permission_ids_async(
                login_user,
                resource_type,
                resource_id,
                nearest_binding_wins=_lineage_binding_can_override(resource_type),
            )

        if management_permission_ids and not (management_permission_ids & caller_permission_ids):
            return PermissionDeniedError.return_resp()

        for grant in request.grants or []:
            model = model_map.get(getattr(grant, "model_id", None)) if getattr(grant, "model_id", None) else None
            if getattr(grant, "model_id", None) and model is None:
                return PermissionDeniedError.return_resp()
            if not _can_grant_relation_model(
                resource_type=resource_type,
                relation=grant.relation,
                model=model,
                caller_permission_ids=caller_permission_ids,
            ):
                return PermissionDeniedError.return_resp()

        for revoke in request.revokes or []:
            binding = _binding_from_map(
                binding_map,
                resource_type,
                str(resource_id),
                revoke.subject_type,
                revoke.subject_id,
                revoke.relation,
                getattr(revoke, "include_children", None),
            )
            model = model_map.get(binding.get("model_id")) if binding and binding.get("model_id") else None
            if binding and binding.get("model_id") and model is None:
                return PermissionDeniedError.return_resp()
            if not _can_grant_relation_model(
                resource_type=resource_type,
                relation=revoke.relation,
                model=model,
                caller_permission_ids=caller_permission_ids,
            ):
                return PermissionDeniedError.return_resp()

    grant_signatures = {_tuple_signature(g) for g in (request.grants or [])}
    revoke_signatures = {_tuple_signature(r) for r in (request.revokes or [])}
    rebind_only_signatures = grant_signatures & revoke_signatures

    # Same subject/relation changes are model rebinds. Do not delete the tuple,
    # but still issue an idempotent write so stale DB-only bindings are repaired.
    rebind_only_grants = [
        grant for grant in (request.grants or []) if _tuple_signature(grant) in rebind_only_signatures
    ]
    tuple_grants = [
        grant for grant in (request.grants or []) if _tuple_signature(grant) not in rebind_only_signatures
    ] + rebind_only_grants
    tuple_revokes = [
        revoke
        for revoke in (request.revokes or [])
        if _tuple_signature(revoke) not in rebind_only_signatures
        and not _is_invalid_owner_subject(revoke.subject_type, revoke.relation)
    ]

    # Owner and creator are decoupled: an owner may be revoked/downgraded as long
    # as another owner survives, but removing the last owner would orphan the
    # resource (INV-2). Applies to ALL owner revokes (self or someone else's), and
    # same-request owner grants count as survivors (ownership transfer).
    owner_revokes = [revoke for revoke in tuple_revokes if getattr(revoke, "relation", None) == "owner"]
    if owner_revokes:
        if resource_type == "knowledge_space":
            # The knowledge_space creator is a permanent, non-removable owner:
            # ownership is backed by the SpaceChannelMember CREATOR row +
            # Knowledge.user_id (honored by "我创建的" and file read/write/delete)
            # regardless of FGA tuples, so revoking/downgrading the creator's owner
            # is refused. Any OTHER owner is always safe to remove — the creator
            # backstops ownership, so the space can never be orphaned.
            from bisheng.permission.domain.services.permission_service import PermissionService

            creator_id = await PermissionService._get_resource_creator(resource_type, resource_id)
            if creator_id is not None and any(
                revoke.subject_type == "user" and int(revoke.subject_id) == int(creator_id) for revoke in owner_revokes
            ):
                return PermissionDeniedError.return_resp("知识空间创建者的所有者身份不可移除")
        elif not await _can_remove_owner_relations(
            resource_type=resource_type,
            resource_id=resource_id,
            revokes=owner_revokes,
            grants=tuple_grants,
        ):
            return PermissionLastOwnerError.return_resp()

    permission_notify_context = None
    if tuple_grants or tuple_revokes:
        from bisheng.permission.domain.services.resource_permission_notification_service import (
            ResourcePermissionNotificationService,
        )

        permission_notify_context = await ResourcePermissionNotificationService.build_context(
            resource_type=resource_type,
            resource_id=resource_id,
            grants=tuple_grants,
            revokes=tuple_revokes,
        )
        logger.info(
            "resource_authorize start actor=%s resource=%s:%s grants=%d revokes=%d",
            login_user.user_id,
            resource_type,
            resource_id,
            len(tuple_grants),
            len(tuple_revokes),
        )
        try:
            await PermissionService.authorize(
                object_type=resource_type,
                object_id=resource_id,
                grants=tuple_grants,
                revokes=tuple_revokes,
                enforce_fga_success=True,
            )
        except Exception as e:
            logger.error(
                "resource_authorize failed actor=%s resource=%s:%s grants=%d revokes=%d error=%s",
                login_user.user_id,
                resource_type,
                resource_id,
                len(tuple_grants),
                len(tuple_revokes),
                e,
            )
            return PermissionTupleWriteError.return_resp(data={"exception": str(e)})

    # Persist relation-model bindings for UI display and model deletion cascade.
    bindings = await _get_bindings()
    bindings_map = {b.get("key"): b for b in bindings if b.get("key")}
    for revoke in request.revokes or []:
        include_children = getattr(revoke, "include_children", None)
        include_children_values = [include_children]
        if revoke.subject_type == "department" and (
            include_children is True or _is_invalid_owner_subject(revoke.subject_type, revoke.relation)
        ):
            include_children_values = [True, False]
        for include_children in include_children_values:
            for key in _binding_lookup_keys(
                resource_type,
                str(resource_id),
                revoke.subject_type,
                revoke.subject_id,
                revoke.relation,
                include_children,
            ):
                bindings_map.pop(key, None)
    for grant in request.grants or []:
        if not getattr(grant, "model_id", None):
            continue
        normalized_include_children = _normalize_binding_include_children(
            grant.subject_type,
            getattr(grant, "include_children", None),
        )
        key = _binding_key_with_scope(
            resource_type,
            str(resource_id),
            grant.subject_type,
            grant.subject_id,
            grant.relation,
            normalized_include_children,
        )
        bindings_map[key] = {
            "key": key,
            "resource_type": resource_type,
            "resource_id": str(resource_id),
            "subject_type": grant.subject_type,
            "subject_id": grant.subject_id,
            "relation": grant.relation,
            "include_children": normalized_include_children,
            "model_id": grant.model_id,
        }
    await _save_bindings(list(bindings_map.values()))

    # Notification is not part of the authorize business result: dispatch it in
    # the background so the per-member OpenFGA checks + inbox writes never block
    # or fail the response. The pre-write snapshot lives in the context already.
    _dispatch_authorize_notifications_in_background(
        context=permission_notify_context,
        operator_user_id=login_user.user_id,
        operator_user_name=getattr(login_user, "user_name", None),
    )
    logger.info(
        "resource_authorize success actor=%s resource=%s:%s grants=%d revokes=%d bindings=%d",
        login_user.user_id,
        resource_type,
        resource_id,
        len(request.grants or []),
        len(request.revokes or []),
        len(bindings_map),
    )
    return resp_200(None)


@router.get("/resources/{resource_type}/{resource_id}/grant-subjects/users")
async def get_grant_subject_users(
    resource_type: str,
    resource_id: str,
    keyword: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(1000, ge=1, le=2000),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    if resource_type not in VALID_RESOURCE_TYPES:
        return PermissionInvalidResourceError.return_resp()
    if not await _has_resource_permission_management_access(
        resource_type=resource_type,
        resource_id=resource_id,
        login_user=login_user,
    ):
        return PermissionDeniedError.return_resp()
    tenant_id = await _resolve_grant_subject_tenant_id(
        resource_type=resource_type,
        resource_id=resource_id,
        login_user=login_user,
    )
    if tenant_id is None:
        return resp_200([])
    scope = await _resolve_department_space_scope(resource_type, resource_id)
    return resp_200(
        await _list_knowledge_space_grant_users(
            tenant_id=tenant_id,
            keyword=keyword,
            page=page,
            page_size=page_size,
            restrict_dept_ids=scope.subtree_dept_ids if scope else None,
        )
    )


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
    scope = await _resolve_department_space_scope(resource_type, resource_id)
    restrict_root_path = None
    if scope is not None:
        if not scope.subtree_dept_ids:
            return None, tenant_id, None, True  # bound dept archived/missing → no target
        from bisheng.database.models.department import DepartmentDao

        bound = await DepartmentDao.aget_by_id(scope.department_id)
        if bound is None or getattr(bound, "path", None) is None:
            return None, tenant_id, None, True
        restrict_root_path = bound.path
    return None, tenant_id, restrict_root_path, False


@router.get("/resources/{resource_type}/{resource_id}/grant-subjects/departments/children")
async def get_grant_subject_departments_children(
    resource_type: str,
    resource_id: str,
    parent_id: int | None = Query(None),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    err, tenant_id, restrict_root_path, empty = await _grant_dept_lazy_preamble(resource_type, resource_id, login_user)
    if err is not None:
        return err
    if empty:
        return resp_200(_EMPTY_DEPT_LAYER)
    return resp_200(
        await _grant_departments_children(
            tenant_id=tenant_id, parent_id=parent_id, restrict_root_path=restrict_root_path
        )
    )


@router.get("/resources/{resource_type}/{resource_id}/grant-subjects/departments/search")
async def search_grant_subject_departments(
    resource_type: str,
    resource_id: str,
    keyword: str = "",
    limit: int = Query(50, ge=1, le=200),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    err, tenant_id, restrict_root_path, empty = await _grant_dept_lazy_preamble(resource_type, resource_id, login_user)
    if err is not None:
        return err
    if empty:
        return resp_200(dict(_EMPTY_DEPT_TREE))
    return resp_200(
        await _grant_departments_search(
            tenant_id=tenant_id, keyword=keyword, limit=limit, restrict_root_path=restrict_root_path
        )
    )


@router.get("/resources/{resource_type}/{resource_id}/grant-subjects/departments/{dept_id:int}/path-tree")
async def get_grant_subject_departments_path_tree(
    resource_type: str,
    resource_id: str,
    dept_id: int,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    err, tenant_id, restrict_root_path, empty = await _grant_dept_lazy_preamble(resource_type, resource_id, login_user)
    if err is not None:
        return err
    if empty:
        return resp_200(dict(_EMPTY_DEPT_TREE))
    return resp_200(
        await _grant_departments_path_tree(tenant_id=tenant_id, dept_id=dept_id, restrict_root_path=restrict_root_path)
    )


@router.get("/resources/{resource_type}/{resource_id}/grant-subjects/user-groups")
async def get_grant_subject_user_groups(
    resource_type: str,
    resource_id: str,
    keyword: str = "",
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    if resource_type not in VALID_RESOURCE_TYPES:
        return PermissionInvalidResourceError.return_resp()
    if not await _has_resource_permission_management_access(
        resource_type=resource_type,
        resource_id=resource_id,
        login_user=login_user,
    ):
        return PermissionDeniedError.return_resp()
    # F033: department knowledge spaces disable the user-group dimension.
    if await _resolve_department_space_scope(resource_type, resource_id) is not None:
        return resp_200([])
    tenant_id = await _resolve_grant_subject_tenant_id(
        resource_type=resource_type,
        resource_id=resource_id,
        login_user=login_user,
    )
    if tenant_id is None:
        return resp_200([])
    return resp_200(
        await _list_knowledge_space_grant_user_groups(
            tenant_id=tenant_id,
            keyword=keyword,
            login_user=login_user,
        )
    )


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
    )
    if not allowed:
        return PermissionDeniedError.return_resp()

    permissions = await PermissionService.get_resource_permissions(
        object_type=resource_type,
        object_id=resource_id,
    )
    models = await _get_relation_models()
    model_map = {m["id"]: _normalize_model_dict(m) for m in models}
    binding_map = {
        b.get("key"): b
        for b in await _get_bindings()
        if b.get("resource_type") == resource_type and str(b.get("resource_id")) == str(resource_id)
    }
    bindings = list(binding_map.values())
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
    return resp_200(permissions)


@router.get("/relation-models")
async def get_relation_models(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    models = [RelationModelItem(**_normalize_model_dict(m)) for m in await _get_relation_models()]
    return resp_200(models)


@router.get("/relation-models/grantable")
async def get_grantable_relation_models(
    object_type: str,
    object_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
):
    """返回当前用户在指定资源上「有权用于授权」的关系模型子集。"""
    if object_type not in VALID_RESOURCE_TYPES:
        return PermissionInvalidResourceError.return_resp()

    raw = [_normalize_model_dict(m) for m in await _get_relation_models()]
    if login_user.is_admin():
        return resp_200([RelationModelItem(**m) for m in raw])

    management_permission_ids = _management_permission_ids(object_type)
    caller_permission_ids = set()
    if management_permission_ids:
        from bisheng.permission.domain.services.fine_grained_permission_service import FineGrainedPermissionService

        caller_permission_ids = await FineGrainedPermissionService.get_effective_permission_ids_async(
            login_user,
            object_type,
            object_id,
            nearest_binding_wins=_lineage_binding_can_override(object_type),
        )
    if management_permission_ids and not (management_permission_ids & caller_permission_ids):
        return resp_200([])

    out = []
    for m in raw:
        if _can_grant_relation_model(
            resource_type=object_type,
            relation=m.get("relation") or "",
            model=m,
            caller_permission_ids=caller_permission_ids,
        ):
            out.append(RelationModelItem(**m))
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
    """PRD §3.2.3 资源权限模板：返回当前内置 OpenFGA 模型类型与关系名（仅超管）。"""
    if not login_user.is_admin():
        return PermissionDeniedError.return_resp()

    from bisheng.core.openfga.authorization_model import MODEL_VERSION, get_authorization_model

    model = get_authorization_model()
    types_out = []
    for td in model.get("type_definitions", []):
        tname = td.get("type")
        rels = sorted(list((td.get("relations") or {}).keys()))
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
