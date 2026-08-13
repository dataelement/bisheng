from __future__ import annotations

import logging
from collections.abc import Iterable

from sqlmodel import col, select

from bisheng.channel.domain.schemas.channel_authorization_schema import (
    ChannelAuthorizeRequest,
    ChannelAuthorizeResponse,
    ChannelGrantItem,
    ChannelPermissionEntry,
    ChannelRelationModelItem,
    ChannelRevokeItem,
)
from bisheng.channel.domain.services.channel_membership_sync_service import (
    ChannelMembershipSyncService,
)
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.channel import (
    ChannelAuthorizationSyncError,
    ChannelNotFoundError,
    ChannelPermissionDeniedError,
)
from bisheng.common.errcode.permission import PermissionTupleWriteError
from bisheng.common.models.space_channel_member import ChannelRelationEnum
from bisheng.common.repositories.interfaces.space_channel_member_repository import (
    SpaceChannelMemberRepository,
)
from bisheng.core.openfga.exceptions import FGAConnectionError, FGAWriteError
from bisheng.permission.domain.channel_permission_template import (
    default_permission_ids_for_relation,
    relation_from_channel_permission_ids,
    validate_channel_grant_subject,
)
from bisheng.permission.domain.schemas.permission_schema import (
    AuthorizeGrantItem,
    AuthorizeRevokeItem,
)
from bisheng.permission.domain.schemas.tuple_operation import TupleOperation
from bisheng.permission.domain.services.fine_grained_permission_service import FineGrainedPermissionService
from bisheng.permission.domain.services.grant_subject_query_service import (
    GrantSubjectQueryService,
)
from bisheng.permission.domain.services.permission_service import PermissionService
from bisheng.permission.domain.services.relation_model_store import get_bindings, get_relation_models, save_bindings
from bisheng.permission.domain.services.resource_permission_notification_service import (
    ResourcePermissionNotificationService,
)

logger = logging.getLogger(__name__)

_GRANT_TIER_VALUES = frozenset({"owner", "manager", "usage"})

# A relation model can only be granted when the caller holds the matching
# fine-grained management permission. This intentionally keeps the three
# `manage_channel_*` checkboxes independent: holding `manage_channel_manager`
# must NOT imply the ability to grant the owner tier.
_GRANT_TIER_TO_MANAGE_PERMISSION = {
    "owner": "manage_channel_owner",
    "manager": "manage_channel_manager",
    "usage": "manage_channel_user",
}
_CHANNEL_MANAGE_PERMISSION_IDS = frozenset(_GRANT_TIER_TO_MANAGE_PERMISSION.values())


def _grant_tier_for_relation(relation: str) -> str:
    if relation == "owner":
        return "owner"
    if relation == "manager":
        return "manager"
    return "usage"


class ChannelAuthorizationService:
    def __init__(
        self,
        channel_repository,
        space_channel_member_repository: SpaceChannelMemberRepository,
        membership_sync_service: ChannelMembershipSyncService | None = None,
        grant_subject_query_service: GrantSubjectQueryService | None = None,
    ):
        self.channel_repository = channel_repository
        self.space_channel_member_repository = space_channel_member_repository
        self.membership_sync_service = membership_sync_service or ChannelMembershipSyncService(
            space_channel_member_repository,
        )
        self.grant_subject_query_service = grant_subject_query_service or GrantSubjectQueryService()

    async def authorize_channel(
        self,
        channel_id: str,
        request: ChannelAuthorizeRequest,
        login_user: UserPayload,
    ) -> ChannelAuthorizeResponse:
        channel = await self._ensure_channel(channel_id)
        self._reject_creator_permission_change(channel, request)
        actor_permissions = await self._actor_grant_permissions(channel_id, login_user)
        self._validate_request(actor_permissions, request)
        await self._validate_subjects_belong_to_channel_tenant(channel, request, login_user)

        tuple_grants = [self._to_permission_grant(item) for item in request.grants]
        tuple_revokes = [self._to_permission_revoke(item) for item in request.revokes]
        notify_context = None
        if tuple_grants or tuple_revokes:
            notify_context = await ResourcePermissionNotificationService.build_context(
                resource_type="channel",
                resource_id=channel_id,
                grants=tuple_grants,
                revokes=tuple_revokes,
            )

        if tuple_grants or tuple_revokes:
            try:
                await PermissionService.authorize(
                    object_type="channel",
                    object_id=channel_id,
                    grants=tuple_grants,
                    revokes=tuple_revokes,
                    enforce_fga_success=True,
                )
            except (FGAConnectionError, FGAWriteError) as exc:
                logger.exception(
                    "channel authorization tuple write failed: channel_id=%s",
                    channel_id,
                )
                raise ChannelAuthorizationSyncError(exception=exc) from exc

        original_bindings: list[dict] | None = None
        try:
            original_bindings = await self._get_bindings()
            await self._save_binding_changes_from_snapshot(channel_id, request, original_bindings)
        except Exception as exc:
            logger.exception("channel authorization sync failed: channel_id=%s", channel_id)
            if original_bindings is not None:
                await self._restore_bindings(channel_id, original_bindings)
            await self._compensate_permission_write(channel_id, tuple_grants, tuple_revokes)
            raise ChannelAuthorizationSyncError(exception=exc) from exc

        await ResourcePermissionNotificationService.dispatch_after_authorize(
            context=notify_context,
            operator_user_id=login_user.user_id,
            operator_user_name=getattr(login_user, "user_name", None),
        )

        return ChannelAuthorizeResponse(
            synced_user_count=0,
            affected_member_count=0,
        )

    async def list_permissions(self, channel_id: str, login_user: UserPayload) -> list[ChannelPermissionEntry]:
        await self._require_manage_access(channel_id, login_user, use_binding_index=True)
        channel = await self._ensure_channel(channel_id)
        creator_id = int(channel.user_id) if getattr(channel, "user_id", None) is not None else None
        bindings = [
            b
            for b in await self._get_bindings()
            if b.get("resource_type") == "channel" and str(b.get("resource_id")) == str(channel_id)
        ]
        model_map = {m["id"]: m for m in await self._get_relation_models()}
        display_bindings = list(bindings)
        if creator_id is not None and not any(
            binding.get("subject_type") == "user"
            and str(binding.get("subject_id")) == str(creator_id)
            and binding.get("relation") == ChannelRelationEnum.OWNER.value
            for binding in display_bindings
        ):
            display_bindings.append(
                {
                    "subject_type": "user",
                    "subject_id": creator_id,
                    "relation": ChannelRelationEnum.OWNER.value,
                    "include_children": None,
                    "model_id": ChannelRelationEnum.OWNER.value,
                }
            )
        permissions = await PermissionService.get_resource_permissions_from_bindings(
            display_bindings,
            model_map,
        )
        out: list[ChannelPermissionEntry] = []
        for item in permissions:
            out.append(
                ChannelPermissionEntry(
                    subject_type=item.subject_type,
                    subject_id=int(item.subject_id),
                    subject_name=getattr(item, "subject_name", None),
                    subject_group_names=getattr(item, "subject_group_names", None),
                    subject_member_names=getattr(item, "subject_member_names", None),
                    relation=ChannelRelationEnum(item.relation),
                    include_children=getattr(item, "include_children", None),
                    model_id=getattr(item, "model_id", None),
                    model_name=getattr(item, "model_name", None),
                    is_creator=(
                        item.subject_type == "user" and creator_id is not None and int(item.subject_id) == creator_id
                    ),
                )
            )
        return out

    async def grantable_relation_models(
        self,
        channel_id: str,
        login_user: UserPayload,
    ) -> list[ChannelRelationModelItem]:
        await self._ensure_channel(channel_id)
        if login_user.is_admin():
            return [ChannelRelationModelItem(**m) for m in await self._get_relation_models()]
        actor_permissions = await self._actor_grant_permissions(channel_id, login_user)
        if not actor_permissions:
            return []
        models = []
        for model in await self._get_relation_models():
            required = _GRANT_TIER_TO_MANAGE_PERMISSION.get(self._model_grant_tier(model))
            if required and required in actor_permissions:
                models.append(ChannelRelationModelItem(**model))
        return models

    async def list_grant_users(self, channel_id: str, login_user: UserPayload, keyword: str, page: int, page_size: int):
        await self._require_manage_access(channel_id, login_user)
        tenant_id = await self._resolve_channel_tenant(channel_id, login_user)
        if tenant_id is None:
            return []
        return await self.grant_subject_query_service.list_users(
            tenant_id=tenant_id,
            keyword=keyword,
            page=page,
            page_size=page_size,
            restrict_dept_path=None,
        )

    # F038: lazy variants. Channels are never department-scoped, so restrict_root_path
    # is always None — same tenant-subtree scope as the legacy full-tree list, just one
    # layer / pruned tree at a time. Reuses the permission module's shared helpers.
    async def list_grant_departments_children(
        self, channel_id: str, login_user: UserPayload, parent_id: int | None = None
    ):
        await self._require_manage_access(channel_id, login_user)
        tenant_id = await self._resolve_channel_tenant(channel_id, login_user)
        if tenant_id is None:
            return []
        return await self.grant_subject_query_service.list_departments_children(
            tenant_id=tenant_id,
            parent_id=parent_id,
            restrict_root_path=None,
        )

    async def search_grant_departments(self, channel_id: str, login_user: UserPayload, keyword: str, limit: int = 50):
        await self._require_manage_access(channel_id, login_user)
        tenant_id = await self._resolve_channel_tenant(channel_id, login_user)
        if tenant_id is None:
            return {"roots": [], "total_matches": 0, "truncated": False}
        return await self.grant_subject_query_service.search_departments(
            tenant_id=tenant_id,
            keyword=keyword,
            limit=limit,
            restrict_root_path=None,
        )

    async def get_grant_departments_path_tree(self, channel_id: str, login_user: UserPayload, dept_id: int):
        await self._require_manage_access(channel_id, login_user)
        tenant_id = await self._resolve_channel_tenant(channel_id, login_user)
        if tenant_id is None:
            return {"roots": [], "total_matches": 0, "truncated": False}
        return await self.grant_subject_query_service.get_departments_path_tree(
            tenant_id=tenant_id,
            dept_id=dept_id,
            restrict_root_path=None,
        )

    async def list_grant_user_groups(self, channel_id: str, login_user: UserPayload, keyword: str):
        await self._require_manage_access(channel_id, login_user)
        tenant_id = await self._resolve_channel_tenant(channel_id, login_user)
        if tenant_id is None:
            return []
        return await self.grant_subject_query_service.list_user_groups(
            tenant_id=tenant_id,
            keyword=keyword,
            login_user=login_user,
        )

    async def _ensure_channel(self, channel_id: str):
        if hasattr(self.channel_repository, "find_by_id"):
            channel = await self.channel_repository.find_by_id(channel_id)
            if channel:
                return channel
        if hasattr(self.channel_repository, "find_channels_by_ids"):
            channels = await self.channel_repository.find_channels_by_ids([channel_id])
            if channels:
                return channels[0]
        raise ChannelNotFoundError()

    async def _validate_subjects_belong_to_channel_tenant(
        self,
        channel,
        request: ChannelAuthorizeRequest,
        login_user: UserPayload,
    ) -> None:
        tenant_id = await self._channel_tenant_id(channel, login_user)
        if tenant_id is None:
            raise ChannelPermissionDeniedError()
        items = [*(request.grants or []), *(request.revokes or [])]
        if not items:
            return
        known_types = {"user", "department", "user_group"}
        if any(item.subject_type not in known_types for item in items):
            raise ChannelPermissionDeniedError()

        grant_items = list(request.grants or [])
        if not grant_items:
            return

        user_ids = {int(item.subject_id) for item in grant_items if item.subject_type == "user"}
        department_ids = {int(item.subject_id) for item in grant_items if item.subject_type == "department"}
        user_group_ids = {int(item.subject_id) for item in grant_items if item.subject_type == "user_group"}

        if user_ids and not await self._users_belong_to_tenant(user_ids, tenant_id):
            raise ChannelPermissionDeniedError()
        if department_ids and not await self._departments_belong_to_tenant(department_ids, tenant_id):
            raise ChannelPermissionDeniedError()
        if user_group_ids and not await self._user_groups_belong_to_tenant(user_group_ids, tenant_id):
            raise ChannelPermissionDeniedError()

    async def _channel_tenant_id(self, channel, login_user: UserPayload) -> int | None:
        tenant_id = getattr(channel, "tenant_id", None)
        if tenant_id is None:
            tenant_id = await self._resolve_channel_tenant(str(getattr(channel, "id", "")), login_user)
        return int(tenant_id or 0) or None

    @staticmethod
    async def _users_belong_to_tenant(user_ids: Iterable[int], tenant_id: int) -> bool:
        from bisheng.core.context.tenant import bypass_tenant_filter
        from bisheng.core.database import get_async_db_session
        from bisheng.database.models.tenant import Tenant, UserTenant
        from bisheng.user.domain.models.user import User

        ids = {int(user_id) for user_id in user_ids}
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                stmt = (
                    select(User.user_id)
                    .join(UserTenant, UserTenant.user_id == User.user_id)
                    .join(Tenant, Tenant.id == UserTenant.tenant_id)
                    .where(
                        col(User.user_id).in_(ids),
                        UserTenant.tenant_id == tenant_id,
                        UserTenant.status == "active",
                        Tenant.status == "active",
                        User.delete == 0,
                    )
                )
                rows = (await session.exec(stmt)).all()
        return {int(row[0] if isinstance(row, tuple) else row) for row in rows} == ids

    @staticmethod
    async def _departments_belong_to_tenant(department_ids: Iterable[int], tenant_id: int) -> bool:
        from bisheng.core.context.tenant import bypass_tenant_filter
        from bisheng.core.database import get_async_db_session
        from bisheng.database.models.department import Department
        from bisheng.database.models.tenant import ROOT_TENANT_ID, Tenant

        ids = {int(department_id) for department_id in department_ids}
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                tenant = (
                    await session.exec(
                        select(Tenant).where(
                            Tenant.id == tenant_id,
                            Tenant.status == "active",
                        ),
                    )
                ).first()
                if tenant is None:
                    return False

                stmt = select(Department.id).where(
                    col(Department.id).in_(ids),
                    Department.status == "active",
                )
                root_dept = None
                if getattr(tenant, "root_dept_id", None):
                    root_dept = (
                        await session.exec(
                            select(Department).where(
                                Department.id == int(tenant.root_dept_id),
                                Department.status == "active",
                            ),
                        )
                    ).first()
                if root_dept is not None:
                    stmt = stmt.where(Department.path.like(f"{root_dept.path}%"))
                    if tenant_id == ROOT_TENANT_ID:
                        child_roots = (
                            await session.exec(
                                select(Department.path).where(
                                    Department.is_tenant_root == 1,
                                    Department.mounted_tenant_id.is_not(None),
                                    Department.mounted_tenant_id != ROOT_TENANT_ID,
                                    Department.status == "active",
                                ),
                            )
                        ).all()
                        for child_path in child_roots:
                            stmt = stmt.where(~Department.path.like(f"{child_path}%"))
                else:
                    stmt = stmt.where(Department.tenant_id == tenant_id)
                rows = (await session.exec(stmt)).all()
        return {int(row[0] if isinstance(row, tuple) else row) for row in rows} == ids

    @staticmethod
    async def _user_groups_belong_to_tenant(user_group_ids: Iterable[int], tenant_id: int) -> bool:
        from bisheng.core.context.tenant import bypass_tenant_filter
        from bisheng.core.database import get_async_db_session
        from bisheng.database.models.group import Group
        from bisheng.database.models.tenant import Tenant

        ids = {int(user_group_id) for user_group_id in user_group_ids}
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                stmt = (
                    select(Group.id)
                    .join(Tenant, Tenant.id == Group.tenant_id)
                    .where(
                        col(Group.id).in_(ids),
                        Group.tenant_id == tenant_id,
                        Tenant.status == "active",
                    )
                )
                rows = (await session.exec(stmt)).all()
        return {int(row[0] if isinstance(row, tuple) else row) for row in rows} == ids

    async def _actor_relation(
        self,
        channel_id: str,
        login_user: UserPayload,
        *,
        use_binding_index: bool = False,
    ) -> ChannelRelationEnum | None:
        if login_user.is_admin():
            return ChannelRelationEnum.OWNER
        try:
            if use_binding_index:
                permission_ids = (
                    await FineGrainedPermissionService.get_effective_permission_ids_from_verified_bindings_async(
                        login_user,
                        "channel",
                        channel_id,
                    )
                )
            else:
                permission_ids = await FineGrainedPermissionService.get_effective_permission_ids_async(
                    login_user,
                    "channel",
                    channel_id,
                )
            relation = relation_from_channel_permission_ids(permission_ids)
            if relation:
                return ChannelRelationEnum(relation)
        except Exception:
            logger.exception("failed to resolve channel permission ids: channel_id=%s", channel_id)
        return await self.space_channel_member_repository.get_effective_channel_relation(
            channel_id,
            login_user.user_id,
        )

    async def _require_manage_access(
        self,
        channel_id: str,
        login_user: UserPayload,
        *,
        use_binding_index: bool = False,
    ) -> ChannelRelationEnum:
        actor_relation = await self._actor_relation(
            channel_id,
            login_user,
            use_binding_index=use_binding_index,
        )
        if actor_relation not in {ChannelRelationEnum.OWNER, ChannelRelationEnum.MANAGER}:
            raise ChannelPermissionDeniedError()
        return actor_relation

    async def _actor_grant_permissions(
        self,
        channel_id: str,
        login_user: UserPayload,
    ) -> set[str]:
        """Return the subset of channel `manage_channel_*` permissions the caller holds.

        Grant gating is driven by these fine-grained permissions rather than a
        collapsed relation tier, so e.g. a role that can manage managers but not
        owners cannot grant the owner relation.
        """
        if login_user.is_admin():
            return set(_CHANNEL_MANAGE_PERMISSION_IDS)
        permission_ids: set[str] = set()
        try:
            resolved = await FineGrainedPermissionService.get_effective_permission_ids_async(
                login_user,
                "channel",
                channel_id,
            )
            permission_ids = set(resolved or [])
        except Exception:
            logger.exception("failed to resolve channel permission ids: channel_id=%s", channel_id)
        if not permission_ids:
            # Legacy members without a relation-model binding: derive the manage
            # permissions from their effective membership relation.
            relation = await self.space_channel_member_repository.get_effective_channel_relation(
                channel_id,
                login_user.user_id,
            )
            if relation is not None:
                permission_ids = set(default_permission_ids_for_relation(relation.value))
        return permission_ids & _CHANNEL_MANAGE_PERMISSION_IDS

    @staticmethod
    def _model_grant_tier(model: dict) -> str:
        tier = model.get("grant_tier")
        if tier in _GRANT_TIER_VALUES:
            return tier
        return _grant_tier_for_relation(model.get("relation") or "")

    @staticmethod
    def _reject_creator_permission_change(channel, request: ChannelAuthorizeRequest) -> None:
        """The channel creator is a permanent owner.

        Their permission level can never be modified through authorization — not
        even by an actor holding ``manage_channel_owner``. Any grant or revoke
        that targets the creator user is rejected.
        """
        creator_id = getattr(channel, "user_id", None)
        if creator_id is None:
            return
        creator_id = int(creator_id)
        for item in [*(request.grants or []), *(request.revokes or [])]:
            if item.subject_type == "user" and int(item.subject_id) == creator_id:
                raise ChannelPermissionDeniedError(msg="无法修改频道创建人的权限")

    def _validate_request(
        self,
        actor_permissions: set[str],
        request: ChannelAuthorizeRequest,
    ) -> None:
        if not actor_permissions:
            raise ChannelPermissionDeniedError()
        for item in [*(request.grants or []), *(request.revokes or [])]:
            relation = ChannelRelationEnum(item.relation).value
            if not validate_channel_grant_subject(item.subject_type, relation):
                raise ChannelPermissionDeniedError(msg="部门或用户组无法成为所有者")
            required = _GRANT_TIER_TO_MANAGE_PERMISSION.get(_grant_tier_for_relation(relation))
            if not required or required not in actor_permissions:
                raise ChannelPermissionDeniedError()

    @staticmethod
    def _to_permission_grant(item: ChannelGrantItem) -> AuthorizeGrantItem:
        return AuthorizeGrantItem(
            subject_type=item.subject_type,
            subject_id=item.subject_id,
            relation=ChannelRelationEnum(item.relation).value,
            include_children=item.include_children,
            model_id=item.model_id or ChannelRelationEnum(item.relation).value,
        )

    @staticmethod
    def _to_permission_revoke(item: ChannelRevokeItem) -> AuthorizeRevokeItem:
        return AuthorizeRevokeItem(
            subject_type=item.subject_type,
            subject_id=item.subject_id,
            relation=ChannelRelationEnum(item.relation).value,
            include_children=item.include_children,
            model_id=item.model_id,
        )

    @classmethod
    async def _compensate_permission_write(
        cls,
        channel_id: str,
        grants: list[AuthorizeGrantItem],
        revokes: list[AuthorizeRevokeItem],
    ) -> None:
        try:
            await PermissionService.authorize(
                object_type="channel",
                object_id=channel_id,
                grants=[
                    AuthorizeGrantItem(
                        subject_type=item.subject_type,
                        subject_id=item.subject_id,
                        relation=item.relation,
                        include_children=item.include_children,
                        model_id=item.model_id,
                    )
                    for item in revokes
                ],
                revokes=[
                    AuthorizeRevokeItem(
                        subject_type=item.subject_type,
                        subject_id=item.subject_id,
                        relation=item.relation,
                        include_children=item.include_children,
                        model_id=item.model_id,
                    )
                    for item in grants
                ],
                enforce_fga_success=True,
            )
        except Exception:
            logger.exception("channel authorization compensation failed: channel_id=%s", channel_id)

    async def _cleanup_grant_membership_sources(self, channel_id: str, binding_keys: list[str]) -> None:
        for binding_key in dict.fromkeys(binding_keys):
            await self.space_channel_member_repository.delete_channel_membership_source(
                channel_id,
                binding_key,
            )

    async def _restore_bindings(self, channel_id: str, bindings: list[dict]) -> None:
        try:
            await self._save_bindings(bindings)
        except Exception:
            logger.exception("channel authorization binding restore failed: channel_id=%s", channel_id)
            raise

    async def _save_binding_changes(self, channel_id: str, request: ChannelAuthorizeRequest) -> None:
        bindings = await self._get_bindings()
        await self._save_binding_changes_from_snapshot(channel_id, request, bindings)

    async def _save_binding_changes_from_snapshot(
        self,
        channel_id: str,
        request: ChannelAuthorizeRequest,
        bindings: list[dict],
    ) -> None:
        bindings_map = {b.get("key"): b for b in bindings if b.get("key")}
        for revoke in request.revokes:
            bindings_map.pop(self.binding_key(channel_id, revoke), None)
        for grant in request.grants:
            key = self.binding_key(channel_id, grant)
            bindings_map[key] = {
                "key": key,
                "resource_type": "channel",
                "resource_id": str(channel_id),
                "subject_type": grant.subject_type,
                "subject_id": grant.subject_id,
                "relation": ChannelRelationEnum(grant.relation).value,
                "include_children": self._normalize_include_children(
                    grant.subject_type,
                    grant.include_children,
                ),
                "model_id": grant.model_id or ChannelRelationEnum(grant.relation).value,
            }
        await self._save_bindings(list(bindings_map.values()))

    @staticmethod
    def _normalize_include_children(subject_type: str, include_children) -> bool | None:
        if subject_type != "department":
            return None
        return bool(include_children)

    @classmethod
    def binding_key(cls, channel_id: str, item: ChannelGrantItem | ChannelRevokeItem) -> str:
        include_children = cls._normalize_include_children(item.subject_type, item.include_children)
        scope = "-" if include_children is None else ("1" if include_children else "0")
        return (
            f"channel:{channel_id}:{item.subject_type}:{item.subject_id}:"
            f"{ChannelRelationEnum(item.relation).value}:{scope}"
        )

    @classmethod
    def _binding_lookup_keys(
        cls,
        channel_id: str,
        subject_type: str,
        subject_id: int,
        relation: str,
        include_children,
    ) -> list[str]:
        normalized = cls._normalize_include_children(subject_type, include_children)
        scope = "-" if normalized is None else ("1" if normalized else "0")
        return [
            f"channel:{channel_id}:{subject_type}:{subject_id}:{relation}:{scope}",
            f"channel:{channel_id}:{subject_type}:{subject_id}:{relation}",
        ]

    @classmethod
    def _binding_from_map(
        cls,
        bindings_map: dict,
        channel_id: str,
        subject_type: str,
        subject_id: int,
        relation: str,
        include_children,
    ):
        for key in cls._binding_lookup_keys(
            channel_id,
            subject_type,
            subject_id,
            relation,
            include_children,
        ):
            binding = bindings_map.get(key)
            if binding:
                return binding
        return None

    @classmethod
    async def clear_authorization_for_private(cls, channel_id: str, creator_user_id: int) -> int:
        """Remove every private-channel grant except the actual creator owner."""
        try:
            fga = await PermissionService._aget_fga()
            if fga is None:
                raise RuntimeError("FGAClient not available while clearing private-channel permissions")
            tuples = await fga.read_tuples(object=f"channel:{channel_id}")
            creator_tuple = (f"user:{creator_user_id}", "owner")
            operations = [
                TupleOperation(
                    action="delete",
                    user=tuple_item["user"],
                    relation=tuple_item["relation"],
                    object=tuple_item["object"],
                )
                for tuple_item in (tuples or [])
                if (tuple_item.get("user"), tuple_item.get("relation")) != creator_tuple
            ]
            if operations:
                await PermissionService.batch_write_tuples(
                    operations,
                    crash_safe=True,
                    raise_on_failure=True,
                    stop_on_failure=True,
                )
        except PermissionTupleWriteError:
            raise
        except Exception as error:
            logger.exception("failed to clear private-channel tuples: channel_id=%s", channel_id)
            raise PermissionTupleWriteError(exception=error) from error

        try:
            bindings = await cls._get_bindings()
            remaining: list[dict] = []
            removed = 0
            for binding in bindings:
                is_channel_binding = binding.get("resource_type") == "channel" and str(
                    binding.get("resource_id")
                ) == str(channel_id)
                is_creator_binding = (
                    binding.get("subject_type") == "self"
                    and str(binding.get("subject_id")) == str(creator_user_id)
                    and binding.get("relation") == ChannelRelationEnum.OWNER.value
                )
                if is_channel_binding and not is_creator_binding:
                    removed += 1
                    continue
                remaining.append(binding)
            if removed:
                await cls._save_bindings(remaining)
        except PermissionTupleWriteError:
            raise
        except Exception as error:
            logger.exception("failed to clear private-channel bindings: channel_id=%s", channel_id)
            raise PermissionTupleWriteError(exception=error) from error
        return removed

    @classmethod
    async def clear_non_owner_bindings(cls, channel_id: str) -> int:
        """Compatibility helper for callers that only revoke non-owner grants."""
        bindings = await cls._get_bindings()
        remaining: list[dict] = []
        removed = 0
        for binding in bindings:
            is_channel_binding = binding.get("resource_type") == "channel" and str(binding.get("resource_id")) == str(
                channel_id
            )
            if is_channel_binding and binding.get("relation") != ChannelRelationEnum.OWNER.value:
                removed += 1
                continue
            remaining.append(binding)
        if removed:
            await cls._save_bindings(remaining)
        return removed

    @staticmethod
    async def _get_bindings() -> list[dict]:
        return await get_bindings()

    @staticmethod
    async def _save_bindings(bindings: list[dict]) -> None:
        await save_bindings(bindings)

    @classmethod
    async def _get_relation_models(cls) -> list[dict]:
        models = await get_relation_models()
        if not isinstance(models, list) or not models:
            return cls._default_relation_models()
        return [cls._normalize_model_dict(model) for model in models]

    @staticmethod
    def _default_relation_models() -> list[dict]:
        return [
            {
                "id": relation,
                "name": name,
                "relation": relation,
                "grant_tier": grant_tier,
                "permissions": list(default_permission_ids_for_relation(relation)),
                "permissions_explicit": False,
                "is_system": True,
            }
            for relation, name, grant_tier in (
                ("owner", "所有者", "owner"),
                ("manager", "可管理", "manager"),
                ("editor", "可编辑", "usage"),
                ("viewer", "可查看", "usage"),
            )
        ]

    @staticmethod
    def _normalize_model_dict(model: dict) -> dict:
        out = dict(model)
        relation = out.get("relation") or "viewer"
        out["relation"] = relation
        out["id"] = out.get("id") or relation
        out["name"] = out.get("name") or relation
        out["permissions"] = out.get("permissions") or list(default_permission_ids_for_relation(relation))
        out["permissions_explicit"] = bool(out.get("permissions_explicit", False))
        out["is_system"] = bool(out.get("is_system", False))
        if out.get("grant_tier") not in _GRANT_TIER_VALUES:
            out["grant_tier"] = "owner" if relation == "owner" else "manager" if relation == "manager" else "usage"
        return out

    async def _resolve_channel_tenant(self, channel_id: str, login_user: UserPayload) -> int | None:
        from bisheng.database.models.tenant import TenantDao

        try:
            tenant_id = await PermissionService._resolve_resource_tenant("channel", channel_id)
        except Exception:
            tenant_id = None
        resolved_id = int(tenant_id or getattr(login_user, "tenant_id", 0) or 0) or None
        if resolved_id is None:
            return None
        tenant = await TenantDao.aget_by_id(resolved_id)
        if tenant is None or getattr(tenant, "status", None) != "active":
            return None
        return resolved_id
