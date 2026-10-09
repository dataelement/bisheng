"""Administrative aggregation with durable, actor-bound Gateway commands."""

from datetime import timedelta
from uuid import UUID

from fastapi import HTTPException

from bisheng.common.errcode.dsh import (
    DshAuthorizationUnavailableError,
    DshDshDisabledError,
    DshInvalidRequestError,
    DshLicenseExpiredError,
    DshLicenseInvalidError,
    DshOperationConflictError,
    DshOperationInProgressError,
)
from bisheng.dsh.domain.schemas.admin import (
    CommandResult,
    LicenseSnapshot,
    ModelUserPermissionPage,
    SeatItem,
    SessionItem,
    SubjectPolicyInventory,
    SubjectPolicyUpdateResult,
    UsageOverviewPage,
)
from bisheng.dsh.domain.services.profile import profile_scope
from bisheng.dsh.infrastructure.gateway_client import GatewayCommandRejected


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
        gateway,
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
        self.repository_scope, self.gateway, self.authorize = repository_scope, gateway, authorize
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

        actor, tenant = await self.authorize(actor_id, tenant_id)
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
        if include_seats:
            from bisheng.dsh.domain.services.access_status import read_access_statuses

            statuses = await read_access_statuses(
                result["items"],
                tenant=tenant,
                actor=actor,
                snapshot=self._license_snapshot,
                request=self._request,
            )
            for row in result["items"]:
                row["access_status"] = statuses[row["user_id"]]
        return ModelUserPermissionPage.model_validate(result).model_dump()

    async def _request(self, operation, payload):
        try:
            result = await self.gateway.request(operation, payload)
            if not isinstance(result, dict):
                raise ValueError("Invalid management response")
            return result
        except GatewayCommandRejected:
            raise
        except Exception:
            raise DshAuthorizationUnavailableError() from None

    @staticmethod
    def _page(result):
        if (
            set(result) != {"items", "next_cursor", "has_more"}
            or not isinstance(result.get("items"), list)
            or type(result.get("has_more")) is not bool
            or not (result.get("next_cursor") is None or isinstance(result["next_cursor"], str))
        ):
            raise DshAuthorizationUnavailableError()
        if result["has_more"] and not result["next_cursor"]:
            raise DshAuthorizationUnavailableError()
        return result

    async def users(
        self,
        actor_id,
        *,
        tenant_id=None,
        cursor=None,
        limit=50,
        keyword=None,
        seat_state=None,
        user_id=None,
        login_state=None,
    ):
        from bisheng.dsh.domain.services.seat_pages import read_seat_page

        actor, target_tenant = await self.authorize(actor_id, tenant_id, user_id)
        target = {"tenant_id": str(target_tenant) if target_tenant else None}
        if user_id is not None:
            target["user_id"] = str(user_id)
        result = self._page(
            await read_seat_page(
                self._request,
                actor=actor,
                target=target,
                cursor=cursor,
                limit=limit,
                keyword=keyword,
                seat_state=seat_state,
                login_state=login_state,
            )
        )
        try:
            result["items"] = [SeatItem.model_validate(row).model_dump() for row in result["items"]]
            if target_tenant is not None and any(int(row["tenant_id"]) != target_tenant for row in result["items"]):
                raise ValueError("Foreign tenant in management page")
            if user_id is not None and any(int(row["user_id"]) != user_id for row in result["items"]):
                raise ValueError("Foreign user in seat lookup")
            ids = [int(row["user_id"]) for row in result["items"]]
            if len(ids) > limit or len(set(ids)) != len(ids):
                raise ValueError()
            snapshots = await self.profiles(ids)
            for row in result["items"]:
                row["department_name"] = None
                snapshot = snapshots.get(int(row["user_id"]))
                # Cross-tenant moves never relocate a historical seat or its grant.
                if snapshot and str(snapshot["tenant_id"]) == str(row["tenant_id"]):
                    row.update(
                        {
                            key: snapshot[key]
                            for key in ("username", "display_name", "profile_version", "department_name")
                            if key in snapshot
                        }
                    )
        except Exception:
            raise DshAuthorizationUnavailableError() from None
        return {**result, "as_of": self.now().isoformat() + "Z"}

    async def license(self, actor_id, *, tenant_id=None):
        actor, target_tenant = await self.authorize(actor_id, tenant_id)
        result = await self._license_snapshot(actor, target_tenant)
        return {
            **result,
            "used": result["assigned"],
            "limit": result["seat_limit"],
            "valid_until": result.get("expires_at"),
        }

    async def _license_snapshot(self, actor, target_tenant):
        result = await self._request(
            "management",
            {
                "resource": "license",
                "actor": actor,
                "target": {"tenant_id": str(target_tenant) if target_tenant else None},
            },
        )
        try:
            result = LicenseSnapshot.model_validate(result).model_dump()
            if result["available"] != max(0, result["seat_limit"] - result["assigned"]):
                raise ValueError("Inconsistent seat availability")
        except ValueError:
            raise DshAuthorizationUnavailableError() from None
        return result

    async def _grant_seat_limit(self, actor, target_tenant) -> int:
        snapshot = await self._license_snapshot(actor, target_tenant)
        status_errors = {
            "license_invalid": DshLicenseInvalidError,
            "license_expired": DshLicenseExpiredError,
            "dsh_disabled": DshDshDisabledError,
        }
        error = status_errors.get(snapshot["status"])
        if error is not None:
            raise error()
        return snapshot["seat_limit"]

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
                seat_limit=None,
            )

    async def sessions(self, actor_id, user_id, *, tenant_id=None, cursor=None, limit=50):
        actor, tenant = await self.authorize(actor_id, tenant_id, user_id)
        target = {"tenant_id": str(tenant), "user_id": str(user_id)}
        for state in ("ASSIGNED", "REVOKED"):
            page = self._page(
                await self._request(
                    "management",
                    {
                        "resource": "seats",
                        "actor": actor,
                        "target": target,
                        "limit": 1,
                        "cursor": None,
                        "seat_state": state,
                    },
                )
            )
            if page["items"]:
                seat = page["items"][0]
                if str(seat["user_id"]) != str(user_id) or str(seat["tenant_id"]) != str(tenant):
                    raise DshAuthorizationUnavailableError()
                target["seat_id"] = seat["seat_id"]
                break
        if "seat_id" not in target:
            return {"items": [], "next_cursor": None, "has_more": False}
        result = self._page(
            await self._request(
                "management",
                {"resource": "sessions", "actor": actor, "target": target, "limit": limit, "cursor": cursor},
            )
        )

        try:
            result["items"] = [SessionItem.model_validate(row).model_dump() for row in result["items"]]
            if len(result["items"]) > limit or any(row["seat_id"] != target["seat_id"] for row in result["items"]):
                raise ValueError("Foreign seat in session page")
        except ValueError:
            raise DshAuthorizationUnavailableError() from None
        return result

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

    async def command(self, actor_id, user_id, action, operation_id, expected_grant_version, *, tenant_id=None):
        try:
            if str(UUID(operation_id)) != operation_id:
                raise ValueError("Use a canonical UUID")
        except (ValueError, TypeError, AttributeError):
            raise DshInvalidRequestError() from None
        actor, tenant = await self.authorize(actor_id, tenant_id, user_id)
        payload = {
            "operation_id": operation_id,
            "actor": actor,
            "target": {"tenant_id": str(tenant), "user_id": str(user_id)},
            "expected_grant_version": expected_grant_version,
        }
        with profile_scope(tenant):
            with self.repository_scope() as repository:
                repository.register_intent(
                    operation_id=operation_id,
                    user_id=user_id,
                    actor_user_id=actor_id,
                    action=action,
                    payload=payload,
                    expected_grant_version=expected_grant_version,
                )
            return await self.resume(operation_id)

    async def resume(self, operation_id):
        current = self._read(operation_id)
        if current["action"] not in {"REVOKE", "REASSIGN"}:
            raise DshOperationConflictError()
        if current["status"] in {"SUCCEEDED", "FAILED"}:
            return current
        try:
            with self.repository_scope() as repository:
                operation = repository.claim(operation_id, now=self.now())
                generation, attempts, payload = operation.lease_generation, operation.attempts, dict(operation.payload)
        except DshOperationInProgressError:
            return self._read(operation_id)
        try:
            result = None
            if attempts > 1:
                result = CommandResult.model_validate(
                    await self._request("operation", {"operation_id": operation_id})
                ).model_dump()
                if result.get("operation_id") != operation_id or result.get("status") not in {
                    "UNKNOWN",
                    "SUCCEEDED",
                    "FAILED",
                }:
                    raise DshAuthorizationUnavailableError()
            if result is None or result["status"] == "UNKNOWN":
                try:
                    await self.authorize(current["actor_user_id"], current["tenant_id"], current["user_id"])
                except HTTPException as error:
                    if error.status_code != 403:
                        raise
                    with self.repository_scope() as repository:
                        repository.finish(
                            operation_id,
                            generation,
                            now=self.now(),
                            status="FAILED",
                            result={
                                "operation_id": operation_id,
                                "status": "FAILED",
                                "result_grant_version": None,
                                "result_code": "permission_denied",
                            },
                            code="permission_denied",
                        )
                    return self._read(operation_id)
            # A lookup by ID alone cannot prove the actor, target, action or version.
            # Replaying the exact stored intent lets Gateway verify its durable hash.
            result = CommandResult.model_validate(await self._request(current["action"].lower(), payload)).model_dump()
            if result.get("operation_id") != operation_id or result.get("status") not in {"SUCCEEDED", "FAILED"}:
                raise DshAuthorizationUnavailableError()
            if result["status"] == "SUCCEEDED" and (
                type(result.get("result_grant_version")) is not int
                or result["result_grant_version"] <= current["expected_grant_version"]
            ):
                raise DshAuthorizationUnavailableError()
            with self.repository_scope() as repository:
                repository.finish(
                    operation_id,
                    generation,
                    now=self.now(),
                    status=result["status"],
                    result=result,
                    code=result.get("result_code"),
                )
        except GatewayCommandRejected:
            with self.repository_scope() as repository:
                repository.finish(
                    operation_id,
                    generation,
                    now=self.now(),
                    status="FAILED",
                    result={
                        "operation_id": operation_id,
                        "status": "FAILED",
                        "result_grant_version": None,
                        "result_code": "authorization_conflict",
                    },
                    code="authorization_conflict",
                )
        except Exception:
            with self.repository_scope() as repository:
                repository.retry(
                    operation_id,
                    generation,
                    now=self.now(),
                    code="authorization_unavailable",
                    retry_at=self.now() + timedelta(seconds=30),
                )
        return self._read(operation_id)
