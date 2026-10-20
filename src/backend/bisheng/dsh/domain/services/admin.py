"""Administrative aggregation for native sessions, model quotas and audit history."""

from datetime import timedelta

from bisheng.common.errcode.dsh import (
    DshAuthorizationUnavailableError,
    DshInvalidRequestError,
    DshOperationConflictError,
)
from bisheng.dsh.domain.schemas.admin import (
    ModelUserPermissionPage,
    SubjectPolicyInventory,
    SubjectPolicyUpdateResult,
    UsageOverviewPage,
)
from bisheng.dsh.domain.services.profile import profile_scope


class DshManagementService:
    async def model_vision(self, actor_id, model_id, setting=None):
        from loguru import logger

        from bisheng.core.context.tenant import get_current_tenant_id
        from bisheng.dsh.domain.services.vision import configure_vision

        _actor, tenant = await self.authorize(actor_id, None)
        tenant = tenant if tenant is not None else get_current_tenant_id()
        if tenant is None:
            raise DshAuthorizationUnavailableError()
        with profile_scope(tenant):
            result = await configure_vision(model_id, setting)
        if setting is not None:
            logger.info(
                "DSH model capability saved: actor={} tenant={} model={} vision={}",
                actor_id,
                tenant,
                model_id,
                result["vision"],
            )
        return result

    def __init__(
        self,
        *,
        repository_scope,
        sessions=None,
        authorize,
        profiles,
        policy,
        policy_view,
        now,
        model_users_view=None,
        model_user_permissions_view=None,
        model_policy_view=None,
        usage_summary_view=None,
        usage_overview_view=None,
        subject_policy_view=None,
        audit_view=None,
        subject_grant=None,
    ):
        self.repository_scope, self.sessions_service, self.authorize = repository_scope, sessions, authorize
        self.profiles, self.policy, self.policy_view, self.now = profiles, policy, policy_view, now
        self.model_users_view = model_users_view
        self.model_user_permissions_view = model_user_permissions_view
        self.model_policy_view = model_policy_view
        self.usage_summary_view = usage_summary_view
        self.usage_overview_view = usage_overview_view
        self.subject_policy_view = subject_policy_view
        self.audit_view = audit_view
        self.subject_grant = subject_grant

    async def audit_records(self, actor_id, *, tenant_id=None, cursor=None, limit=20, action=None, status=None):
        from bisheng.core.context.tenant import get_current_tenant_id
        from bisheng.dsh.domain.schemas.audit import AuditPage

        _actor, tenant = await self.authorize(actor_id, tenant_id)
        tenant = tenant if tenant is not None else get_current_tenant_id()
        if tenant is None or self.audit_view is None:
            raise DshAuthorizationUnavailableError()
        with profile_scope(tenant):
            result = await self.audit_view(cursor=cursor, limit=limit, action=action, status=status)
        return AuditPage.model_validate(result).model_dump(mode="json")

    async def model_subjects(self, actor_id, model_id, *, tenant_id=None):
        from bisheng.core.context.tenant import get_current_tenant_id

        _actor, tenant = await self.authorize(actor_id, tenant_id)
        tenant = tenant if tenant is not None else get_current_tenant_id()
        if tenant is None or self.subject_policy_view is None:
            raise DshAuthorizationUnavailableError()
        with profile_scope(tenant):
            result = await self.subject_policy_view(model_id)
        return SubjectPolicyInventory.model_validate(result).model_dump()

    async def update_subject_policy(
        self,
        actor_id,
        model_id,
        subject_type,
        subject_id,
        request,
        *,
        tenant_id=None,
    ):
        from bisheng.core.context.tenant import get_current_tenant_id

        actor, tenant = await self.authorize(actor_id, tenant_id)
        tenant = tenant if tenant is not None else get_current_tenant_id()
        if tenant is None or self.subject_grant is None:
            raise DshAuthorizationUnavailableError()
        with profile_scope(tenant):
            if self.subject_grant is None:
                raise DshAuthorizationUnavailableError()
            result = await self.subject_grant(
                actor=actor,
                tenant=tenant,
                actor_id=actor_id,
                model_id=model_id,
                subject_type=subject_type,
                subject_id=subject_id,
                request=request,
            )
        return SubjectPolicyUpdateResult.model_validate(result).model_dump()

    async def model_users(
        self, actor_id, model_id, *, tenant_id=None, cursor=None, limit=20, keyword=None, authorized_only=False
    ):
        from bisheng.core.context.tenant import get_current_tenant_id

        _actor, tenant = await self.authorize(actor_id, tenant_id)
        tenant = tenant if tenant is not None else get_current_tenant_id()
        if tenant is None or self.model_users_view is None:
            raise DshAuthorizationUnavailableError()
        with profile_scope(tenant):
            return await self.model_users_view(
                model_id,
                after_user_id=int(cursor or 0),
                limit=limit,
                keyword=keyword or "",
                authorized_only=authorized_only,
            )

    async def model_user_permissions(
        self,
        actor_id,
        model_id,
        *,
        tenant_id=None,
        cursor=None,
        limit=20,
        keyword=None,
        department_id=None,
        membership="EFFECTIVE",
        unassigned_only=False,
        include_seats=False,
    ):
        from bisheng.core.context.tenant import get_current_tenant_id

        _actor, tenant = await self.authorize(actor_id, tenant_id)
        tenant = tenant if tenant is not None else get_current_tenant_id()
        if tenant is None or self.model_user_permissions_view is None:
            raise DshAuthorizationUnavailableError()
        with profile_scope(tenant):
            result = await self.model_user_permissions_view(
                model_id,
                after_user_id=int(cursor or 0),
                limit=limit,
                keyword=keyword or "",
                department_id=department_id,
                membership=membership,
                **({"unassigned_only": True} if unassigned_only else {}),
            )
        return ModelUserPermissionPage.model_validate(result).model_dump()

    async def get_policy(self, actor_id, user_id, *, tenant_id=None):
        _actor, tenant = await self.authorize(actor_id, tenant_id, user_id)
        with profile_scope(tenant):
            return await self.policy_view(user_id)

    async def usage_summary(self, actor_id, user_id, *, start_at, end_at, tenant_id=None, granularity=None):
        if (
            start_at.tzinfo is None
            or end_at.tzinfo is None
            or end_at <= start_at
            or end_at - start_at > timedelta(days=366)
            or granularity not in (None, "hour", "day")
            or (granularity == "hour" and end_at - start_at > timedelta(days=7))
        ):
            raise DshInvalidRequestError()
        _actor, tenant = await self.authorize(actor_id, tenant_id, user_id)
        if self.usage_summary_view is None:
            raise DshAuthorizationUnavailableError()
        granularity = granularity or ("hour" if end_at - start_at <= timedelta(hours=48) else "day")
        with profile_scope(tenant):
            return await self.usage_summary_view(user_id, start_at, end_at, granularity)

    async def usage_overview(
        self,
        actor_id,
        *,
        start_at,
        end_at,
        tenant_id=None,
        cursor=None,
        limit=20,
        keyword=None,
        department_id=None,
        include_summary=False,
        granularity=None,
    ):
        from bisheng.core.context.tenant import get_current_tenant_id

        if (
            start_at.tzinfo is None
            or end_at.tzinfo is None
            or end_at <= start_at
            or end_at - start_at > timedelta(days=366)
            or granularity not in (None, "hour", "day")
            or (granularity == "hour" and end_at - start_at > timedelta(days=7))
        ):
            raise DshInvalidRequestError()
        _actor, tenant = await self.authorize(actor_id, tenant_id)
        tenant = tenant if tenant is not None else get_current_tenant_id()
        if tenant is None or self.usage_overview_view is None:
            raise DshAuthorizationUnavailableError()
        with profile_scope(tenant):
            result = await self.usage_overview_view(
                start_at=start_at,
                end_at=end_at,
                after_user_id=int(cursor or 0),
                limit=limit,
                keyword=keyword or "",
                department_id=department_id,
                include_summary=include_summary,
                granularity=granularity,
            )
        return UsageOverviewPage.model_validate(result).model_dump()

    async def get_model_policy(self, actor_id, user_id, model_id, *, tenant_id=None):
        _actor, tenant = await self.authorize(actor_id, tenant_id, user_id)
        with profile_scope(tenant):
            return await self.model_policy_view(user_id, model_id)

    async def update_policy(self, actor_id, user_id, request, *, model_id: int, tenant_id=None):
        _actor, tenant = await self.authorize(actor_id, tenant_id, user_id)
        with profile_scope(tenant):
            return await self.policy.update_policy(
                user_id=user_id,
                actor_user_id=actor_id,
                model_id=model_id,
                request=request,
            )

    def _read(self, operation_id):
        with self.repository_scope() as repository:
            operation = repository.get(operation_id)
            if operation is None:
                raise DshOperationConflictError()
            return operation.model_dump()

    async def operation(self, actor_id, operation_id, *, tenant_id=None):
        actor, tenant = await self.authorize(actor_id, tenant_id)
        if tenant is None:
            if actor["scope"] != "instance":
                raise DshOperationConflictError()
            with self.repository_scope() as repository:
                tenant = repository.locate_instance_operation(operation_id)
        with profile_scope(tenant):
            return self._read(operation_id)

    async def sessions(self, actor_id, user_id, *, tenant_id=None, cursor=None, limit=50):
        _actor, tenant = await self.authorize(actor_id, tenant_id, user_id)
        if self.sessions_service is None:
            raise DshAuthorizationUnavailableError()
        return await self.sessions_service.page(tenant, user_id, cursor=cursor, limit=limit)
