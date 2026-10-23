"""Request-row CAS ownership for immutable reconciliation operations."""

from copy import deepcopy
from datetime import datetime

from sqlmodel import Session, select

from bisheng.common.errcode.dsh import DshOperationConflictError
from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.dsh.domain.models.admin_operation import DshAdminOperation
from bisheng.dsh.domain.models.model_call import DshModelCall
from bisheng.dsh.domain.repositories.admin_operation import DshOperationRepository, payload_digest, require_tenant


class DshReconciliationRepository:
    def __init__(self, session: Session):
        self.session = session
        self.operations = DshOperationRepository(session)

    def get_request(self, request_id: str, *, lock=False):
        tenant = require_tenant()
        statement = select(DshModelCall).where(DshModelCall.request_id == request_id)
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        with strict_tenant_filter():
            row = self.session.exec(statement).one_or_none()
        if row is not None and row.tenant_id != tenant:
            raise DshOperationConflictError()
        return row

    def register(self, request, *, actor_user_id: int):
        row = self.get_request(request.request_id, lock=True)
        if row is None:
            raise DshOperationConflictError()
        payload = request.model_dump(mode="json")
        digest = payload_digest(payload)
        old = self.operations.get(request.operation_id, lock=True)
        if old is not None:
            if (
                old.action != "RECONCILE_USAGE"
                or old.actor_user_id != actor_user_id
                or old.user_id != row.user_id
                or old.payload_hash != digest
            ):
                raise DshOperationConflictError()
            return old
        if (
            row.status != "USAGE_UNKNOWN"
            or row.total_tokens is not None
            or row.event_version != request.expected_event_version
            or row.reconciliation_operation_id is not None
        ):
            raise DshOperationConflictError()
        operation = DshAdminOperation(
            operation_id=request.operation_id,
            tenant_id=require_tenant(),
            user_id=row.user_id,
            actor_user_id=actor_user_id,
            action="RECONCILE_USAGE",
            expected_event_version=request.expected_event_version,
            payload_hash=digest,
            payload=deepcopy(payload),
            before_values=row.model_dump(mode="json"),
            result_payload={"phase": "REGISTERED"},
        )
        self.session.add(operation)
        row.reconciliation_operation_id = request.operation_id
        self.session.flush()
        return operation

    def complete_if_projected(self, operation_id: str, generation: int, *, now: datetime):
        operation = self.operations.owned(operation_id, generation, now=now)
        row = self.get_request(operation.payload["request_id"], lock=True)
        payload = operation.payload
        if row is None or row.reconciliation_operation_id != operation_id:
            raise DshOperationConflictError()
        if row.status == "USAGE_UNKNOWN" and row.event_version == operation.expected_event_version:
            return False
        if (
            row.event_version != operation.expected_event_version + 1
            or row.usage_source != "RECONCILED"
            or any(getattr(row, key) != payload[key] for key in ["input_tokens", "output_tokens", "total_tokens"])
        ):
            raise DshOperationConflictError()
        operation.after_values = row.model_dump(mode="json")
        operation.committed_at = now
        operation.effective_at = now
        operation.status = "SUCCEEDED"
        operation.result_payload = {"phase": "COMPLETE", "event_version": row.event_version}
        operation.lease_until = None
        self.session.flush()
        return True

    def fail(self, operation_id: str, generation: int, *, code: str, now: datetime):
        operation = self.operations.owned(operation_id, generation, now=now)
        operation.status = "FAILED"
        operation.result_code = code
        operation.result_payload = {"phase": "FAILED"}
        operation.lease_until = None
        self.session.flush()
        return operation
