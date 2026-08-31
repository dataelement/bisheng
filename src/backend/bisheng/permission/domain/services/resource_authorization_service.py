from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AsyncExitStack, asynccontextmanager

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
from bisheng.permission.domain.ports.resource_grant_executor import (
    ResourceGrantCommand,
    ResourceGrantVerificationResult,
)
from bisheng.permission.domain.schemas.permission_schema import (
    VALID_RESOURCE_TYPES,
    AuthorizationItemResult,
    AuthorizationResult,
    AuthorizeGrantItem,
    AuthorizeRequest,
    ResourcePermissionItem,
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
        invite_application_service=None,
        invite_service=None,
        binding_mutation_service=None,
    ):
        self._get_relation_models_callback = get_relation_models
        self._get_bindings_callback = get_bindings
        self._save_bindings_callback = save_bindings
        self._dispatch_notifications_callback = dispatch_notifications
        self._grant_subject_query_service = grant_subject_query_service
        self._invite_application_service = invite_application_service or invite_service
        self._binding_mutation_service = binding_mutation_service

    def _get_invite_application_service(self):
        if self._invite_application_service is not None:
            return self._invite_application_service
        from bisheng.permission.domain.services.resource_user_invite_application_service import (
            build_runtime_resource_user_invite_application_service,
        )

        self._invite_application_service = build_runtime_resource_user_invite_application_service()
        return self._invite_application_service

    def _get_binding_mutation_service(self):
        if self._binding_mutation_service is not None:
            return self._binding_mutation_service
        from bisheng.permission.domain.services.relation_binding_mutation_service import (
            RelationBindingMutationService,
        )

        self._binding_mutation_service = RelationBindingMutationService(
            get_bindings=self.get_bindings,
            save_bindings=self.save_bindings,
        )
        return self._binding_mutation_service

    @asynccontextmanager
    async def _invite_scenario_guard(self, *, tenant_id: int):
        invite_service = self._get_invite_application_service()
        guard_factory = getattr(invite_service, "scenario_guard", None)
        if guard_factory is None:
            availability_check = getattr(invite_service, "ensure_scenario_available", None)
            if availability_check is None:
                raise RuntimeError("resource user invite scenario guard is not configured")
            await availability_check(tenant_id=int(tenant_id))
            yield
            return
        async with guard_factory(tenant_id=int(tenant_id)):
            yield

    @asynccontextmanager
    async def invite_scenario_guard_for_grants(self, *, grants, tenant_id: int):
        if any(item.subject_type == "user" for item in grants or []):
            async with self._invite_scenario_guard(tenant_id=int(tenant_id)):
                yield
            return
        yield

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
            (model for model in models if model.get("id") == "owner" and model.get("relation") == "owner"),
            None,
        )
        if owner_model is None:
            owner_model = next(
                (model for model in models if model.get("relation") == "owner" and model.get("is_system")),
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
        *,
        scenario_guarded: bool = False,
    ) -> AuthorizationResult | None:
        """Apply direct operations and route new knowledge-space users to approval."""
        if resource_type not in VALID_RESOURCE_TYPES:
            raise PermissionInvalidResourceError()
        if resource_type == "channel":
            raise PermissionDeniedError()
        invite_grants: list[AuthorizeGrantItem] = []
        invite_tenant_id: int | None = None
        direct_grants = list(request.grants)
        if resource_type == "knowledge_space":
            from bisheng.permission.domain.services.permission_service import PermissionService

            explicit = await PermissionService.get_resource_permissions(resource_type, resource_id)
            active_user_ids = {int(item.subject_id) for item in explicit if item.subject_type == "user"}
            invite_grants = [
                item
                for item in request.grants
                if item.subject_type == "user" and int(item.subject_id) not in active_user_ids
            ]
            invite_signatures = {_signature(item) for item in invite_grants}
            direct_grants = [item for item in request.grants if _signature(item) not in invite_signatures]
            if invite_grants:
                resolved_tenant_id = await PermissionService._resolve_resource_tenant(resource_type, resource_id)
                if resolved_tenant_id is None:
                    from bisheng.core.context.tenant import get_current_tenant_id

                    resolved_tenant_id = get_current_tenant_id() or getattr(login_user, "tenant_id", 1)
                invite_tenant_id = int(resolved_tenant_id)

        async with AsyncExitStack() as stack:
            if invite_grants and not scenario_guarded:
                from bisheng.common.errcode.approval import ApprovalScenarioDisabledError

                try:
                    await stack.enter_async_context(
                        self._invite_scenario_guard(tenant_id=int(invite_tenant_id)),
                    )
                except ApprovalScenarioDisabledError:
                    # 「知识空间用户邀请确认」审批场景关闭时，个人用户授权降级为直接授权：
                    # 不再创建本人确认审批，直接对新增个人用户授权成功。
                    direct_grants = list(request.grants)
                    invite_grants = []
            if invite_grants:
                await self._validate_invite_request_access(
                    resource_type=resource_type,
                    resource_id=resource_id,
                    grants=invite_grants,
                    login_user=login_user,
                )

            direct_request = AuthorizeRequest(grants=direct_grants, revokes=request.revokes)
            if direct_request.grants or direct_request.revokes:
                await self._authorize_direct(resource_type, resource_id, direct_request, login_user)

            item_results = [
                AuthorizationItemResult(
                    operation="grant",
                    subject_type=item.subject_type,
                    subject_id=item.subject_id,
                    relation=item.relation,
                    model_id=item.model_id,
                    outcome="applied",
                )
                for item in direct_grants
            ]
            item_results.extend(
                AuthorizationItemResult(
                    operation="revoke",
                    subject_type=item.subject_type,
                    subject_id=item.subject_id,
                    relation=item.relation,
                    model_id=item.model_id,
                    outcome="applied",
                )
                for item in request.revokes
            )
            for grant in invite_grants:
                item_results.append(
                    await self._request_personal_user_invite(
                        resource_type=resource_type,
                        resource_id=resource_id,
                        grant=grant,
                        login_user=login_user,
                        tenant_id=int(invite_tenant_id),
                    )
                )
            result = self._authorization_result(item_results)
            return result if resource_type == "knowledge_space" else None

    async def ensure_invite_scenario_available_for_grants(self, *, grants, tenant_id: int) -> None:
        if not any(item.subject_type == "user" for item in grants or []):
            return
        invite_service = self._get_invite_application_service()
        availability_check = getattr(invite_service, "ensure_scenario_available", None)
        if availability_check is None:
            async with self._invite_scenario_guard(tenant_id=int(tenant_id)):
                return
        await availability_check(tenant_id=int(tenant_id))

    async def _validate_invite_request_access(
        self,
        *,
        resource_type: str,
        resource_id: str,
        grants: list[AuthorizeGrantItem],
        login_user: UserPayload,
    ) -> None:
        if login_user.is_admin():
            return
        from bisheng.permission.domain.services.fine_grained_permission_service import (
            FineGrainedPermissionService,
        )

        caller_permissions = await FineGrainedPermissionService.get_effective_permission_ids_async(
            login_user,
            resource_type,
            resource_id,
        )
        management_ids = _management_permission_ids(resource_type)
        if management_ids and not (management_ids & set(caller_permissions)):
            raise PermissionDeniedError()
        await self.validate_grants_for_permissions(
            resource_type=resource_type,
            grants=grants,
            caller_permission_ids=set(caller_permissions),
        )

    async def _request_personal_user_invite(
        self,
        *,
        resource_type: str,
        resource_id: str,
        grant: AuthorizeGrantItem,
        login_user: UserPayload,
        tenant_id: int,
    ) -> AuthorizationItemResult:
        try:
            if int(grant.subject_id) == int(login_user.user_id):
                raise PermissionDeniedError(msg="不能修改自己的权限")
            if not bool(getattr(login_user, "is_global_super", False)):
                # Global super admins invite across departments; everyone else stays
                # scoped to the knowledge space's bound department subtree.
                await self._validate_department_space_grants(resource_type, resource_id, [grant])
            from bisheng.permission.domain.services.grant_subject_query_service import (
                GrantSubjectQueryService,
            )

            query_service = self._grant_subject_query_service or GrantSubjectQueryService()
            await query_service.validate_resource_grants(
                resource_type=resource_type,
                resource_id=resource_id,
                grants=[grant],
            )
            resource_name, target_name, applicant_department_id = await self._resolve_invite_context(
                resource_type=resource_type,
                resource_id=resource_id,
                target_user_id=int(grant.subject_id),
                inviter_user_id=int(login_user.user_id),
            )
            model_id, role_snapshot = await self._resolve_role_snapshot(grant)
            result = await self._get_invite_application_service().request_invite(
                tenant_id=int(tenant_id),
                resource_type=resource_type,
                resource_id=str(resource_id),
                resource_name=resource_name,
                inviter_user_id=int(login_user.user_id),
                inviter_user_name=getattr(login_user, "user_name", "") or "",
                target_user_id=int(grant.subject_id),
                target_user_name=target_name,
                relation=grant.relation,
                model_id=model_id,
                role_snapshot=role_snapshot,
                include_children=False,
                applicant_department_id=applicant_department_id,
            )
            return AuthorizationItemResult(
                operation="grant",
                subject_type="user",
                subject_id=int(result.get("subject_id", grant.subject_id)),
                relation=result.get("relation") or grant.relation,
                model_id=result.get("model_id") or model_id,
                outcome=result["outcome"],
                approval_instance_id=result.get("approval_instance_id"),
            )
        except BaseErrorCode as error:
            return AuthorizationItemResult(
                operation="grant",
                subject_type="user",
                subject_id=grant.subject_id,
                relation=grant.relation,
                model_id=grant.model_id,
                outcome="failed",
                error_code=error.code,
                error_message=error.message,
            )

    @staticmethod
    def _authorization_result(results: list[AuthorizationItemResult]) -> AuthorizationResult:
        return AuthorizationResult(
            direct_applied_count=sum(item.outcome == "applied" for item in results),
            invite_created_count=sum(item.outcome == "invite_created" for item in results),
            invite_existing_count=sum(item.outcome == "invite_existing" for item in results),
            failed_count=sum(item.outcome == "failed" for item in results),
            results=results,
        )

    async def _resolve_role_snapshot(self, grant: AuthorizeGrantItem) -> tuple[str, dict]:
        models = [_normalize_model(item) for item in await self.get_relation_models()]
        model_id = grant.model_id or grant.relation
        model = next(
            (item for item in models if item.get("id") == model_id),
            None,
        )
        if model is None:
            model = next(
                (item for item in models if item.get("relation") == grant.relation and item.get("is_system")),
                None,
            )
        if model is None:
            raise PermissionDeniedError(msg="授权角色不存在")
        return str(model["id"]), model

    async def _resolve_invite_context(
        self,
        *,
        resource_type: str,
        resource_id: str,
        target_user_id: int,
        inviter_user_id: int,
    ) -> tuple[str, str, int | None]:
        from bisheng.database.models.department import UserDepartmentDao
        from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
        from bisheng.user.domain.models.user import UserDao

        resource = await KnowledgeDao.aquery_by_id(int(resource_id)) if resource_type == "knowledge_space" else None
        target = await UserDao.aget_user(target_user_id)
        primary_department = await UserDepartmentDao.aget_user_primary_department(inviter_user_id)
        return (
            getattr(resource, "name", None) or str(resource_id),
            getattr(target, "user_name", None) or str(target_user_id),
            getattr(primary_department, "department_id", None),
        )

    async def _authorize_direct(
        self,
        resource_type: str,
        resource_id: str,
        request: AuthorizeRequest,
        login_user: UserPayload,
        *,
        recovery_owner: str = "service",
    ) -> None:
        if resource_type not in VALID_RESOURCE_TYPES:
            raise PermissionInvalidResourceError()
        if resource_type == "channel":
            raise PermissionDeniedError()
        if any(item.relation == "owner" and item.subject_type != "user" for item in request.grants):
            raise PermissionDeniedError(msg="部门或用户组无法成为所有者")

        if not bool(getattr(login_user, "is_global_super", False)):
            # Global super admins grant across departments; everyone else stays
            # scoped to the knowledge space's bound department subtree.
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
                    recovery_owner=recovery_owner,
                )
            except BaseErrorCode:
                raise
            except Exception as error:
                logger.exception("resource authorization tuple write failed")
                raise PermissionTupleWriteError(exception=error) from error

        if resource_type == "knowledge_space":
            await self._mutate_binding_changes_for_authorize(resource_type, resource_id, request)
        else:
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

    async def _mutate_binding_changes_for_authorize(self, resource_type, resource_id, request) -> None:
        try:
            await self._get_binding_mutation_service().mutate(
                lambda bindings: self._updated_bindings(resource_type, resource_id, request, bindings)
            )
        except BaseErrorCode:
            raise
        except Exception as error:
            logger.exception("resource authorization relation-model binding mutation failed")
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
        await self.save_bindings(self._updated_bindings(resource_type, resource_id, request, bindings))

    def _updated_bindings(self, resource_type, resource_id, request, bindings) -> list[dict]:
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
        return list(binding_map.values())

    async def list_pending_permissions(
        self,
        *,
        tenant_id: int,
        resource_type: str,
        resource_id: str,
        active_permissions: list[ResourcePermissionItem],
    ) -> list[ResourcePermissionItem]:
        """Merge approval-backed pending rows without weakening active FGA truth."""
        if resource_type != "knowledge_space":
            return active_permissions
        invite_service = self._get_invite_application_service()
        list_pending_items = getattr(invite_service, "list_pending_invite_items", None)
        if list_pending_items is not None:
            pending_items = await list_pending_items(
                tenant_id=int(tenant_id),
                resource_type=resource_type,
                resource_id=str(resource_id),
            )
        else:
            # Transitional adapter for injected legacy fakes/implementations.
            rows = await invite_service.list_pending_invites(
                tenant_id=int(tenant_id),
                resource_type=resource_type,
                resource_id=str(resource_id),
            )
            pending_items = [
                ResourcePermissionItem(
                    subject_type="user",
                    subject_id=int(row.target_user_id),
                    subject_name=getattr(row, "target_user_name", None),
                    relation=row.relation,
                    model_id=getattr(row, "model_id", None),
                    model_name=(getattr(row, "role_snapshot", None) or {}).get("name"),
                    authorization_status="pending",
                    approval_instance_id=row.approval_instance_id,
                )
                for row in rows
            ]
        active_users = {int(item.subject_id) for item in active_permissions if item.subject_type == "user"}
        merged = list(active_permissions)
        seen_pending: set[int] = set()
        for item in pending_items:
            target_user_id = int(item.subject_id)
            if not target_user_id or target_user_id in active_users or target_user_id in seen_pending:
                continue
            seen_pending.add(target_user_id)
            merged.append(item)
        return merged

    async def _validate_confirmed_grant_command(
        self,
        command: ResourceGrantCommand,
    ) -> AuthorizeGrantItem:
        from bisheng.core.context.tenant import get_current_tenant_id
        from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum, KnowledgeDao
        from bisheng.permission.domain.services.fine_grained_permission_service import (
            FineGrainedPermissionService,
        )
        from bisheng.permission.domain.services.grant_subject_query_service import (
            GrantSubjectQueryService,
        )
        from bisheng.user.domain.models.user import UserDao
        from bisheng.user.domain.models.user_role import UserRoleDao

        current_tenant_id = get_current_tenant_id()
        if current_tenant_id is None or int(current_tenant_id) != command.tenant_id:
            raise PermissionDeniedError()
        if command.resource_type != "knowledge_space" or not command.resource_id.isdigit():
            raise PermissionInvalidResourceError()
        resource = await KnowledgeDao.aquery_by_id(int(command.resource_id))
        if resource is None:
            raise PermissionInvalidResourceError()
        resource_tenant_id = getattr(resource, "tenant_id", None)
        if resource_tenant_id is not None and int(resource_tenant_id) != command.tenant_id:
            raise PermissionDeniedError()
        # Backstop for the race window where the space is flipped to PRIVATE at the
        # same moment an invitee accepts a share invite (F045). The make-private
        # path withdraws pending invites, but an accept already in flight must not
        # be allowed to add the user to a now-private space.
        if getattr(resource, "auth_type", None) == AuthTypeEnum.PRIVATE:
            raise PermissionDeniedError(msg="知识空间已转为私密, 邀请已失效")
        if command.inviter_user_id == command.target_user_id:
            raise PermissionDeniedError(msg="不能修改自己的权限")

        model_id = command.model_id or command.relation
        normalized_snapshot = _normalize_model(dict(command.role_snapshot))
        snapshot_fingerprint = self._role_snapshot_fingerprint(normalized_snapshot)
        if snapshot_fingerprint != command.role_fingerprint:
            raise PermissionDeniedError(msg="邀请角色快照已变化")
        current_models = [_normalize_model(item) for item in await self.get_relation_models()]
        current_model = next((item for item in current_models if item.get("id") == model_id), None)
        if (
            current_model is None
            or self._role_snapshot_fingerprint(current_model) != command.role_fingerprint
            or current_model.get("relation") != command.relation
        ):
            raise PermissionDeniedError(msg="邀请角色已变更, 请重新邀请")

        grant = AuthorizeGrantItem(
            subject_type="user",
            subject_id=command.target_user_id,
            relation=command.relation,
            model_id=model_id,
            include_children=command.include_children,
        )
        await self._validate_department_space_grants("knowledge_space", command.resource_id, [grant])
        query_service = self._grant_subject_query_service or GrantSubjectQueryService()
        await query_service.validate_resource_grants(
            resource_type="knowledge_space",
            resource_id=command.resource_id,
            grants=[grant],
        )

        inviter = await UserDao.aget_user(command.inviter_user_id)
        if inviter is None or getattr(inviter, "delete", 0):
            raise PermissionDeniedError(msg="邀请人已失效")
        target = await UserDao.aget_user(command.target_user_id)
        if target is None or getattr(target, "delete", 0):
            raise PermissionDeniedError(msg="被邀请人已失效")
        for user in (inviter, target):
            user_tenant_id = getattr(user, "tenant_id", None)
            if user_tenant_id is not None and int(user_tenant_id) != command.tenant_id:
                raise PermissionDeniedError()
        inviter_roles = await UserRoleDao.aget_user_roles(command.inviter_user_id)
        inviter_payload = UserPayload(
            user_id=command.inviter_user_id,
            user_name=getattr(inviter, "user_name", "") or "",
            tenant_id=command.tenant_id,
            user_role=[int(item.role_id) for item in inviter_roles],
        )
        caller_permissions = await FineGrainedPermissionService.get_effective_permission_ids_async(
            inviter_payload,
            "knowledge_space",
            command.resource_id,
        )
        if not (_management_permission_ids("knowledge_space") & set(caller_permissions)):
            raise PermissionDeniedError()
        await self.validate_grants_for_permissions(
            resource_type="knowledge_space",
            grants=[grant],
            caller_permission_ids=set(caller_permissions),
            relation_models=current_models,
        )
        return grant

    async def execute_confirmed_grant(self, command: ResourceGrantCommand) -> None:
        from bisheng.permission.domain.services.permission_service import PermissionService

        grant = await self._validate_confirmed_grant_command(command)
        active = await PermissionService.get_resource_permissions(
            "knowledge_space",
            command.resource_id,
        )
        active_for_target = [
            item for item in active if item.subject_type == "user" and int(item.subject_id) == command.target_user_id
        ]
        exact = next(
            (item for item in active_for_target if item.relation == command.relation),
            None,
        )
        request = AuthorizeRequest(grants=[grant], revokes=[])
        async with self._get_binding_mutation_service().transaction() as transaction:
            desired_bindings = self._updated_bindings(
                "knowledge_space",
                command.resource_id,
                request,
                transaction.bindings,
            )
            if exact is not None and desired_bindings == transaction.bindings:
                return
            if active_for_target:
                raise PermissionDeniedError(msg="目标用户已有生效权限, 请重新发起授权")
            write_error: Exception | None = None
            try:
                await PermissionService.authorize(
                    object_type="knowledge_space",
                    object_id=command.resource_id,
                    grants=[grant],
                    revokes=[],
                    enforce_fga_success=True,
                    recovery_owner="caller",
                )
            except Exception as error:
                write_error = error

            if not await self._confirmed_grant_visible(command):
                await transaction.restore()
                if write_error is not None:
                    raise write_error
                raise PermissionTupleWriteError(exception=RuntimeError("confirmed grant is not authoritative"))

            try:
                await transaction.commit(desired_bindings)
            except Exception as binding_error:
                await self._compensate_confirmed_grant(
                    command=command,
                    grant=grant,
                    transaction=transaction,
                    binding_error=binding_error,
                )
            if write_error is not None:
                raise write_error

    @staticmethod
    async def _confirmed_grant_visible(command: ResourceGrantCommand) -> bool:
        from bisheng.permission.domain.services.permission_service import PermissionService

        active = await PermissionService.get_resource_permissions(
            "knowledge_space",
            command.resource_id,
        )
        return any(
            item.subject_type == "user"
            and int(item.subject_id) == command.target_user_id
            and item.relation == command.relation
            for item in active
        )

    @staticmethod
    async def _compensate_confirmed_grant(
        *,
        command: ResourceGrantCommand,
        grant: AuthorizeGrantItem,
        transaction,
        binding_error: Exception,
    ) -> None:
        from bisheng.permission.domain.schemas.permission_schema import AuthorizeRevokeItem
        from bisheng.permission.domain.services.permission_service import PermissionService

        compensation_error: Exception | None = None
        try:
            await PermissionService.authorize(
                object_type="knowledge_space",
                object_id=command.resource_id,
                grants=[],
                revokes=[
                    AuthorizeRevokeItem(
                        subject_type="user",
                        subject_id=command.target_user_id,
                        relation=command.relation,
                        include_children=command.include_children,
                        model_id=grant.model_id,
                    )
                ],
                enforce_fga_success=True,
                recovery_owner="caller",
            )
        except Exception as error:
            compensation_error = error
            logger.exception("confirmed grant tuple compensation failed")
        restore_error: Exception | None = None
        try:
            await transaction.restore()
        except Exception as error:
            restore_error = error
            logger.exception("confirmed grant binding restore failed")
        if compensation_error is not None or restore_error is not None:
            raise RuntimeError("confirmed grant compensation did not converge") from (
                compensation_error or restore_error
            )
        raise PermissionTupleWriteError(exception=binding_error) from binding_error

    async def verify_confirmed_grant(
        self,
        command: ResourceGrantCommand,
    ) -> ResourceGrantVerificationResult:
        from bisheng.permission.domain.services.permission_service import PermissionService

        grant = await self._validate_confirmed_grant_command(command)
        active = await PermissionService.get_resource_permissions(
            "knowledge_space",
            command.resource_id,
        )
        exact = any(
            item.subject_type == "user"
            and int(item.subject_id) == command.target_user_id
            and item.relation == command.relation
            for item in active
        )
        bindings = await self._get_bindings_for_authorize()
        desired_bindings = self._updated_bindings(
            "knowledge_space",
            command.resource_id,
            AuthorizeRequest(grants=[grant], revokes=[]),
            bindings,
        )
        applied = exact and desired_bindings == bindings
        return ResourceGrantVerificationResult(
            applied=applied,
            result_snapshot={
                "request_id": command.request_id,
                "resource_type": command.resource_type,
                "resource_id": command.resource_id,
                "target_user_id": command.target_user_id,
                "relation": command.relation,
                "model_id": command.model_id,
                "grant_visible": applied,
            },
        )

    async def apply_confirmed_personal_user_grant(
        self,
        *,
        tenant_id: int,
        resource_id: str,
        inviter_user_id: int,
        target_user_id: int,
        relation: str,
        model_id: str | None,
        role_snapshot: dict,
        role_fingerprint: str,
        include_children: bool,
        approval_instance_id: int,
    ) -> None:
        await self.execute_confirmed_grant(
            ResourceGrantCommand(
                tenant_id=tenant_id,
                request_id=approval_instance_id,
                request_fingerprint=f"legacy-approval-instance:{approval_instance_id}",
                resource_type="knowledge_space",
                resource_id=resource_id,
                inviter_user_id=inviter_user_id,
                target_user_id=target_user_id,
                relation=relation,
                model_id=model_id,
                include_children=include_children,
                role_snapshot=role_snapshot,
                role_fingerprint=role_fingerprint,
            )
        )

    @staticmethod
    def _role_snapshot_fingerprint(snapshot: Mapping[str, object]) -> str:
        canonical = json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

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


class KnowledgeSpaceResourceGrantExecutor:
    """Resource owner adapter for confirmed knowledge-space user grants."""

    resource_type = "knowledge_space"

    def __init__(
        self,
        *,
        authorization_service: ResourceAuthorizationService | None = None,
    ) -> None:
        self.authorization_service = authorization_service or ResourceAuthorizationService()

    async def execute(self, command: ResourceGrantCommand) -> None:
        self._validate_type(command)
        await self.authorization_service.execute_confirmed_grant(command)

    async def verify(
        self,
        command: ResourceGrantCommand,
    ) -> ResourceGrantVerificationResult:
        self._validate_type(command)
        return await self.authorization_service.verify_confirmed_grant(command)

    @classmethod
    def _validate_type(cls, command: ResourceGrantCommand) -> None:
        if command.resource_type != cls.resource_type:
            raise PermissionInvalidResourceError()


__all__ = [
    "KnowledgeSpaceResourceGrantExecutor",
    "ResourceAuthorizationService",
]
