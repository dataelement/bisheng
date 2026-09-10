"""Policy ownership and immutable audit transitions in one SQL transaction.

No method commits. Invoke inside a short caller-owned transaction and never hold
that transaction across remote Redis/Gateway calls. Inserts use savepoints so a
unique-key race can be reread without destroying the surrounding transaction.
"""

from copy import deepcopy
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from bisheng.common.errcode.dsh import DshOperationConflictError, DshOperationInProgressError
from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.dsh.domain.models.admin_operation import DshAdminOperation
from bisheng.dsh.domain.models.user_policy import DshUserPolicy
from bisheng.dsh.domain.repositories.admin_operation import DshOperationRepository, payload_digest, require_tenant
from bisheng.dsh.domain.schemas.model_policy import DshModelPolicyState, DshPolicySnapshot


class DshPolicyRepository:
    def __init__(self, session: Session):
        self.session = session
        self.operations = DshOperationRepository(session)

    def rows(self, user_id: int, *, lock: bool = False) -> list[DshUserPolicy]:
        tenant_id = require_tenant()
        statement = select(DshUserPolicy).where(DshUserPolicy.user_id == user_id).order_by(DshUserPolicy.model_id)
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        with strict_tenant_filter():
            rows = list(self.session.exec(statement).all())
        if any(row.tenant_id != tenant_id for row in rows):
            raise DshOperationConflictError()
        return rows

    def get(self, user_id: int, *, lock: bool = False) -> DshPolicySnapshot | None:
        rows = self.rows(user_id, lock=lock)
        return (
            DshPolicySnapshot(
                tenant_id=require_tenant(),
                user_id=user_id,
                rows=[DshModelPolicyState.model_validate(row) for row in rows],
            )
            if rows
            else None
        )

    def get_model(self, user_id: int, model_id: int, *, lock: bool = False) -> DshUserPolicy | None:
        tenant = require_tenant()
        statement = select(DshUserPolicy).where(DshUserPolicy.user_id == user_id, DshUserPolicy.model_id == model_id)
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        with strict_tenant_filter():
            row = self.session.exec(statement).one_or_none()
        if row is not None and row.tenant_id != tenant:
            raise DshOperationConflictError()
        return row

    def register_update(
        self,
        *,
        operation_id: str,
        user_id: int,
        actor_user_id: int,
        expected_version: int,
        model_id: int,
        monthly_token_limit: int,
        enabled: bool,
    ):
        require_tenant()
        if type(expected_version) is not int or expected_version < 0:
            raise ValueError("Versions and limits must be nonnegative integers")
        if any(type(value) is not int or value <= 0 for value in (user_id, actor_user_id)):
            raise ValueError("Subjects and models must be positive integers")
        if (
            type(model_id) is not int
            or model_id <= 0
            or type(monthly_token_limit) is not int
            or not 0 <= monthly_token_limit <= 9223372036854775807
            or type(enabled) is not bool
        ):
            raise ValueError("A typed model grant is required")
        payload = {"model_id": model_id, "monthly_token_limit": monthly_token_limit, "enabled": enabled}
        digest = payload_digest(payload)
        existing = self.operations.get(operation_id, lock=True)
        if existing is not None:
            return self._same_intent(existing, user_id, actor_user_id, expected_version, digest)
        policy = self.get_model(user_id, model_id, lock=True)
        if policy is None:
            try:
                with self.session.begin_nested():
                    snapshot = self.get(user_id)
                    policy = DshUserPolicy(
                        user_id=user_id,
                        model_id=model_id,
                        updated_by=actor_user_id,
                        quota_epoch=snapshot.quota_epoch if snapshot else 1,
                    )
                    self.session.add(policy)
                    self.session.flush()
            except IntegrityError:
                policy = self.get_model(user_id, model_id, lock=True)
                if policy is None:
                    raise
        # Reread after the user lock: another transaction may have committed our ID.
        existing = self.operations.get(operation_id, lock=True)
        if existing is not None:
            return self._same_intent(existing, user_id, actor_user_id, expected_version, digest)
        if policy.pending_operation_id is not None:
            raise DshOperationInProgressError()
        if policy.version != expected_version:
            raise DshOperationConflictError()
        operation = DshAdminOperation(
            operation_id=operation_id,
            user_id=user_id,
            actor_user_id=actor_user_id,
            action="UPDATE_POLICY",
            expected_policy_version=expected_version,
            payload_hash=digest,
            payload=deepcopy(payload),
            result_payload={"phase": "REGISTERED"},
        )
        try:
            with self.session.begin_nested():
                self.session.add(operation)
                self.session.flush()
        except IntegrityError:
            existing = self.operations.get(operation_id, lock=True)
            if existing is None:
                # The global operation ID may belong to another tenant; disclose no data.
                raise DshOperationConflictError() from None
            return self._same_intent(existing, user_id, actor_user_id, expected_version, digest)
        policy.pending_operation_id = operation_id
        self.session.flush()
        return operation

    @staticmethod
    def _same_intent(operation, user_id, actor_user_id, expected_version, digest):
        if (
            operation.action != "UPDATE_POLICY"
            or operation.user_id != user_id
            or operation.actor_user_id != actor_user_id
            or operation.expected_policy_version != expected_version
            or operation.payload_hash != digest
        ):
            raise DshOperationConflictError()
        return operation

    def _owned(self, operation_id: str, generation: int, *, now: datetime):
        operation = self.operations.owned(operation_id, generation, now=now)
        if operation.action != "UPDATE_POLICY":
            raise DshOperationConflictError()
        policy = self.get_model(operation.user_id, operation.payload["model_id"], lock=True)
        if policy is None or policy.pending_operation_id != operation_id:
            raise DshOperationConflictError()
        return operation, policy

    @staticmethod
    def _snapshot(policy):
        return {
            "version": policy.version,
            "model_id": policy.model_id,
            "monthly_token_limit": policy.monthly_token_limit,
            "enabled": bool(policy.enabled),
        }

    def commit_update(self, operation_id: str, generation: int, *, now: datetime):
        operation, policy = self._owned(operation_id, generation, now=now)
        if operation.committed_at is not None:
            if self._snapshot(policy) != operation.after_values:
                raise DshOperationConflictError()
            return operation
        if policy.version != operation.expected_policy_version:
            raise DshOperationConflictError()
        before = self._snapshot(policy)
        policy.monthly_token_limit = operation.payload["monthly_token_limit"]
        policy.enabled = int(operation.payload["enabled"])
        policy.version += 1
        policy.updated_by = operation.actor_user_id
        policy.quota_sync_state = "PENDING"
        operation.before_values = before
        operation.after_values = self._snapshot(policy)
        operation.committed_at = now
        operation.result_payload = {"phase": "SQL_COMMITTED"}
        self.session.flush()
        return operation

    def mark_ready(self, operation_id: str, generation: int, *, now: datetime):
        operation, policy = self._owned(operation_id, generation, now=now)
        if operation.committed_at is None or operation.after_values != self._snapshot(policy):
            raise DshOperationConflictError()
        policy.quota_sync_state = "READY"
        operation.result_payload = {"phase": "SQL_READY"}
        self.session.flush()
        return operation

    def complete_update(self, operation_id: str, generation: int, *, now: datetime):
        operation, policy = self._owned(operation_id, generation, now=now)
        if policy.quota_sync_state != "READY" or operation.committed_at is None:
            raise DshOperationConflictError()
        operation.effective_at = now
        operation.status = "SUCCEEDED"
        operation.result_payload = {"phase": "EFFECTIVE"}
        operation.result_code = None
        operation.next_retry_at = None
        policy.pending_operation_id = None
        self.session.flush()
        return operation

    def fail_uncommitted(self, operation_id: str, generation: int, *, code: str, now: datetime):
        operation, policy = self._owned(operation_id, generation, now=now)
        if operation.committed_at is not None:
            raise DshOperationConflictError()
        operation.status = "FAILED"
        operation.result_code = code
        operation.result_payload = {"phase": "REJECTED"}
        policy.pending_operation_id = None
        self.session.flush()
        return operation

    def new_user_proof(self, operation_id: str, generation: int, *, now: datetime) -> dict:
        """Initialize a user ledger only when every model is an uncommitted placeholder."""
        from bisheng.dsh.domain.models.model_call import DshModelCall
        from bisheng.dsh.domain.models.monthly_usage import DshMonthlyUsage

        operation, policy = self._owned(operation_id, generation, now=now)
        if operation.committed_at is not None or operation.expected_policy_version != 0 or policy.version != 0:
            raise DshOperationConflictError()
        if any(row.version > 0 for row in self.rows(policy.user_id)):
            return None
        with strict_tenant_filter():
            for model in (DshModelCall, DshMonthlyUsage):
                if self.session.exec(select(model).where(model.user_id == policy.user_id).limit(1)).first() is not None:
                    return None
        return {
            "tenant_id": require_tenant(),
            "user_id": policy.user_id,
            "operation_id": operation_id,
            "lease_generation": generation,
            "policy_version": 0,
            "history_empty": True,
        }
