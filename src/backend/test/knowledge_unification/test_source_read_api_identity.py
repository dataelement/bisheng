"""Restore API deletion through the trusted audit bridge, keeping SA authority."""

import pytest
from fastapi import HTTPException
from sqlalchemy import delete

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.common.errcode.open_api import OpenApiScopeMissingError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.database.models import tenant as tenant_module
from bisheng.database.models.tenant import UserTenant
from bisheng.knowledge.application import deletion_admission as admission
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.open_api.domain.context import OpenApiPrincipal, get_current_open_api_principal
from bisheng.permission.application import identity as permission_identity
from bisheng.permission.application.identity import PermissionActor, get_current_permission_actor
from bisheng.resource_reference.application import read_identity as module
from bisheng.resource_reference.application.read_identity import AuthenticatedSourceReadIdentity
from bisheng.user.domain.models import user as user_module
from bisheng.user.domain.models.user import User
from test.knowledge_unification import test_kn_delete_plan as native
from test.knowledge_unification import test_processing_identity as credentials

deletion_tenant, db, context, service, application = (
    native.deletion_tenant,
    native.db,
    native.context,
    native.service,
    native.application,
)
api_ports = credentials.api_ports


def principal(**changes):
    values = {
        "credential_id": 20,
        "actor_kind": "service_account",
        "actor_id": 44,
        "actor_name": "machine",
        "tenant_id": 101,
        "resource_owner_user_id": 7,
        "scopes": frozenset({"knowledge:write"}),
        "mode": "S",
        "authorization_subject_type": "service_account",
        "authorization_subject_id": 44,
        "effective_user_id": None,
    }
    return OpenApiPrincipal(**{**values, **changes})


def actor():
    return PermissionActor(subject_type="service_account", subject_id=44, tenant_id=101)


@pytest.fixture
async def sa(application, context, api_ports, monkeypatch):
    # The existing audit adapter reads native User/UserTenant, rather than a
    # fabricated owner payload. Only credential/FGA transports reuse test ports.
    async with context.db.engine.begin() as connection:
        await connection.run_sync(
            lambda conn: User.metadata.create_all(conn, tables=[User.__table__, UserTenant.__table__])
        )
    async with context.db.sessions() as session, session.begin():
        session.add(User(user_id=7, user_name="audit-person", password="-", delete=0))
        session.add(UserTenant(user_id=7, tenant_id=101, is_active=1, status="active"))
    monkeypatch.setattr(user_module, "get_async_db_session", context.db.sessions)
    monkeypatch.setattr(tenant_module, "get_async_db_session", context.db.sessions)
    monkeypatch.setattr(module, "get_current_open_api_principal", get_current_open_api_principal)
    monkeypatch.setattr(module, "resolve_permission_actor", permission_identity.resolve_permission_actor)
    original = principal()
    api_ports.current[0] = original
    api_ports.row.subject_id = 44
    return original


async def test_native_api_deletion_identity_uses_audit_payload_without_owner_authority(application, sa):
    with credentials.request_context(actor(), sa):
        reference = await admission.capture(application.user, space_id=2)
        async with admission.identity(reference, current=application.user) as (actual, continuation):
            assert isinstance(actual, UserPayload)
            assert actual.user_id == 7 and actual.user_name == "audit-person"
            assert actual.user_role == [] and actual.is_global_super is False
            restored = get_current_open_api_principal()
            assert restored.authorization_subject_type == "service_account"
            assert restored.authorization_subject_id == 44 and restored.effective_user_id is None
            assert all(restored.has_scope(code) == sa.has_scope(code) for code in admission.OPEN_API_SCOPE_CODES)
            assert get_current_permission_actor().fga_subject == "service_account:44"
            assert continuation["actor"]["subject_type"] == "service_account"
            capture = AuthenticatedSourceReadIdentity()
            first = await capture.acapture(actual)
            assert first == await capture.acapture(actual) and first.request_tenant_id == 101


async def test_native_delete_precheck_and_empty_clear_restore_same_sa_through_reference_reads(
    application, context, sa, monkeypatch
):
    observed = []

    async def require_original(identity, **kwargs):
        assert isinstance(identity, UserPayload) and identity.user_id == 7
        assert not identity.is_global_super and identity.user_role == []
        current = get_current_open_api_principal()
        assert current.authorization_subject_type == "service_account" and current.authorization_subject_id == 44
        assert get_current_permission_actor().fga_subject == "service_account:44"
        assert kwargs["action"] == "delete"
        observed.append(current)

    monkeypatch.setattr(native.native.module, "require_business_action", require_original)
    with credentials.request_context(actor(), sa):
        review = await application.aprecheck(identity=application.user, space_id=2, operation="knowledge_space_delete")
        assert review.can_execute and not review.invalid_items
        async with context.db.sessions() as session:
            plan = await session.get(KnowledgeOperationPlan, review.confirmation_id)
            assert plan.actor_user_id == 7
            assert plan.actor_reference["actor"]["subject_type"] == "service_account"
            assert plan.actor_reference["actor"]["subject_id"] == 44
        manifest = await application.aordinary_delete(
            identity=application.user, space_id=2, operation="knowledge_space_clear"
        )
        assert manifest["rows"] == []
    assert len(observed) >= 2
    application.permission_runtime.project_delete.assert_not_awaited()


@pytest.mark.parametrize("invalid", ["revoked", "tenant", "subject", "scope"])
async def test_original_credential_gates_still_reject_before_audit_bridge(application, sa, api_ports, invalid):
    with credentials.request_context(actor(), sa):
        reference = await admission.capture(application.user, space_id=2)
        if invalid == "revoked":
            api_ports.row.is_valid_at = lambda now: False
        elif invalid == "tenant":
            api_ports.row.tenant_id = 202
        elif invalid == "subject":
            api_ports.current[0] = principal(actor_id=45, authorization_subject_id=45)
        else:
            api_ports.current[0] = principal(scopes=frozenset({"knowledge:read"}))
        with pytest.raises((PermissionDeniedError, OpenApiScopeMissingError)):
            async with admission.identity(reference, current=application.user):
                pytest.fail("invalid credential reached the deletion body")


@pytest.mark.parametrize("invalid", ["missing", "disabled", "foreign"])
async def test_native_audit_owner_must_exist_be_active_and_same_tenant(application, context, sa, invalid):
    async with context.db.sessions() as session, session.begin():
        if invalid == "missing":
            await session.execute(delete(User).where(User.user_id == 7))
        elif invalid == "disabled":
            (await session.get(User, 7)).delete = 1
        else:
            from sqlalchemy import select

            row = (await session.execute(select(UserTenant).where(UserTenant.user_id == 7))).scalar_one()
            row.tenant_id = 202
    with credentials.request_context(actor(), sa):
        reference = await admission.capture(application.user, space_id=2)
        with pytest.raises(HTTPException) as error:
            async with admission.identity(reference, current=application.user):
                pytest.fail("unavailable audit owner reached the deletion body")
        assert error.value.status_code == 404


@pytest.mark.parametrize("case", ["actual", "clone", "other", "absent", "owner_actor", "tenant"])
async def test_generic_reference_identity_still_refuses_raw_principal(case):
    original, supplied, current_actor, tenant = principal(), None, actor(), 101
    supplied = original
    if case == "clone":
        supplied = original.model_copy()
    elif case == "other":
        supplied = principal(credential_id=21)
    elif case == "owner_actor":
        current_actor = PermissionActor(subject_type="user", subject_id=7, tenant_id=101, super_admin=True)
    elif case == "tenant":
        tenant = 202
    with credentials.request_context(current_actor, None if case == "absent" else original, tenant=tenant):
        with pytest.raises(ResourceReferenceInvalidError):
            await AuthenticatedSourceReadIdentity().acapture(supplied)
