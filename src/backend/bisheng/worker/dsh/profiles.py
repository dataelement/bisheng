"""Lease-fenced delivery of immutable committed user profile snapshots."""

import json
from datetime import timedelta

from bisheng.common.errcode.dsh import DshOperationConflictError, DshOperationInProgressError


class ProfileOutboxWorker:
    def __init__(self, *, repository_scope, gateway, now):
        self.repository_scope, self.gateway, self.now = repository_scope, gateway, now

    def read(self, operation_id):
        with self.repository_scope() as repository:
            operation = repository.get(operation_id)
            if operation is None or operation.action != "SYNC_PROFILE":
                raise DshOperationConflictError()
            return operation.model_dump()

    async def resume(self, operation_id):
        current = self.read(operation_id)
        if current["status"] in {"SUCCEEDED", "FAILED"}:
            return current
        try:
            with self.repository_scope() as repository:
                operation = repository.claim(operation_id, now=self.now())
                generation, snapshot = operation.lease_generation, dict(operation.payload)
        except DshOperationInProgressError:
            return self.read(operation_id)
        try:
            list(profile_batches([snapshot]))
        except (ValueError, TypeError):
            with self.repository_scope() as repository:
                repository.finish(
                    operation_id,
                    generation,
                    now=self.now(),
                    status="FAILED",
                    result={"phase": "FAILED", "reason": "profile_body_too_large"},
                    code="invalid_request",
                )
            return self.read(operation_id)
        try:
            result = await self.gateway.request("profiles", {"items": [snapshot]})
            if set(result) != {"accepted"} or type(result["accepted"]) is not int or result["accepted"] not in (0, 1):
                raise ValueError("Invalid profile acknowledgement")
            with self.repository_scope() as repository:
                repository.finish(operation_id, generation, now=self.now(), status="SUCCEEDED", result=result)
        except Exception:
            with self.repository_scope() as repository:
                repository.retry(
                    operation_id,
                    generation,
                    now=self.now(),
                    code="authorization_unavailable",
                    retry_at=self.now() + timedelta(seconds=30),
                )
        return self.read(operation_id)


def profile_batches(items):
    """Respect both the 100-user bound and the signed UTF-8 request body bound."""
    batch = []
    for item in items:
        candidate = [*batch, item]
        size = len(
            json.dumps({"items": candidate}, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        )
        if len(candidate) > 100 or size > 65536:
            if not batch:
                raise ValueError("A single profile exceeds the service body limit")
            yield batch
            batch = [item]
            if (
                len(json.dumps({"items": batch}, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode())
                > 65536
            ):
                raise ValueError("A single profile exceeds the service body limit")
        else:
            batch = candidate
    if batch:
        yield batch


def register_profile_tasks(app, runtime_factory):
    @app.task(bind=True, name="dsh.scan_profiles", autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
    def scan_profiles(task, after_user_id: int = 0):
        from bisheng.worker._asyncio_utils import run_async_task

        async def execute():
            from bisheng.core.context import tenant as context
            from bisheng.user.domain.services.user import UserService

            # User directory rows are instance-owned; projection payloads keep their own tenant.
            tokens = [
                context.set_current_tenant_id(None),
                context.set_admin_scope_tenant_id(None),
                context.set_visible_tenant_ids(None),
                context._bypass_tenant_filter.set(False),
            ]
            try:
                page = await UserService.scan_dsh_profiles(after_user_id=after_user_id, limit=100)
                async with runtime_factory() as runtime:
                    for batch in profile_batches(page["items"]):
                        result = await runtime.gateway.request("profiles", {"items": batch})
                        if (
                            set(result) != {"accepted"}
                            or type(result["accepted"]) is not int
                            or not 0 <= result["accepted"] <= len(batch)
                        ):
                            raise ValueError("Invalid profile acknowledgement")
                if page["has_more"]:
                    scan_profiles.apply_async(args=[page["next_user_id"]])
                return len(page["items"])
            finally:
                for token in reversed(tokens):
                    token.var.reset(token)

        return run_async_task(execute)

    return scan_profiles
