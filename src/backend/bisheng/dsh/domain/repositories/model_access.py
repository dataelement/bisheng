"""Paginate platform users and policies without a seat or DSH login prerequisite."""

from sqlmodel import Session, col, select

from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.dsh.domain.models.user_policy import DshUserPolicy
from bisheng.dsh.domain.repositories.admin_operation import require_tenant
from bisheng.dsh.domain.schemas.admin import ModelAccessUser


class DshModelAccessRepository:
    def __init__(self, session: Session):
        self.session = session

    def users(self, rows: list[tuple[int, str]], *, limit: int = 20) -> dict:
        tenant = require_tenant()
        if not 1 <= limit <= 100 or len(rows) > limit + 1:
            raise ValueError("A bounded user page is required")
        with strict_tenant_filter():
            ids = [user_id for user_id, _name in rows[:limit]]
            policies = (
                {
                    policy.user_id: policy
                    for policy in self.session.exec(
                        select(DshUserPolicy).where(
                            DshUserPolicy.tenant_id == tenant, col(DshUserPolicy.user_id).in_(ids)
                        )
                    ).all()
                }
                if ids
                else {}
            )
        items = [
            ModelAccessUser(
                user_id=user_id,
                user_name=name,
                version=policy.version if policy else 0,
                models=policy.model_configs if policy else [],
                pending_operation_id=policy.pending_operation_id if policy else None,
            ).model_dump()
            for user_id, name in rows[:limit]
            for policy in [policies.get(user_id)]
        ]
        return {
            "items": items,
            "next_cursor": str(items[-1]["user_id"]) if len(rows) > limit else None,
            "has_more": len(rows) > limit,
        }
