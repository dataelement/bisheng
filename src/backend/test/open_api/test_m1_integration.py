from types import SimpleNamespace

from sqlmodel import select

from bisheng.database.models.tenant import UserTenant
from bisheng.open_api.api.endpoints.auth import whoami
from bisheng.open_api.domain.models import ServiceAccount
from bisheng.open_api.domain.models.api_credential import SUBJECT_KIND_SERVICE_ACCOUNT
from bisheng.open_api.domain.schemas.credential import KeyIssueRequest
from bisheng.open_api.domain.schemas.service_account import ServiceAccountCreate
from bisheng.open_api.domain.services.credential_service import CredentialService
from bisheng.open_api.domain.services.credential_validator import validate_bearer
from bisheng.open_api.domain.services.service_account_service import ServiceAccountService
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.user.domain.models.user import User


async def test_independent_service_account_round_trip_keeps_user_tables_unchanged(
    open_api_db,
    fake_redis,
    audit_events,
):
    async with open_api_db() as session:
        session.add(User(user_id=1, user_name="owner", password="x", delete=0))
        session.add(UserTenant(user_id=1, tenant_id=1, status="active", is_active=1))
        await session.commit()
        users_before = len((await session.exec(select(User))).all())
        memberships_before = len((await session.exec(select(UserTenant))).all())

    account = await ServiceAccountService.create(
        SimpleNamespace(user_id=1, tenant_id=1, is_global_super=False),
        ServiceAccountCreate(name="integration", resource_owner_user_id=1),
    )
    assert account.id == 1
    issued = await CredentialService.issue(
        tenant_id=1,
        subject_kind=SUBJECT_KIND_SERVICE_ACCOUNT,
        subject_id=account.id,
        request=KeyIssueRequest(name="read", scopes=["knowledge:read"]),
        created_by=1,
    )
    resolved = await validate_bearer(f"Bearer {issued.plaintext}")
    response = await whoami(resolved)

    async with open_api_db() as session:
        assert len((await session.exec(select(User))).all()) == users_before
        assert len((await session.exec(select(UserTenant))).all()) == memberships_before
        assert len((await session.exec(select(ServiceAccount))).all()) == 1

    assert resolved.actor_kind == "service_account"
    assert resolved.actor_id == account.id
    assert resolved.resource_owner_user_id == 1
    assert response.data.actor_kind == "service_account"
    assert response.data.actor_id == account.id
    assert response.data.resource_owner.user_id == 1
    assert response.data.key_mask == issued.key_mask

    user_actor = PermissionActor(subject_type="user", subject_id=1, tenant_id=1)
    service_account_actor = PermissionActor(
        subject_type="service_account",
        subject_id=1,
        tenant_id=1,
    )
    assert user_actor.fga_subject == "user:1"
    assert service_account_actor.fga_subject == "service_account:1"
    assert user_actor != service_account_actor
    assert audit_events[0]["metadata"]["service_account_id"] == account.id
