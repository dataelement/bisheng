"""Administrative aggregation with durable, actor-bound Gateway commands."""

from datetime import timedelta
from uuid import UUID

from fastapi import HTTPException

from bisheng.common.errcode.dsh import (
    DshAuthorizationUnavailableError,
    DshInvalidRequestError,
    DshOperationConflictError,
    DshOperationInProgressError,
)
from bisheng.dsh.domain.schemas.admin import CommandResult, LicenseSnapshot, SeatItem, SessionItem
from bisheng.dsh.domain.services.profile import profile_scope
from bisheng.dsh.infrastructure.gateway_client import GatewayCommandRejected


class DshManagementService:
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
        model_policy_view=None,
    ):
        self.repository_scope, self.gateway, self.authorize = repository_scope, gateway, authorize
        self.profiles, self.policy, self.policy_view, self.now = profiles, policy, policy_view, now
        self.model_users_view = model_users_view
        self.model_policy_view = model_policy_view

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
        seat_state="ASSIGNED",
        login_state=None,
    ):
        actor, target_tenant = await self.authorize(actor_id, tenant_id)
        result = self._page(
            await self._request(
                "management",
                {
                    "resource": "seats",
                    "actor": actor,
                    "target": {"tenant_id": str(target_tenant) if target_tenant else None},
                    "cursor": cursor,
                    "limit": limit,
                    "keyword": keyword,
                    "seat_state": seat_state,
                    "login_state": login_state,
                },
            )
        )
        try:
            result["items"] = [SeatItem.model_validate(row).model_dump() for row in result["items"]]
            if target_tenant is not None and any(int(row["tenant_id"]) != target_tenant for row in result["items"]):
                raise ValueError("Foreign tenant in management page")
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
        return {
            **result,
            "used": result["assigned"],
            "limit": result["seat_limit"],
            "valid_until": result.get("expires_at"),
        }

    async def get_policy(self, actor_id, user_id, *, tenant_id=None):
        _actor, tenant = await self.authorize(actor_id, tenant_id, user_id)
        with profile_scope(tenant):
            return await self.policy_view(user_id)

    async def get_model_policy(self, actor_id, user_id, model_id, *, tenant_id=None):
        _actor, tenant = await self.authorize(actor_id, tenant_id, user_id)
        with profile_scope(tenant):
            return await self.model_policy_view(user_id, model_id)

    async def update_policy(self, actor_id, user_id, request, *, model_id: int, tenant_id=None):
        _actor, tenant = await self.authorize(actor_id, tenant_id, user_id)
        with profile_scope(tenant):
            return await self.policy.update_policy(
                user_id=user_id, actor_user_id=actor_id, model_id=model_id, request=request
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
