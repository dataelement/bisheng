"""DSH-owned writes for the model owner's explicit new-receiver manifests."""

from sqlalchemy import select

from bisheng.common.errcode.dsh import DshOperationConflictError
from bisheng.core.context.tenant import bypass_tenant_filter, get_current_tenant_id
from bisheng.database.models.tenant import ROOT_TENANT_ID, Tenant
from bisheng.dsh.domain.models.unified_policy import ModelVisibility, UnifiedPolicyAudit
from bisheng.resource_reference.application.contracts import TransactionIdentity


class SharedModelVisibilityRepository:
    async def ainitialize(self, session, *, child_ids, model_ids, actor_user_id, plan_id, guard):
        transaction = TransactionIdentity.capture(session)
        if get_current_tenant_id() != ROOT_TENANT_ID or not session.in_transaction():
            raise DshOperationConflictError()
        for child_id in sorted(set(child_ids)):
            guard()
            with session.no_autoflush, bypass_tenant_filter():
                child = (
                    await session.execute(select(Tenant).where(Tenant.id == child_id).with_for_update())
                ).scalar_one_or_none()
            transaction.assert_current(session)
            guard()
            if child is None or child.parent_tenant_id != ROOT_TENANT_ID:
                raise DshOperationConflictError()
            for model_id in sorted(set(model_ids)):
                with session.no_autoflush, bypass_tenant_filter():
                    existing = (
                        await session.execute(
                            select(ModelVisibility)
                            .where(ModelVisibility.tenant_id == child_id, ModelVisibility.model_id == model_id)
                            .with_for_update()
                        )
                    ).scalar_one_or_none()
                transaction.assert_current(session)
                guard()
                if existing is not None:
                    continue
                session.add(
                    ModelVisibility(
                        tenant_id=child_id,
                        model_id=model_id,
                        everyone=True,
                        subjects=[],
                        version=1,
                        updated_by=actor_user_id,
                    )
                )
                session.add(
                    UnifiedPolicyAudit(
                        tenant_id=child_id,
                        actor_user_id=actor_user_id,
                        resource=f"shared-model:{model_id}:{plan_id}",
                        before_values=None,
                        after_values={"version": 1, "everyone": True, "subjects": []},
                    )
                )
                await session.flush()
                transaction.assert_current(session)
                guard()
