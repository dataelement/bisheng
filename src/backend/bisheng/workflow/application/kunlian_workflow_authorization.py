"""昆联 Workflow 授权的隔离应用适配。"""

from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from hashlib import sha256
from json import dumps
from typing import Protocol

from loguru import logger
from sqlalchemy.exc import SQLAlchemyError

from bisheng.common.errcode.permission import (
    GrantLevelForbiddenError,
    InvalidPermissionModeError,
    PermissionCheckFailedError,
    PermissionDeniedError,
    PermissionInvalidResourceError,
    PermissionModelStateConflictError,
    PermissionProjectionFailedError,
    PermissionPublishNotReadyError,
    PermissionServiceUnavailableError,
    PermissionSubjectUnavailableError,
    PermissionVersionConflictError,
    ProtectedAssignmentMutationError,
)
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.permission.application.identity import (
    PermissionActor,
    reset_current_permission_actor,
    set_current_permission_actor,
)
from bisheng.permission.application.resource_api import GrantMutationRequest


class AuthorizationError(Exception):
    """隔离候选合同的安全错误分类。"""


@dataclass(frozen=True, slots=True)
class AuthorizationSubject:
    connection_id: str
    tenant_id: int
    user_id: int
    actor: PermissionActor


@dataclass(frozen=True, slots=True)
class GrantChange:
    expected_resource_version: int
    expected_catalog_release_id: int
    subject_ref: str | None = None
    model_key: str | None = None
    assignee_id: str | None = None
    expected_assignee_version: int | None = None


@dataclass(frozen=True, slots=True)
class GrantReceiptResult:
    status: str
    applied_revision: int | None = None


@dataclass(frozen=True, slots=True)
class GrantReceipt:
    digest: str
    ref: str
    result: GrantReceiptResult | None = None


class GrantReceiptPort(Protocol):
    async def claim_or_read(self, key: str, digest: str) -> tuple[GrantReceipt, bool]: ...

    async def complete(self, key: str, result: GrantReceiptResult) -> GrantReceiptResult: ...


def _digest(value):
    return sha256(dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class WorkflowAuthorizationService:
    def __init__(
        self,
        *,
        permissions,
        targets,
        decisions,
        verify_subject,
        resolve_member,
        receipts: GrantReceiptPort,
        allowed_models,
    ):
        self.permissions = permissions
        self.targets = targets
        self.decisions = decisions
        self.verify_subject = verify_subject
        self.resolve_member = resolve_member
        self.receipts = receipts
        self.allowed_models = frozenset(allowed_models)

    @staticmethod
    def _require_allowed(allowed):
        if allowed is False:
            raise AuthorizationError("NOT_FOUND")
        if allowed is not True:
            raise AuthorizationError("UNAVAILABLE")

    @asynccontextmanager
    async def _authorized(self, subject, workflow_id, action):
        actor = subject.actor
        if actor.subject_type != "user" or (actor.tenant_id, actor.user_id) != (subject.tenant_id, subject.user_id):
            raise AuthorizationError("NOT_FOUND")
        if type(subject.tenant_id) is not int or subject.tenant_id <= 0:
            raise AuthorizationError("NOT_FOUND")

        with tenant_execution_scope(subject.tenant_id):
            token = set_current_permission_actor(actor)
            try:
                self._require_allowed(await self.verify_subject(subject, workflow_id, action))
                arguments = {"resource_type": "workflow", "resource_id": workflow_id, "actor": actor}
                target = await self.targets.resolve(action=action, **arguments)
                if (target.tenant_id, target.resource_type, target.resource_id) != (
                    subject.tenant_id,
                    "workflow",
                    workflow_id,
                ):
                    raise AuthorizationError("NOT_FOUND")
                self._require_allowed(await self.decisions.check(action=action, **arguments))
                yield arguments
            finally:
                reset_current_permission_actor(token)

    @staticmethod
    def _context_revision(context):
        if context["can_manage_permission"] is not True:
            raise AuthorizationError("NOT_FOUND")
        if context["projection_state"] != "CURRENT":
            raise AuthorizationError("UNAVAILABLE")
        return context["resource_version"], context["catalog_release_id"]

    async def _grantable(self, arguments):
        models = await self.permissions.get_grantable_models(**arguments)
        return [{"key": model["key"]} for model in models if model["active"] and model["key"] in self.allowed_models]

    async def list_grants(self, subject, workflow_id, *, cursor, limit):
        async with self._authorized(subject, workflow_id, "manage_permission") as arguments:
            revision = self._context_revision(await self.permissions.get_context(**arguments))
            page = await self.permissions.list_grants(cursor=cursor, page_size=limit, **arguments)
            models = await self._grantable(arguments)
            if revision != self._context_revision(await self.permissions.get_context(**arguments)):
                raise AuthorizationError("REVISION_CONFLICT")
            items = [
                {
                    "assignee_id": row["assignee_id"],
                    "assignee_version": row["assignee_version"],
                    "subject": {"type": row["subject"]["type"], "id": row["subject"]["id"]},
                    "model_key": row["model"]["key"],
                    "editable": row["editable"] and not row["protected"] and row["subject"]["type"] == "user",
                }
                for row in page["data"]
                if row["scope"] == "LOCAL" and row["inherited_from"] is None
            ]
            return {
                "resource_version": revision[0],
                "catalog_release_id": revision[1],
                "items": items,
                "grantable_models": models,
                "next_cursor": page["next_cursor"],
                "has_more": page["has_more"],
            }

    async def my_permissions(self, subject, workflow_id):
        async with self._authorized(subject, workflow_id, "visible") as arguments:
            result = await self.permissions.get_my_permissions(**arguments)
            if result["projection_degraded"] is not False:
                raise AuthorizationError("UNAVAILABLE")
            return {"actions": result["actions"]}

    async def _submit_change(self, subject, arguments, change: GrantChange, idempotency_key: str):
        if change.assignee_id is None:
            member = await self.resolve_member(subject, change.subject_ref)
            if member is None or member[0] != subject.tenant_id or type(member[1]) is not int or member[1] <= 0:
                raise AuthorizationError("NOT_FOUND")
            if {"key": change.model_key} not in await self._grantable(arguments):
                raise AuthorizationError("NOT_FOUND")
            mutation = {"op": "ADD", "subject": {"type": "user", "id": str(member[1])}, "model_key": change.model_key}
        else:
            await self.permissions.check_workflow_direct_user_grant(
                resource_id=arguments["resource_id"],
                actor=arguments["actor"],
                assignee_id=int(change.assignee_id),
                expected_assignee_version=change.expected_assignee_version,
            )
            mutation = {
                "op": "REMOVE",
                "assignee_id": change.assignee_id,
                "expected_assignee_version": change.expected_assignee_version,
            }
        request = GrantMutationRequest.model_validate(
            {
                "idempotency_key": idempotency_key,
                "expected_resource_version": change.expected_resource_version,
                "expected_catalog_release_id": change.expected_catalog_release_id,
                "changes": (mutation,),
            }
        )
        result = await self.permissions.mutate_grants(request=request, **arguments)
        return result["resource_version"]

    async def _original_outcome(self, arguments, key):
        return await self.permissions.get_workflow_grant_outcome(
            resource_id=arguments["resource_id"],
            actor=arguments["actor"],
            idempotency_key=key,
        )

    @staticmethod
    def _projection_result(outcome):
        if outcome is not None and outcome[0] == "FINALIZED":
            return GrantReceiptResult("APPLIED", outcome[1])
        return GrantReceiptResult("PENDING")

    async def _run_original_change(self, subject, arguments, change, key):
        try:
            revision = await self._submit_change(subject, arguments, change, key)
        except AuthorizationError as error:
            return GrantReceiptResult(str(error))
        except (
            GrantLevelForbiddenError,
            InvalidPermissionModeError,
            PermissionDeniedError,
            PermissionInvalidResourceError,
            PermissionModelStateConflictError,
            PermissionSubjectUnavailableError,
            ProtectedAssignmentMutationError,
        ):
            return GrantReceiptResult("NOT_FOUND")
        except PermissionVersionConflictError:
            outcome = await self._original_outcome(arguments, key)
            if outcome is None:
                return GrantReceiptResult("REVISION_CONFLICT")
            return self._projection_result(outcome)
        except (
            PermissionCheckFailedError,
            PermissionProjectionFailedError,
            PermissionPublishNotReadyError,
            PermissionServiceUnavailableError,
            SQLAlchemyError,
        ) as error:
            logger.warning(
                "昆联授权结果待核对,workflow_id={} error_type={}", arguments["resource_id"], type(error).__name__
            )
            return self._projection_result(await self._original_outcome(arguments, key))
        return GrantReceiptResult("APPLIED", revision)

    async def change(self, subject, workflow_id, change: GrantChange, client_key: str):
        async with self._authorized(subject, workflow_id, "manage_permission") as arguments:
            # TODO [F128][EXT-03] 正式回执支持跨实例和重启后查回。
            key = _digest(["F128", subject.connection_id, subject.tenant_id, subject.user_id, workflow_id, client_key])
            digest = _digest(asdict(change))
            receipt, first = await self.receipts.claim_or_read(key, digest)
            if receipt.digest != digest:
                raise AuthorizationError("IDEMPOTENCY_CONFLICT")
            result = receipt.result
            if result is None:
                if first:
                    result = await self._run_original_change(subject, arguments, change, key)
                else:
                    result = self._projection_result(await self._original_outcome(arguments, key))
                if result.status != "PENDING":
                    result = await self.receipts.complete(key, result)
            logger.info(
                "昆联授权,operation_ref={} tenant_id={} workflow_id={} actor_id={} action={} revision={} result={}",
                receipt.ref,
                subject.tenant_id,
                workflow_id,
                subject.user_id,
                "revoke" if change.assignee_id is not None else "grant",
                change.expected_resource_version,
                result.status,
            )
            if result.status not in {"APPLIED", "PENDING"}:
                raise AuthorizationError(result.status)
            data = {"operation_ref": receipt.ref, "status": result.status}
            if result.applied_revision is not None:
                data["applied_resource_version"] = result.applied_revision
            return data
