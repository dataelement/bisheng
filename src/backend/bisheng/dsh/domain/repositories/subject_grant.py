"""Short tenant-serialized transactions around immutable batch selection."""

from uuid import uuid4

from sqlmodel import select

from bisheng.common.errcode.dsh import DshInvalidRequestError, DshOperationConflictError
from bisheng.database.models.tenant import Tenant
from bisheng.dsh.domain.models.subject_grant import DshSubjectGrant
from bisheng.dsh.domain.models.subject_policy import DshSubjectPolicy
from bisheng.dsh.domain.repositories.admin_operation import require_tenant
from bisheng.dsh.domain.repositories.subject_policy import DshSubjectPolicyRepository


class DshSubjectGrantRepository:
    def __init__(self, session):
        self.session = session

    def _lock(self):
        tenant = require_tenant()
        self.session.exec(select(Tenant).where(Tenant.id == tenant).with_for_update()).one()
        return tenant

    def prepare(self, *, actor_id, model_id, subject_type, subject_id, request):
        tenant = self._lock()
        policies = DshSubjectPolicyRepository(self.session)
        policies._validate_subject(subject_type, subject_id)
        intent = {
            "expected_version": request.expected_version,
            "enabled": request.enabled,
            "monthly_token_limit": request.monthly_token_limit,
        }
        rows = self.session.exec(
            select(DshSubjectGrant).where(
                DshSubjectGrant.tenant_id == tenant,
                DshSubjectGrant.subject_type == subject_type,
                DshSubjectGrant.subject_id == subject_id,
                DshSubjectGrant.model_id == model_id,
            )
        ).all()
        for row in rows:
            if row.status == "PENDING":
                if row.actor_user_id != actor_id or row.payload["request"] != intent:
                    raise DshOperationConflictError()
                return row.model_dump()
        current = self.session.exec(
            select(DshSubjectPolicy).where(
                DshSubjectPolicy.tenant_id == tenant,
                DshSubjectPolicy.subject_type == subject_type,
                DshSubjectPolicy.subject_id == subject_id,
                DshSubjectPolicy.model_id == model_id,
            )
        ).one_or_none()
        version = current.version if current else 0
        if version != request.expected_version:
            for row in rows:
                if (
                    row.status == "SUCCEEDED"
                    and row.actor_user_id == actor_id
                    and row.payload["request"] == intent
                    and row.result["version"] == version
                ):
                    return row.model_dump()
            raise DshOperationConflictError()
        members = (
            policies.selected_user_ids(subject_type, subject_id)
            if request.enabled and request.monthly_token_limit > 0
            else []
        )
        if len(members) > 1000:
            raise DshInvalidRequestError()
        row = DshSubjectGrant(
            operation_id=str(uuid4()),
            tenant_id=tenant,
            actor_user_id=actor_id,
            subject_type=subject_type,
            subject_id=subject_id,
            model_id=model_id,
            status="PENDING",
            payload={"request": intent, "user_ids": members},
        )
        self.session.add(row)
        self.session.flush()
        return row.model_dump()

    def finish(self, operation_id, *, failure=None):
        tenant = self._lock()
        row = self.session.exec(
            select(DshSubjectGrant)
            .where(DshSubjectGrant.operation_id == operation_id, DshSubjectGrant.tenant_id == tenant)
            .with_for_update()
        ).one()
        if row.status != "PENDING":
            return row.model_dump()
        if failure:
            row.status = "FAILED"
            row.result = {"result_code": failure}
        else:
            row.result = DshSubjectPolicyRepository(self.session).update(
                subject_type=row.subject_type,
                subject_id=row.subject_id,
                model_id=row.model_id,
                actor_user_id=row.actor_user_id,
                **row.payload["request"],
            )
            row.status = "SUCCEEDED"
        self.session.add(row)
        self.session.flush()
        return row.model_dump()
