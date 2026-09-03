"""Canonical identity facts used by the F048 operational migration."""

from __future__ import annotations

from sqlmodel import col, select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.department import UserDepartment
from bisheng.database.models.tenant import UserTenant

TupleIdentity = tuple[str, str, str]


def _member_pair(
    identity: TupleIdentity,
    *,
    object_type: str,
) -> tuple[int, int] | None:
    user, relation, object_key = identity
    user_type, user_separator, user_id = user.partition(":")
    actual_object_type, object_separator, object_id = object_key.partition(":")
    if (
        relation != "member"
        or user_type != "user"
        or not user_separator
        or actual_object_type != object_type
        or not object_separator
        or not user_id.isdigit()
        or not object_id.isdigit()
    ):
        return None
    return int(user_id), int(object_id)


class LegacyIdentityPermissionMigrationSource:
    """Resolve only business-owned tenant and department membership."""

    async def aresolve_expected_states(
        self,
        tuple_identities: tuple[TupleIdentity, ...],
    ) -> dict[TupleIdentity, bool]:
        tenant_pairs = {
            identity: pair
            for identity in tuple_identities
            if (pair := _member_pair(identity, object_type="tenant")) is not None
        }
        department_pairs = {
            identity: pair
            for identity in tuple_identities
            if (pair := _member_pair(identity, object_type="department")) is not None
        }
        result = dict.fromkeys((*tenant_pairs.keys(), *department_pairs.keys()), False)
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                if tenant_pairs:
                    active_tenants = set(
                        (
                            await session.execute(
                                select(
                                    UserTenant.user_id,
                                    UserTenant.tenant_id,
                                ).where(
                                    col(UserTenant.user_id).in_({pair[0] for pair in tenant_pairs.values()}),
                                    col(UserTenant.tenant_id).in_({pair[1] for pair in tenant_pairs.values()}),
                                    UserTenant.status == "active",
                                    UserTenant.is_active == 1,
                                )
                            )
                        ).all()
                    )
                    for identity, pair in tenant_pairs.items():
                        result[identity] = pair in active_tenants
                if department_pairs:
                    active_departments = set(
                        (
                            await session.execute(
                                select(
                                    UserDepartment.user_id,
                                    UserDepartment.department_id,
                                ).where(
                                    col(UserDepartment.user_id).in_({pair[0] for pair in department_pairs.values()}),
                                    col(UserDepartment.department_id).in_(
                                        {pair[1] for pair in department_pairs.values()}
                                    ),
                                )
                            )
                        ).all()
                    )
                    for identity, pair in department_pairs.items():
                        result[identity] = pair in active_departments
        return result
