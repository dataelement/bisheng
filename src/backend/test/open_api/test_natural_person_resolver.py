from datetime import datetime, timedelta

import pytest

from bisheng.common.errcode.open_api import PersonalTokenHolderInvalidError
from bisheng.database.models.tenant import UserTenant
from bisheng.open_api.domain.models.api_credential import ApiCredential
from bisheng.open_api.domain.services.credential_validator import resolve_natural_person
from bisheng.user.domain.models.user import User


async def _seed_holder(open_api_db, *, deleted: int = 0, tenant_id: int = 1, active: int | None = 1):
    async with open_api_db() as session:
        user = User(user_name="holder", password="unused", delete=deleted)
        session.add(user)
        await session.flush()
        session.add(
            UserTenant(
                user_id=user.user_id,
                tenant_id=tenant_id,
                status="active",
                is_active=active,
            )
        )
        await session.commit()
        return user


def _credential(user_id: int, *, tenant_id: int = 1) -> ApiCredential:
    return ApiCredential(
        id=90,
        tenant_id=tenant_id,
        subject_kind="natural_person",
        subject_id=user_id,
        name="pat",
        key_prefix="bs-pat-",
        last4="last",
        token_hash="a" * 64,
        scopes=["knowledge:read"],
        expires_at=datetime.now() + timedelta(days=1),
    )


async def test_resolver_builds_user_actor_and_keeps_credential_tenant_visible(open_api_db):
    holder = await _seed_holder(open_api_db)
    principal = await resolve_natural_person(_credential(holder.user_id))

    assert principal.authorization_subject_type == "user"
    assert principal.authorization_subject_id == holder.user_id
    assert principal.tenant_id == 1
    assert "super_admin" not in type(principal).model_fields
    assert "tenant_admin_tenant_ids" not in type(principal).model_fields


@pytest.mark.parametrize(
    ("deleted", "membership_tenant", "active"),
    [(1, 1, 1), (0, 2, 1), (0, 1, None)],
)
async def test_resolver_rejects_invalid_holder(
    open_api_db,
    deleted,
    membership_tenant,
    active,
):
    holder = await _seed_holder(
        open_api_db,
        deleted=deleted,
        tenant_id=membership_tenant,
        active=active,
    )
    with pytest.raises(PersonalTokenHolderInvalidError):
        await resolve_natural_person(_credential(holder.user_id))
