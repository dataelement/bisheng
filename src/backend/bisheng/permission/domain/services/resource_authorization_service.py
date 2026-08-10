from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.permission import (
    PermissionDeniedError,
    PermissionInvalidResourceError,
    PermissionLastOwnerError,
    PermissionTupleWriteError,
)
from bisheng.permission.domain.application_permission_template import (
    default_permission_ids_for_relation as default_application_permissions,
)
from bisheng.permission.domain.channel_permission_template import (
    default_permission_ids_for_relation as default_channel_permissions,
)
from bisheng.permission.domain.knowledge_library_permission_template import (
    default_permission_ids_for_relation as default_knowledge_library_permissions,
)
from bisheng.permission.domain.knowledge_space_permission_template import (
    default_permission_ids_for_relation as default_knowledge_space_permissions,
)
from bisheng.permission.domain.schemas.permission_schema import (
    VALID_RESOURCE_TYPES,
    AuthorizeRequest,
)
from bisheng.permission.domain.services.relation_model_store import (
    get_bindings,
    get_relation_models,
    normalize_model_dict,
    save_bindings,
)
from bisheng.permission.domain.tool_permission_template import (
    default_permission_ids_for_relation as default_tool_permissions,
)

logger = logging.getLogger(__name__)

_MANAGE_PERMISSION_BY_RESOURCE_TIER = {
    "workflow": {"owner": "manage_app_owner", "manager": "manage_app_manager", "usage": "manage_app_viewer"},
    "assistant": {"owner": "manage_app_owner", "manager": "manage_app_manager", "usage": "manage_app_viewer"},
    "tool": {"owner": "manage_tool_owner", "manager": "manage_tool_manager", "usage": "manage_tool_viewer"},
    "knowledge_library": {"owner": "manage_kb_owner", "manager": "manage_kb_manager", "usage": "manage_kb_viewer"},
    "channel": {"owner": "manage_channel_owner", "manager": "manage_channel_manager", "usage": "manage_channel_user"},
}
_MANAGE_PERMISSION_BY_RESOURCE = {
    "knowledge_space": "manage_space_relation",
    "folder": "manage_folder_relation",
    "knowledge_file": "manage_file_relation",
}
_PENDING_NOTIFICATION_TASKS: set[asyncio.Task] = set()


def _infer_grant_tier(relation: str) -> str:
    if relation == "owner":
        return "owner"
    if relation == "manager":
        return "manager"
    return "usage"


def _normalize_model(model: dict) -> dict:
    return normalize_model_dict(model)


def _default_permission_ids(resource_type: str, relation: str) -> set[str]:
    if resource_type in {"workflow", "assistant"}:
        return set(default_application_permissions(relation))
    if resource_type == "tool":
        return set(default_tool_permissions(relation))
    if resource_type == "channel":
        return set(default_channel_permissions(relation))
    if resource_type == "knowledge_library":
        return set(default_knowledge_library_permissions(relation))
    if resource_type in {"knowledge_space", "folder", "knowledge_file"}:
        return set(default_knowledge_space_permissions(relation))
    return set()


def _permission_ids_for_model(resource_type: str, relation: str, model: dict | None) -> set[str]:
    if model is None:
        return _default_permission_ids(resource_type, relation)
    permissions = set(model.get("permissions") or [])
    if model.get("permissions_explicit") is True:
        return permissions & _default_permission_ids(resource_type, "owner")
    if model.get("is_system"):
        return _default_permission_ids(resource_type, model.get("relation") or relation)
    return permissions


def _management_permission_ids(resource_type: str) -> set[str]:
    direct = _MANAGE_PERMISSION_BY_RESOURCE.get(resource_type)
    if direct:
        return {direct}
    return set((_MANAGE_PERMISSION_BY_RESOURCE_TIER.get(resource_type) or {}).values())


def _can_grant_model(resource_type: str, relation: str, model: dict | None, caller_permissions: set[str]) -> bool:
    if model is not None and model.get("relation") != relation:
        return False
    tier_map = _MANAGE_PERMISSION_BY_RESOURCE_TIER.get(resource_type)
    if tier_map:
        tier = model.get("grant_tier") if model else _infer_grant_tier(relation)
        required = {tier_map[tier]} if tier in tier_map else set()
        if model and (not model.get("is_system") or model.get("permissions_explicit") is True):
            required.update(_permission_ids_for_model(resource_type, relation, model) & set(tier_map.values()))
        return bool(required) and required.issubset(caller_permissions)
    return _permission_ids_for_model(resource_type, relation, model).issubset(caller_permissions)


def _normalize_include_children(subject_type: str, value) -> bool | None:
    return bool(value) if subject_type == "department" else None


def _signature(item) -> tuple:
    return (
        item.subject_type,
        int(item.subject_id),
        item.relation,
        _normalize_include_children(item.subject_type, getattr(item, "include_children", None)),
    )


def _binding_key(resource_type, resource_id, subject_type, subject_id, relation, include_children) -> str:
    normalized = _normalize_include_children(subject_type, include_children)
    scope = "-" if normalized is None else "1" if normalized else "0"
    return f"{resource_type}:{resource_id}:{subject_type}:{subject_id}:{relation}:{scope}"


def _legacy_binding_key(resource_type, resource_id, subject_type, subject_id, relation) -> str:
    return f"{resource_type}:{resource_id}:{subject_type}:{subject_id}:{relation}"


class ResourceAuthorizationService:
    """Authoritative generic resource authorization workflow."""

    def __init__(
        self,
        *,
        get_relation_models: Callable[[], Awaitable[list[dict]]] | None = None,
        get_bindings: Callable[[], Awaitable[list[dict]]] | None = None,
        save_bindings: Callable[[list[dict]], Awaitable[None]] | None = None,
        dispatch_notifications: Callable[..., None] | None = None,
        grant_subject_query_service=None,
    ):
        self._get_relation_models_callback = get_relation_models
        self._get_bindings_callback = get_bindings
        self._save_bindings_callback = save_bindings
        self._dispatch_notifications_callback = dispatch_notifications
        self._grant_subject_query_service = grant_subject_query_service

    async def get_relation_models(self) -> list[dict]:
        if self._get_relation_models_callback:
            return await self._get_relation_models_callback()
        return await get_relation_models()

    async def get_bindings(self) -> list[dict]:
        if self._get_bindings_callback:
            return await self._get_bindings_callback()
        return await get_bindings()

    async def save_bindings(self, bindings: list[dict]) -> None:
        if self._save_bindings_callback:
            await self._save_bindings_callback(bindings)
            return
        await save_bindings(bindings)

    async def prospective_owner_permission_ids(
        self,
        resource_type: str,
        *,
        relation_models: list[dict] | None = None,
    ) -> set[str]:
        raw_models = await self.get_relation_models() if relation_models is None else relation_models
        models = [_normalize_model(model) for model in raw_models]
        owner_model = next(
            (
                model
                for model in models
                if model.get("id") == "owner" and model.get("relation") == "owner"
            ),
            None,
        )
        if owner_model is None:
            owner_model = next(
                (
                    model
                    for model in models
                    if model.get("relation") == "owner" and model.get("is_system")
                ),
                None,
            )
        if owner_model is None:
            owner_model = next((model for model in models if model.get("relation") == "owner"), None)
        if owner_model is None:
            return set()
        return _permission_ids_for_model(resource_type, "owner", owner_model)

    async def grantable_models_for_permissions(
        self,
        resource_type: str,
        caller_permission_ids: set[str],
        *,
        relation_models: list[dict] | None = None,
    ) -> list[dict]:
        raw_models = await self.get_relation_models() if relation_models is None else relation_models
        models = [_normalize_model(model) for model in raw_models]
        return [
            model
            for model in models
            if _can_grant_model(
                resource_type,
                model.get("relation") or "",
                model,
                caller_permission_ids,
            )
        ]

    async def validate_grants_for_permissions(
        self,
        *,
        resource_type: str,
        grants,
        caller_permission_ids: set[str],
        relation_models: list[dict] | None = None,
    ) -> None:
        items = list(grants or [])
        models = {}
        if any(getattr(grant, "model_id", None) for grant in items):
            raw_models = await self.get_relation_models() if relation_models is None else relation_models
            models = {model["id"]: _normalize_model(model) for model in raw_models}
        for grant in items:
            model_id = getattr(grant, "model_id", None)
            model = models.get(model_id) if model_id else None
            if model_id and model is None:
                raise PermissionDeniedError()
            if not _can_grant_model(
                resource_type,
                grant.relation,
                model,
                caller_permission_ids,
            ):
                raise PermissionDeniedError()

    async def authorize(
        self,
        resource_type: str,
        resource_id: str,
        request: AuthorizeRequest,
        login_user: UserPayload,
    ) -> None:
        if resource_type not in VALID_RESOURCE_TYPES:
            raise PermissionInvalidResourceError()
        if resource_type == "channel":
            raise PermissionDeniedError()
        if any(item.relation == "owner" and item.subject_type != "user" for item in request.grants):
            raise PermissionDeniedError(msg="部门或用户组无法成为所有者")

        await self._validate_department_space_grants(resource_type, resource_id, request.grants)
        if resource_type == "knowledge_space" and request.grants:
            from bisheng.permission.domain.services.grant_subject_query_service import (
                GrantSubjectQueryService,
            )

            query_service = self._grant_subject_query_service or GrantSubjectQueryService()
            await query_service.validate_resource_grants(
                resource_type=resource_type,
                resource_id=resource_id,
                grants=request.grants,
            )
        bindings: list[dict] | None = None
        if not login_user.is_admin():
            from bisheng.permission.domain.services.fine_grained_permission_service import (
                FineGrainedPermissionService,
            )

            caller_permissions = await FineGrainedPermissionService.get_effective_permission_ids_async(
                login_user,
                resource_type,
                resource_id,
                nearest_binding_wins=resource_type in {"folder", "knowledge_file"},
            )
            management_ids = _management_permission_ids(resource_type)
            if management_ids and not (management_ids & set(caller_permissions)):
                raise PermissionDeniedError()
            bindings = await self._get_bindings_for_authorize()
            await self.validate_grants_for_permissions(
                resource_type=resource_type,
                grants=request.grants,
                caller_permission_ids=set(caller_permissions),
            )
            await self._validate_revokes(
                resource_type=resource_type,
                resource_id=resource_id,
                revokes=request.revokes,
                caller_permission_ids=set(caller_permissions),
                bindings=bindings,
            )
        grant_signatures = {_signature(item) for item in request.grants}
        revoke_signatures = {_signature(item) for item in request.revokes}
        rebind_signatures = grant_signatures & revoke_signatures
        tuple_grants = [item for item in request.grants if _signature(item) not in rebind_signatures]
        tuple_grants.extend(item for item in request.grants if _signature(item) in rebind_signatures)
        tuple_revokes = [
            item
            for item in request.revokes
            if _signature(item) not in rebind_signatures
            and not (item.relation == "owner" and item.subject_type != "user")
        ]
        if any(
            item.subject_type == "user" and int(item.subject_id) == int(login_user.user_id)
            for item in [*tuple_grants, *tuple_revokes]
        ):
            raise PermissionDeniedError(msg="不能修改自己的权限")
        await self._validate_owner_revokes(resource_type, resource_id, tuple_grants, tuple_revokes)

        notify_context = None
        if tuple_grants or tuple_revokes:
            from bisheng.permission.domain.services.permission_service import PermissionService
            from bisheng.permission.domain.services.resource_permission_notification_service import (
                ResourcePermissionNotificationService,
            )

            notify_context = await ResourcePermissionNotificationService.build_context(
                resource_type=resource_type,
                resource_id=resource_id,
                grants=tuple_grants,
                revokes=tuple_revokes,
            )
            try:
                await PermissionService.authorize(
                    object_type=resource_type,
                    object_id=resource_id,
                    grants=tuple_grants,
                    revokes=tuple_revokes,
                    enforce_fga_success=True,
                )
            except BaseErrorCode:
                raise
            except Exception as error:
                logger.exception("resource authorization tuple write failed")
                raise PermissionTupleWriteError(exception=error) from error

        # Admin callers do not need bindings for capability validation. Keep the
        # persistent read after the authoritative tuple write so a rejected
        # self/creator change or a failed FGA write has no unrelated DB dependency.
        if bindings is None:
            bindings = await self._get_bindings_for_authorize()
        await self._save_binding_changes_for_authorize(resource_type, resource_id, request, bindings)
        self._dispatch_notifications(
            context=notify_context,
            operator_user_id=login_user.user_id,
            operator_user_name=getattr(login_user, "user_name", None),
        )
        return None

    async def _get_bindings_for_authorize(self) -> list[dict]:
        try:
            return await self.get_bindings()
        except BaseErrorCode:
            raise
        except Exception as error:
            logger.exception("resource authorization relation-model binding read failed")
            raise PermissionTupleWriteError(exception=error) from error

    async def _save_binding_changes_for_authorize(self, resource_type, resource_id, request, bindings) -> None:
        try:
            await self._save_binding_changes(resource_type, resource_id, request, bindings)
        except BaseErrorCode:
            raise
        except Exception as error:
            logger.exception("resource authorization relation-model binding write failed")
            raise PermissionTupleWriteError(exception=error) from error

    async def _validate_revokes(self, *, resource_type, resource_id, revokes, caller_permission_ids, bindings) -> None:
        models = {model["id"]: _normalize_model(model) for model in await self.get_relation_models()}
        binding_map = {item.get("key"): item for item in bindings}
        for revoke in revokes:
            keys = [
                _binding_key(
                    resource_type,
                    resource_id,
                    revoke.subject_type,
                    revoke.subject_id,
                    revoke.relation,
                    getattr(revoke, "include_children", None),
                ),
                _legacy_binding_key(
                    resource_type,
                    resource_id,
                    revoke.subject_type,
                    revoke.subject_id,
                    revoke.relation,
                ),
            ]
            binding = next((binding_map.get(key) for key in keys if binding_map.get(key)), None)
            model_id = binding.get("model_id") if binding else None
            model = models.get(model_id) if model_id else None
            if model_id and model is None:
                raise PermissionDeniedError()
            if not _can_grant_model(resource_type, revoke.relation, model, caller_permission_ids):
                raise PermissionDeniedError()

    async def _validate_department_space_grants(self, resource_type, resource_id, grants) -> None:
        if resource_type != "knowledge_space" or not str(resource_id).isdigit() or not grants:
            return
        from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
        from bisheng.knowledge.domain.models.department_knowledge_space import (
            DepartmentKnowledgeSpaceDao,
        )

        binding = await DepartmentKnowledgeSpaceDao.aget_by_space_id(int(resource_id))
        if binding is None:
            return
        department = await DepartmentDao.aget_by_id(int(binding.department_id))
        subtree_ids = set(await DepartmentDao.aget_subtree_ids(department.path)) if department else set()
        user_ids: set[int] = set()
        for grant in grants:
            if grant.subject_type == "user_group":
                raise PermissionDeniedError(msg="部门知识空间不支持按用户组授权")
            if grant.subject_type == "department" and int(grant.subject_id) not in subtree_ids:
                raise PermissionDeniedError(msg="只能授权给本部门及子部门")
            if grant.subject_type == "user":
                user_ids.add(int(grant.subject_id))
        if user_ids:
            rows = await UserDepartmentDao.aget_by_user_ids(list(user_ids))
            allowed = {int(row.user_id) for row in rows if int(row.department_id) in subtree_ids}
            if not user_ids.issubset(allowed):
                raise PermissionDeniedError(msg="只能授权给本部门及子部门的成员")

    async def _validate_owner_revokes(self, resource_type, resource_id, grants, revokes) -> None:
        owner_revokes = [item for item in revokes if item.relation == "owner"]
        if not owner_revokes:
            return
        from bisheng.permission.domain.services.permission_service import PermissionService

        if resource_type == "knowledge_space":
            creator_id = await PermissionService._get_resource_creator(resource_type, resource_id)
            if creator_id is not None and any(
                item.subject_type == "user" and int(item.subject_id) == int(creator_id) for item in owner_revokes
            ):
                raise PermissionDeniedError(msg="知识空间创建者的所有者身份不可移除")
            return
        permissions = await PermissionService.get_resource_permissions(resource_type, resource_id)
        owners = {_signature(item) for item in permissions if item.relation == "owner"}
        revoked = {_signature(item) for item in owner_revokes}
        granted = {_signature(item) for item in grants if item.relation == "owner"}
        if not ((owners - revoked) | granted):
            raise PermissionLastOwnerError()

    async def _save_binding_changes(self, resource_type, resource_id, request, bindings) -> None:
        binding_map = {item.get("key"): item for item in bindings if item.get("key")}
        for revoke in request.revokes:
            include_values = [getattr(revoke, "include_children", None)]
            if revoke.subject_type == "department" and (
                getattr(revoke, "include_children", None) is True
                or (revoke.relation == "owner" and revoke.subject_type != "user")
            ):
                include_values = [True, False]
            for include_children in include_values:
                binding_map.pop(
                    _binding_key(
                        resource_type,
                        resource_id,
                        revoke.subject_type,
                        revoke.subject_id,
                        revoke.relation,
                        include_children,
                    ),
                    None,
                )
                binding_map.pop(
                    _legacy_binding_key(
                        resource_type,
                        resource_id,
                        revoke.subject_type,
                        revoke.subject_id,
                        revoke.relation,
                    ),
                    None,
                )
        for grant in request.grants:
            if not grant.model_id:
                continue
            include_children = _normalize_include_children(grant.subject_type, getattr(grant, "include_children", None))
            key = _binding_key(
                resource_type,
                resource_id,
                grant.subject_type,
                grant.subject_id,
                grant.relation,
                include_children,
            )
            binding_map[key] = {
                "key": key,
                "resource_type": resource_type,
                "resource_id": str(resource_id),
                "subject_type": grant.subject_type,
                "subject_id": grant.subject_id,
                "relation": grant.relation,
                "include_children": include_children,
                "model_id": grant.model_id,
            }
        await self.save_bindings(list(binding_map.values()))

    def _dispatch_notifications(self, **kwargs) -> None:
        if self._dispatch_notifications_callback:
            self._dispatch_notifications_callback(**kwargs)
            return
        if kwargs.get("context") is None:
            return
        from bisheng.permission.domain.services.resource_permission_notification_service import (
            ResourcePermissionNotificationService,
        )

        async def runner() -> None:
            try:
                await ResourcePermissionNotificationService.dispatch_after_authorize(**kwargs)
            except Exception:
                logger.exception("post-authorize notification dispatch failed")

        task = asyncio.create_task(runner())
        _PENDING_NOTIFICATION_TASKS.add(task)
        task.add_done_callback(_PENDING_NOTIFICATION_TASKS.discard)
