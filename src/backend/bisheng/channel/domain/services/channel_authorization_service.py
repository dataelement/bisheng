from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from contextlib import AsyncExitStack, asynccontextmanager

from loguru import logger
from sqlmodel import col, select

from bisheng.channel.domain.schemas.channel_authorization_schema import (
    ChannelAuthorizationItemResult,
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
from bisheng.common.errcode.approval import ApprovalScenarioDisabledError
from bisheng.common.errcode.base import BaseErrorCode
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
from bisheng.permission.domain.ports.resource_grant_executor import (
    ResourceGrantCommand,
    ResourceGrantVerificationResult,
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
from bisheng.permission.domain.services.relation_binding_mutation_service import (
    RelationBindingMutationService,
)
from bisheng.permission.domain.services.relation_model_store import (
    get_bindings,
    get_relation_models,
    normalize_model_dict,
    save_bindings,
)
from bisheng.permission.domain.services.resource_permission_notification_service import (
    ResourcePermissionNotificationService,
)

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


def _canonical_role_snapshot(snapshot) -> tuple[dict, str]:
    def thaw(value):
        if isinstance(value, Mapping):
            return {str(key): thaw(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [thaw(item) for item in value]
        if isinstance(value, (set, frozenset)):
            return [thaw(item) for item in sorted(value, key=repr)]
        return value

    canonical = json.dumps(
        thaw(snapshot),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    normalized = json.loads(canonical)
    if not isinstance(normalized, dict):
        raise ChannelPermissionDeniedError(msg="邀请角色快照无效")
    return normalized, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
        invite_application_service=None,
        relation_binding_mutation_service: RelationBindingMutationService | None = None,
    ):
        self.channel_repository = channel_repository
        self.space_channel_member_repository = space_channel_member_repository
        self.membership_sync_service = membership_sync_service or ChannelMembershipSyncService(
            space_channel_member_repository,
        )
        self.grant_subject_query_service = grant_subject_query_service or GrantSubjectQueryService()
        self._invite_application_service = invite_application_service
        self.relation_binding_mutation_service = relation_binding_mutation_service or RelationBindingMutationService(
            get_bindings=self._load_bindings_for_mutation,
            save_bindings=self._save_bindings_for_mutation,
        )

    def _get_invite_application_service(self):
        if self._invite_application_service is not None:
            return self._invite_application_service
        from bisheng.permission.domain.services.resource_user_invite_application_service import (
            build_runtime_resource_user_invite_application_service,
        )

        self._invite_application_service = build_runtime_resource_user_invite_application_service()
        return self._invite_application_service

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
    async def invite_scenario_guard_for_grants(
        self,
        grants: list[ChannelGrantItem],
        *,
        tenant_id: int,
    ):
        if any(item.subject_type == "user" for item in grants):
            async with self._invite_scenario_guard(tenant_id=int(tenant_id)):
                yield
            return
        yield

    async def authorize_channel(
        self,
        channel_id: str,
        request: ChannelAuthorizeRequest,
        login_user: UserPayload,
        *,
        scenario_guarded: bool = False,
    ) -> ChannelAuthorizeResponse:
        channel = await self._ensure_channel(channel_id)
        self._reject_creator_permission_change(channel, request)
        actor_permissions = await self._actor_grant_permissions(channel_id, login_user)
        self._validate_request(actor_permissions, request)
        user_grants = [item for item in request.grants if item.subject_type == "user"]
        active_user_ids = await self._active_explicit_user_ids(channel_id) if user_grants else set()
        invite_grants = [
            item
            for item in request.grants
            if item.subject_type == "user" and int(item.subject_id) not in active_user_ids
        ]
        invite_ids = {id(item) for item in invite_grants}
        direct_request = ChannelAuthorizeRequest(
            grants=[item for item in request.grants if id(item) not in invite_ids],
            revokes=list(request.revokes),
        )
        tenant_id = await self._channel_tenant_id(channel, login_user)
        if tenant_id is None:
            raise ChannelPermissionDeniedError()

        async with AsyncExitStack() as stack:
            if invite_grants and not scenario_guarded:
                await stack.enter_async_context(
                    self._invite_scenario_guard(tenant_id=tenant_id),
                )

            await self._validate_subjects_belong_to_channel_tenant(
                channel,
                direct_request,
                login_user,
            )
            results: list[ChannelAuthorizationItemResult] = []
            if direct_request.grants or direct_request.revokes:
                await self._apply_direct_authorization(
                    channel_id,
                    direct_request,
                    login_user,
                )
                results.extend(self._direct_results(direct_request))

            resource_name = str(getattr(channel, "name", "") or "")
            for grant in invite_grants:
                results.append(
                    await self._request_personal_user_invite(
                        tenant_id=tenant_id,
                        channel_id=channel_id,
                        resource_name=resource_name,
                        grant=grant,
                        login_user=login_user,
                    )
                )

            return self._authorization_response(results)

    async def _apply_direct_authorization(
        self,
        channel_id: str,
        request: ChannelAuthorizeRequest,
        login_user: UserPayload,
    ) -> None:
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

        async with self.relation_binding_mutation_service.transaction() as transaction:
            transaction.ensure_owned()
            updated_bindings = self._binding_changes_from_snapshot(
                channel_id,
                request,
                transaction.bindings,
            )
            try:
                await PermissionService.authorize(
                    object_type="channel",
                    object_id=channel_id,
                    grants=tuple_grants,
                    revokes=tuple_revokes,
                    enforce_fga_success=True,
                    recovery_owner="caller",
                )
            except (FGAConnectionError, FGAWriteError) as exc:
                logger.exception(
                    "channel authorization tuple write failed: channel_id={}",
                    channel_id,
                )
                raise ChannelAuthorizationSyncError(exception=exc) from exc

            try:
                await transaction.commit(updated_bindings)
            except Exception as binding_error:
                compensation_error = None
                try:
                    await self._compensate_permission_write(
                        channel_id,
                        request,
                        transaction.snapshot,
                    )
                except Exception as error:
                    compensation_error = error
                    logger.exception(
                        "channel direct authorization compensation failed: channel_id={}",
                        channel_id,
                    )
                restore_error = None
                try:
                    await transaction.restore()
                except Exception as error:
                    restore_error = error
                    logger.exception(
                        "channel direct authorization binding restore failed: channel_id={}",
                        channel_id,
                    )
                if compensation_error is not None or restore_error is not None:
                    failure = compensation_error or restore_error
                    raise ChannelAuthorizationSyncError(exception=failure) from failure
                logger.exception("channel authorization sync failed: channel_id={}", channel_id)
                raise ChannelAuthorizationSyncError(exception=binding_error) from binding_error

        await ResourcePermissionNotificationService.dispatch_after_authorize(
            context=notify_context,
            operator_user_id=login_user.user_id,
            operator_user_name=getattr(login_user, "user_name", None),
        )

    async def ensure_invite_scenario_available_for_grants(
        self,
        grants: list[ChannelGrantItem],
        *,
        tenant_id: int,
    ) -> None:
        if any(item.subject_type == "user" for item in grants):
            invite_service = self._get_invite_application_service()
            availability_check = getattr(invite_service, "ensure_scenario_available", None)
            if availability_check is not None:
                await availability_check(tenant_id=tenant_id)
                return
            async with self._invite_scenario_guard(tenant_id=tenant_id):
                return

    async def _active_explicit_user_ids(self, channel_id: str) -> set[int]:
        permissions = await PermissionService.get_resource_permissions("channel", channel_id)
        return {int(item.subject_id) for item in permissions if item.subject_type == "user"}

    async def _request_personal_user_invite(
        self,
        *,
        tenant_id: int,
        channel_id: str,
        resource_name: str,
        grant: ChannelGrantItem,
        login_user: UserPayload,
    ) -> ChannelAuthorizationItemResult:
        try:
            if not await self._users_belong_to_tenant({int(grant.subject_id)}, tenant_id):
                raise ChannelPermissionDeniedError()
            target_name = await self._target_user_name(int(grant.subject_id))
            role_snapshot = await self._role_snapshot(grant)
            outcome = await self._get_invite_application_service().request_invite(
                tenant_id=tenant_id,
                resource_type="channel",
                resource_id=str(channel_id),
                resource_name=resource_name,
                inviter_user_id=int(login_user.user_id),
                inviter_user_name=str(getattr(login_user, "user_name", "") or ""),
                target_user_id=int(grant.subject_id),
                target_user_name=target_name,
                relation=ChannelRelationEnum(grant.relation).value,
                model_id=grant.model_id or ChannelRelationEnum(grant.relation).value,
                role_snapshot=role_snapshot,
                include_children=False,
            )
            payload = {
                "operation": "grant",
                "subject_type": "user",
                "subject_id": int(grant.subject_id),
                "relation": ChannelRelationEnum(grant.relation).value,
                "model_id": grant.model_id or ChannelRelationEnum(grant.relation).value,
                **outcome,
            }
            return ChannelAuthorizationItemResult.model_validate(payload)
        except ApprovalScenarioDisabledError:
            raise
        except BaseErrorCode as exc:
            return self._failed_result(grant, exc.code, exc.message)
        except Exception:
            logger.exception(
                "channel personal user invite failed: channel_id={} target_user_id={}",
                channel_id,
                grant.subject_id,
            )
            return self._failed_result(
                grant,
                ChannelAuthorizationSyncError.Code,
                ChannelAuthorizationSyncError.Msg,
            )

    async def _target_user_name(self, user_id: int) -> str:
        from bisheng.user.domain.models.user import UserDao

        user = await UserDao.aget_user(user_id)
        if user is None or getattr(user, "delete", 0):
            raise ChannelPermissionDeniedError()
        return str(getattr(user, "user_name", "") or user_id)

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
        from bisheng.core.context.tenant import get_current_tenant_id

        current_tenant_id = get_current_tenant_id()
        if current_tenant_id is None or int(current_tenant_id) != int(tenant_id):
            raise ValueError("channel resource grant requires the matching tenant context")
        channel = await self._ensure_channel(resource_id)
        channel_tenant_id = await self._channel_tenant_id(
            channel,
            UserPayload(
                user_id=inviter_user_id,
                user_name="",
                tenant_id=tenant_id,
                user_role=[],
            ),
        )
        if channel_tenant_id != int(tenant_id):
            raise ChannelPermissionDeniedError()
        if str(getattr(channel, "visibility", "public")) in {"private", "ChannelVisibilityEnum.PRIVATE"}:
            raise ChannelPermissionDeniedError()
        creator_id = getattr(channel, "user_id", None)
        if creator_id is not None and int(creator_id) == int(target_user_id):
            raise ChannelPermissionDeniedError(msg="无法修改频道创建人的权限")
        if not await self._users_belong_to_tenant(
            {int(inviter_user_id), int(target_user_id)},
            int(tenant_id),
        ):
            raise ChannelPermissionDeniedError()

        inviter_name = await self._target_user_name(int(inviter_user_id))
        await self._target_user_name(int(target_user_id))

        inviter = UserPayload(
            user_id=int(inviter_user_id),
            user_name=inviter_name,
            tenant_id=int(tenant_id),
            user_role=[],
        )
        actor_permissions = await self._actor_grant_permissions(resource_id, inviter)
        grant = ChannelGrantItem(
            subject_type="user",
            subject_id=int(target_user_id),
            relation=ChannelRelationEnum(relation),
            include_children=include_children,
            model_id=model_id or relation,
        )
        confirmed_request = ChannelAuthorizeRequest(grants=[grant], revokes=[])
        self._validate_request(actor_permissions, confirmed_request)

        current_snapshot = await self._role_snapshot(grant)
        normalized_snapshot, snapshot_fingerprint = _canonical_role_snapshot(role_snapshot)
        if snapshot_fingerprint != role_fingerprint or current_snapshot != normalized_snapshot:
            raise ChannelPermissionDeniedError(msg="邀请角色已变更, 请重新邀请")

        permission_grant = self._to_permission_grant(grant)
        existing_permissions = await PermissionService.get_resource_permissions(
            "channel",
            resource_id,
        )
        existing_target_permissions = [
            item
            for item in existing_permissions
            if item.subject_type == "user" and int(item.subject_id) == int(target_user_id)
        ]
        notify_context = await ResourcePermissionNotificationService.build_context(
            resource_type="channel",
            resource_id=resource_id,
            grants=[permission_grant],
            revokes=[],
        )
        async with self.relation_binding_mutation_service.transaction() as transaction:
            transaction.ensure_owned()
            binding_map = {item.get("key"): item for item in transaction.bindings if item.get("key")}
            existing_binding = self._binding_from_map(
                binding_map,
                resource_id,
                "user",
                int(target_user_id),
                relation,
                False,
            )
            if existing_target_permissions:
                is_exact = (
                    len(existing_target_permissions) == 1
                    and existing_target_permissions[0].relation == relation
                    and existing_binding is not None
                    and (existing_binding.get("model_id") == (model_id or relation))
                )
                if is_exact:
                    return
                raise ChannelPermissionDeniedError(msg="目标用户已有不同的个人权限, 请重新邀请")
            updated = self._binding_changes_from_snapshot(
                resource_id,
                confirmed_request,
                transaction.bindings,
            )
            try:
                await PermissionService.authorize(
                    object_type="channel",
                    object_id=resource_id,
                    grants=[permission_grant],
                    revokes=[],
                    enforce_fga_success=True,
                    recovery_owner="caller",
                )
            except Exception as write_error:
                refreshed = await PermissionService.get_resource_permissions("channel", resource_id)
                refreshed_target = [
                    item
                    for item in refreshed
                    if item.subject_type == "user" and int(item.subject_id) == int(target_user_id)
                ]
                if len(refreshed_target) == 1 and refreshed_target[0].relation == relation:
                    await self._commit_confirmed_grant_binding(
                        transaction=transaction,
                        updated=updated,
                        resource_id=resource_id,
                        target_user_id=target_user_id,
                        relation=relation,
                        model_id=model_id,
                        approval_instance_id=approval_instance_id,
                    )
                else:
                    try:
                        await transaction.restore()
                    except Exception as recovery_error:
                        raise ChannelAuthorizationSyncError(exception=recovery_error) from recovery_error
                raise write_error
            await self._commit_confirmed_grant_binding(
                transaction=transaction,
                updated=updated,
                resource_id=resource_id,
                target_user_id=target_user_id,
                relation=relation,
                model_id=model_id,
                approval_instance_id=approval_instance_id,
            )

        try:
            await ResourcePermissionNotificationService.dispatch_after_authorize(
                context=notify_context,
                operator_user_id=int(inviter_user_id),
                operator_user_name=inviter_name,
            )
        except Exception:
            # Permission is already effective; notification delivery is best-effort.
            logger.exception(
                "confirmed channel grant notification failed: channel_id={} instance_id={}",
                resource_id,
                approval_instance_id,
            )

    @staticmethod
    async def _commit_confirmed_grant_binding(
        *,
        transaction,
        updated: list[dict],
        resource_id: str,
        target_user_id: int,
        relation: str,
        model_id: str | None,
        approval_instance_id: int,
    ) -> None:
        try:
            await transaction.commit(updated)
            return
        except Exception as binding_error:
            compensation_error = None
            try:
                await PermissionService.authorize(
                    object_type="channel",
                    object_id=resource_id,
                    grants=[],
                    revokes=[
                        AuthorizeRevokeItem(
                            subject_type="user",
                            subject_id=int(target_user_id),
                            relation=relation,
                            include_children=False,
                            model_id=model_id,
                        )
                    ],
                    enforce_fga_success=True,
                    recovery_owner="caller",
                )
            except Exception as error:
                compensation_error = error
                logger.exception(
                    "confirmed channel grant compensation failed: channel_id={} instance_id={}",
                    resource_id,
                    approval_instance_id,
                )
            restore_error = None
            try:
                await transaction.restore()
            except Exception as error:
                restore_error = error
                logger.exception(
                    "confirmed channel grant binding restore failed: channel_id={} instance_id={}",
                    resource_id,
                    approval_instance_id,
                )
            failure = compensation_error or restore_error or binding_error
            raise ChannelAuthorizationSyncError(exception=failure) from failure

    async def _role_snapshot(self, grant: ChannelGrantItem) -> dict:
        model_id = grant.model_id or ChannelRelationEnum(grant.relation).value
        models = [normalize_model_dict(item) for item in await self._get_relation_models()]
        model = next((item for item in models if item.get("id") == model_id), None)
        if model is None or model.get("relation") != ChannelRelationEnum(grant.relation).value:
            raise ChannelPermissionDeniedError()
        return {
            "name": model.get("name") or "",
            "relation": model.get("relation") or "",
            "grant_tier": self._model_grant_tier(model),
            "permissions": sorted(set(model.get("permissions") or [])),
            "permissions_explicit": bool(model.get("permissions_explicit", False)),
        }

    @staticmethod
    def _direct_results(request: ChannelAuthorizeRequest) -> list[ChannelAuthorizationItemResult]:
        return [
            ChannelAuthorizationItemResult(
                operation=operation,
                subject_type=item.subject_type,
                subject_id=int(item.subject_id),
                relation=item.relation,
                model_id=item.model_id,
                outcome="applied",
            )
            for operation, items in (("grant", request.grants), ("revoke", request.revokes))
            for item in items
        ]

    @staticmethod
    def _failed_result(
        grant: ChannelGrantItem,
        error_code: int,
        error_message: str,
    ) -> ChannelAuthorizationItemResult:
        return ChannelAuthorizationItemResult(
            operation="grant",
            subject_type=grant.subject_type,
            subject_id=int(grant.subject_id),
            relation=grant.relation,
            model_id=grant.model_id,
            outcome="failed",
            error_code=error_code,
            error_message=error_message,
        )

    @staticmethod
    def _authorization_response(
        results: list[ChannelAuthorizationItemResult],
    ) -> ChannelAuthorizeResponse:
        return ChannelAuthorizeResponse(
            synced_user_count=0,
            affected_member_count=0,
            direct_applied_count=sum(item.outcome == "applied" for item in results),
            invite_created_count=sum(item.outcome == "invite_created" for item in results),
            invite_existing_count=sum(item.outcome == "invite_existing" for item in results),
            failed_count=sum(item.outcome == "failed" for item in results),
            results=results,
        )

    async def list_permissions(self, channel_id: str, login_user: UserPayload) -> list[ChannelPermissionEntry]:
        await self._require_manage_access(channel_id, login_user)
        channel = await self._ensure_channel(channel_id)
        creator_id = int(channel.user_id) if getattr(channel, "user_id", None) is not None else None
        permissions = await PermissionService.get_resource_permissions("channel", channel_id)
        bindings = [
            b
            for b in await self._get_bindings()
            if b.get("resource_type") == "channel" and str(b.get("resource_id")) == str(channel_id)
        ]
        model_map = {m["id"]: m for m in await self._get_relation_models()}
        binding_map = {b.get("key"): b for b in bindings if b.get("key")}
        out: list[ChannelPermissionEntry] = []
        for item in permissions:
            binding = self._binding_from_map(
                binding_map,
                channel_id,
                item.subject_type,
                int(item.subject_id),
                item.relation,
                getattr(item, "include_children", None),
            )
            model_id = binding.get("model_id") if binding else getattr(item, "model_id", None)
            model = model_map.get(model_id) if model_id else None
            out.append(
                ChannelPermissionEntry(
                    subject_type=item.subject_type,
                    subject_id=int(item.subject_id),
                    subject_name=getattr(item, "subject_name", None),
                    subject_group_names=getattr(item, "subject_group_names", None),
                    subject_member_names=getattr(item, "subject_member_names", None),
                    relation=ChannelRelationEnum(item.relation),
                    include_children=binding.get("include_children")
                    if binding
                    else getattr(item, "include_children", None),
                    model_id=model_id,
                    model_name=model.get("name") if model else getattr(item, "model_name", None),
                    is_creator=(
                        item.subject_type == "user" and creator_id is not None and int(item.subject_id) == creator_id
                    ),
                    authorization_status="active",
                )
            )
        tenant_id = await self._channel_tenant_id(channel, login_user)
        if tenant_id is None:
            raise ChannelPermissionDeniedError()
        active_user_ids = {item.subject_id for item in out if item.subject_type == "user"}
        pending_instances = await self._get_invite_application_service().list_pending_invites(
            tenant_id=tenant_id,
            resource_type="channel",
            resource_id=str(channel_id),
        )
        for instance in pending_instances:
            try:
                target_user_id = int(instance.target_user_id)
                relation = ChannelRelationEnum(instance.relation)
            except (AttributeError, TypeError, ValueError):
                logger.warning(
                    "ignored malformed pending channel invite: channel_id={} instance_id={}",
                    channel_id,
                    getattr(instance, "id", None),
                )
                continue
            if target_user_id in active_user_ids:
                logger.warning(
                    "active channel permission wins over pending invite: channel_id={} target_user_id={}",
                    channel_id,
                    target_user_id,
                )
                continue
            pending_model_id = getattr(instance, "model_id", None) or relation.value
            pending_model = model_map.get(pending_model_id)
            out.append(
                ChannelPermissionEntry(
                    subject_type="user",
                    subject_id=target_user_id,
                    subject_name=getattr(instance, "target_user_name", None),
                    relation=relation,
                    include_children=None,
                    model_id=pending_model_id,
                    model_name=(
                        pending_model.get("name")
                        if pending_model
                        else (getattr(instance, "role_snapshot", None) or {}).get("name")
                    ),
                    is_creator=False,
                    authorization_status="pending",
                    approval_instance_id=getattr(instance, "approval_instance_id", None),
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
    ) -> ChannelRelationEnum | None:
        if login_user.is_admin():
            return ChannelRelationEnum.OWNER
        try:
            permission_ids = await FineGrainedPermissionService.get_effective_permission_ids_async(
                login_user,
                "channel",
                channel_id,
            )
            relation = relation_from_channel_permission_ids(permission_ids)
            if relation:
                return ChannelRelationEnum(relation)
        except Exception:
            logger.exception("failed to resolve channel permission ids: channel_id={}", channel_id)
        return await self.space_channel_member_repository.get_effective_channel_relation(
            channel_id,
            login_user.user_id,
        )

    async def _require_manage_access(self, channel_id: str, login_user: UserPayload) -> ChannelRelationEnum:
        actor_relation = await self._actor_relation(channel_id, login_user)
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
            logger.exception("failed to resolve channel permission ids: channel_id={}", channel_id)
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
        request: ChannelAuthorizeRequest,
        bindings_snapshot: list[dict],
    ) -> None:
        bindings_map = {binding.get("key"): binding for binding in bindings_snapshot if binding.get("key")}
        grants: list[AuthorizeGrantItem] = []
        revokes: list[AuthorizeRevokeItem] = []
        for item in request.revokes:
            original = cls._binding_from_map(
                bindings_map,
                channel_id,
                item.subject_type,
                item.subject_id,
                ChannelRelationEnum(item.relation).value,
                item.include_children,
            )
            if original is not None:
                grants.append(
                    AuthorizeGrantItem(
                        subject_type=item.subject_type,
                        subject_id=item.subject_id,
                        relation=ChannelRelationEnum(item.relation).value,
                        include_children=item.include_children,
                        model_id=original.get("model_id") or item.model_id,
                    )
                )
        for item in request.grants:
            original = cls._binding_from_map(
                bindings_map,
                channel_id,
                item.subject_type,
                item.subject_id,
                ChannelRelationEnum(item.relation).value,
                item.include_children,
            )
            if original is None:
                revokes.append(
                    AuthorizeRevokeItem(
                        subject_type=item.subject_type,
                        subject_id=item.subject_id,
                        relation=ChannelRelationEnum(item.relation).value,
                        include_children=item.include_children,
                        model_id=item.model_id,
                    )
                )
        if not grants and not revokes:
            return
        await PermissionService.authorize(
            object_type="channel",
            object_id=channel_id,
            grants=grants,
            revokes=revokes,
            enforce_fga_success=True,
            recovery_owner="caller",
        )

    async def _cleanup_grant_membership_sources(self, channel_id: str, binding_keys: list[str]) -> None:
        for binding_key in dict.fromkeys(binding_keys):
            await self.space_channel_member_repository.delete_channel_membership_source(
                channel_id,
                binding_key,
            )

    async def _restore_bindings(self, channel_id: str, bindings: list[dict]) -> None:
        try:
            await self.relation_binding_mutation_service.mutate(lambda _current: bindings)
        except Exception:
            logger.exception("channel authorization binding restore failed: channel_id={}", channel_id)
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
        await self.relation_binding_mutation_service.mutate(
            lambda current: self._binding_changes_from_snapshot(
                channel_id,
                request,
                current,
            )
        )

    def _binding_changes_from_snapshot(
        self,
        channel_id: str,
        request: ChannelAuthorizeRequest,
        bindings: list[dict],
    ) -> list[dict]:
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
        return list(bindings_map.values())

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
            logger.exception("failed to clear private-channel tuples: channel_id={}", channel_id)
            raise PermissionTupleWriteError(exception=error) from error

        try:
            removed = 0

            def remove_private_bindings(bindings: list[dict]) -> list[dict]:
                nonlocal removed
                remaining: list[dict] = []
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
                return remaining

            await cls._new_binding_mutation_service().mutate(remove_private_bindings)
        except PermissionTupleWriteError:
            raise
        except Exception as error:
            logger.exception("failed to clear private-channel bindings: channel_id={}", channel_id)
            raise PermissionTupleWriteError(exception=error) from error
        return removed

    @classmethod
    async def clear_non_owner_bindings(cls, channel_id: str) -> int:
        """Compatibility helper for callers that only revoke non-owner grants."""
        removed = 0

        def remove_non_owner_bindings(bindings: list[dict]) -> list[dict]:
            nonlocal removed
            remaining: list[dict] = []
            for binding in bindings:
                is_channel_binding = binding.get("resource_type") == "channel" and str(
                    binding.get("resource_id")
                ) == str(channel_id)
                if is_channel_binding and binding.get("relation") != ChannelRelationEnum.OWNER.value:
                    removed += 1
                    continue
                remaining.append(binding)
            return remaining

        await cls._new_binding_mutation_service().mutate(remove_non_owner_bindings)
        return removed

    @classmethod
    def _new_binding_mutation_service(cls) -> RelationBindingMutationService:
        return RelationBindingMutationService(
            get_bindings=cls._get_bindings,
            save_bindings=cls._save_bindings,
        )

    @staticmethod
    async def _get_bindings() -> list[dict]:
        return await get_bindings()

    @staticmethod
    async def _save_bindings(bindings: list[dict]) -> None:
        await save_bindings(bindings)

    async def _load_bindings_for_mutation(self) -> list[dict]:
        return await self._get_bindings()

    async def _save_bindings_for_mutation(self, bindings: list[dict]) -> None:
        await self._save_bindings(bindings)

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


class ChannelResourceGrantExecutor:
    """Channel owner adapter for Permission's stable resource grant port."""

    resource_type = "channel"

    def __init__(self, *, authorization_service: ChannelAuthorizationService) -> None:
        self.authorization_service = authorization_service

    async def execute(self, command: ResourceGrantCommand) -> None:
        self._require_command_context(command)
        await self.authorization_service.apply_confirmed_personal_user_grant(
            tenant_id=command.tenant_id,
            resource_id=command.resource_id,
            inviter_user_id=command.inviter_user_id,
            target_user_id=command.target_user_id,
            relation=command.relation,
            model_id=command.model_id,
            role_snapshot=dict(command.role_snapshot),
            role_fingerprint=command.role_fingerprint,
            include_children=command.include_children,
            approval_instance_id=command.request_id,
        )

    async def verify(
        self,
        command: ResourceGrantCommand,
    ) -> ResourceGrantVerificationResult:
        self._require_command_context(command)
        service = self.authorization_service
        channel = await service._ensure_channel(command.resource_id)
        tenant_id = await service._channel_tenant_id(
            channel,
            UserPayload(
                user_id=command.inviter_user_id,
                user_name="",
                tenant_id=command.tenant_id,
                user_role=[],
            ),
        )
        if tenant_id != command.tenant_id:
            raise ChannelPermissionDeniedError()
        if str(getattr(channel, "visibility", "public")) in {
            "private",
            "ChannelVisibilityEnum.PRIVATE",
        }:
            raise ChannelPermissionDeniedError()
        creator_id = getattr(channel, "user_id", None)
        if creator_id is not None and int(creator_id) == command.target_user_id:
            raise ChannelPermissionDeniedError(msg="无法修改频道创建人的权限")
        if not await service._users_belong_to_tenant(
            {command.inviter_user_id, command.target_user_id},
            command.tenant_id,
        ):
            raise ChannelPermissionDeniedError()

        inviter_name = await service._target_user_name(command.inviter_user_id)
        await service._target_user_name(command.target_user_id)
        inviter = UserPayload(
            user_id=command.inviter_user_id,
            user_name=inviter_name,
            tenant_id=command.tenant_id,
            user_role=[],
        )
        actor_permissions = await service._actor_grant_permissions(command.resource_id, inviter)
        grant = ChannelGrantItem(
            subject_type="user",
            subject_id=command.target_user_id,
            relation=ChannelRelationEnum(command.relation),
            include_children=command.include_children,
            model_id=command.model_id or command.relation,
        )
        service._validate_request(
            actor_permissions,
            ChannelAuthorizeRequest(grants=[grant], revokes=[]),
        )
        normalized_snapshot, fingerprint = _canonical_role_snapshot(command.role_snapshot)
        current_snapshot = await service._role_snapshot(grant)
        if fingerprint != command.role_fingerprint or normalized_snapshot != current_snapshot:
            raise ChannelPermissionDeniedError(msg="邀请角色已变更, 请重新邀请")

        permissions = await PermissionService.get_resource_permissions("channel", command.resource_id)
        target_permissions = [
            item
            for item in permissions
            if item.subject_type == "user" and int(item.subject_id) == command.target_user_id
        ]
        bindings = await service._get_bindings()
        binding_map = {item.get("key"): item for item in bindings if item.get("key")}
        binding = service._binding_from_map(
            binding_map,
            command.resource_id,
            "user",
            command.target_user_id,
            command.relation,
            False,
        )
        applied = (
            len(target_permissions) == 1
            and target_permissions[0].relation == command.relation
            and binding is not None
            and binding.get("model_id") == (command.model_id or command.relation)
        )
        return ResourceGrantVerificationResult(
            applied=applied,
            result_snapshot={
                "request_id": command.request_id,
                "resource_type": self.resource_type,
                "resource_id": command.resource_id,
                "target_user_id": command.target_user_id,
                "relation": command.relation,
                "model_id": command.model_id or command.relation,
            },
        )

    def _require_command_context(self, command: ResourceGrantCommand) -> None:
        from bisheng.core.context.tenant import get_current_tenant_id

        if command.resource_type != self.resource_type:
            raise ValueError("channel resource grant resource_type mismatch")
        tenant_id = get_current_tenant_id()
        if tenant_id is None or int(tenant_id) != command.tenant_id:
            raise ValueError("channel resource grant requires the matching tenant context")
