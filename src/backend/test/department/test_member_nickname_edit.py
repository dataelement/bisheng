"""F011 approved boundary: finish existing personnel writes, then nickname commit."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select

from bisheng.common.errcode.department import DepartmentInvalidRolesError, DepartmentPermissionDeniedError
from bisheng.common.errcode.user import NicknameValidationError
from bisheng.common.errcode.user_group import UserGroupPermissionDeniedError
from bisheng.database.models.audit_log import AuditLog
from bisheng.user.domain.models.user import User, UserDao
from bisheng.user.domain.models.user_role import UserRole, UserRoleDao
from bisheng.user.domain.services.nickname_service import NicknameService
from test.user.f011_fixtures import identity_store, nickname_store, old_user  # noqa: F401


@pytest.fixture
def personnel(nickname_store, monkeypatch, tmp_path):  # noqa: F811
    config = tmp_path / "member-settings.yaml"
    config.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("config", config.as_posix())
    from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
    from bisheng.department.domain.services import department_service as module
    from bisheng.user.domain.models import user_role as role_module
    from bisheng.user_group.domain.services.user_group_service import UserGroupService

    engine, repository = nickname_store
    target = old_user(engine, account="000TargetCase", name="OriginalNickname")
    operator = old_user(engine, account="OperatorCase", name="OperatorNickname")
    with Session(engine) as session:
        session.add(UserRole(user_id=target.user_id, role_id=2))
        session.commit()
    ctx = SimpleNamespace(id=10, dept_id="dept-10", status="active", path="/1/10/")
    membership = SimpleNamespace(user_id=target.user_id, department_id=10, is_primary=1)
    actor = SimpleNamespace(user_id=operator.user_id, user_name="StaleTokenName", tenant_id=5, user_role=[2])

    @asynccontextmanager
    async def context_session():
        yield SimpleNamespace(exec=AsyncMock(return_value=SimpleNamespace(first=lambda: membership)))

    async def read_user(user_id):
        with Session(engine) as session:
            row = session.get(User, user_id)
            if row is not None:
                session.expunge(row)
            return row

    monkeypatch.setattr(module, "get_async_db_session", context_session)
    permission = AsyncMock(return_value=ctx)
    monkeypatch.setattr(module, "_get_dept_and_check_permission", permission)
    monkeypatch.setattr(UserDao, "aget_user", read_user)
    monkeypatch.setattr(
        UserDao, "aupdate_user", AsyncMock(side_effect=AssertionError("Early nickname write is forbidden"))
    )
    # Identity tests isolate policy qualification through its public ports;
    # real role SQL writes remain separate from the real nickname transaction.
    from bisheng.department.application import business_scope
    from bisheng.role.application import effective_roles
    from bisheng.user.application import policy_bindings

    async def policy_subject(uid):
        with Session(engine) as session:
            rows = session.exec(select(UserRole).where(UserRole.user_id == uid)).all()
            return SimpleNamespace(user_id=uid, home_tenant_id=1, bindings=rows, memberships=[membership])

    async def replace_bindings(uid, home, replace_ids, picked, **kwargs):
        from bisheng.core.context.tenant import tenant_execution_scope

        assert home == 1
        with tenant_execution_scope(home):
            existing = {row.role_id for row in UserRoleDao.get_user_roles(uid)}
            if picked - existing:
                UserRoleDao.add_user_roles(uid, sorted(picked - existing))
            removed = (existing & replace_ids) - picked
            if removed:
                UserRoleDao.delete_user_roles(uid, sorted(removed))

    monkeypatch.setattr(policy_bindings, "read_policy_subject", policy_subject)
    monkeypatch.setattr(policy_bindings, "replace_policy_bindings", replace_bindings)
    monkeypatch.setattr(effective_roles, "load_effective_roles", AsyncMock(return_value=SimpleNamespace(role_ids=(2,))))
    monkeypatch.setattr(
        business_scope, "membership_policy_facts", AsyncMock(return_value=SimpleNamespace(business_tenant_id=1))
    )
    # Retain actual role DAO writes in their original separate SQL transaction.
    monkeypatch.setattr(role_module, "get_sync_db_session", repository.session_scope)
    monkeypatch.setattr(UserDepartmentDao, "aget_user_departments", AsyncMock(return_value=[membership]))
    monkeypatch.setattr(DepartmentDao, "aget_by_ids", AsyncMock(return_value=[ctx]))
    monkeypatch.setattr(module.DepartmentService, "_assignable_role_id_set", AsyncMock(return_value={2, 3}))
    groups = AsyncMock()
    monkeypatch.setattr(UserGroupService, "areplace_user_memberships", groups)
    sync = AsyncMock()
    monkeypatch.setattr(module.LegacyRBACSyncService, "sync_user_role_change", sync)
    monkeypatch.setattr(NicknameService, "profile_enabled", staticmethod(lambda: True))

    async def edit(**kwargs):
        from bisheng.department.domain.schemas.department_schema import DepartmentMemberEditApply

        return await module.DepartmentService.aapply_member_edit(
            ctx.dept_id,
            target.user_id,
            DepartmentMemberEditApply(primary_role_ids=[2], **kwargs),
            actor,
        )

    return SimpleNamespace(
        engine=engine,
        repository=repository,
        target=target,
        operator=operator,
        actor=actor,
        module=module,
        membership=membership,
        permission=permission,
        groups=groups,
        sync=sync,
        edit=edit,
    )


def snapshot(case):
    with Session(case.engine) as session:
        user = session.get(User, case.target.user_id)
        return user.user_name, user.nickname_customized, user.dsh_profile_version, user.token_version


@pytest.mark.parametrize("proposed", ["x" * 33, "bad name", "bad\u200bname", ""])
async def test_invalid_nickname_rejects_before_other_personnel_writes(personnel, proposed):
    """AC-04, AC-06, AC-07, AC-18, AC-23: invalid changes cannot begin other personnel writes."""
    with pytest.raises(NicknameValidationError):
        await personnel.edit(user_name=proposed, group_ids=[])
    assert snapshot(personnel) == ("OriginalNickname", False, 0, 0)
    personnel.groups.assert_not_awaited()
    assert [row.role_id for row in UserRoleDao.get_user_roles(personnel.target.user_id)] == [2]
    with Session(personnel.engine) as session:
        audits = session.exec(select(AuditLog)).all()
        assert len(audits) == 1 and audits[0].audit_metadata["result"] == "failure"


async def test_group_rejection_keeps_nickname_and_original_business_error(personnel):
    """AC-18, AC-23, AC-24: later personnel rejection must not leave an early rename."""
    personnel.groups.side_effect = UserGroupPermissionDeniedError()
    with pytest.raises(UserGroupPermissionDeniedError) as error:
        await personnel.edit(user_name="RequestedNickname", group_ids=[99])
    assert error.value.code == 23006
    assert snapshot(personnel) == ("OriginalNickname", False, 0, 0)
    with Session(personnel.engine) as session:
        assert session.exec(select(AuditLog)).one().audit_metadata["result"] == "failure"


async def test_role_rejection_keeps_nickname_before_other_owner_writes(personnel):
    """AC-18, AC-23: retain existing owner transactions without committing nickname."""
    from bisheng.department.domain.schemas.department_schema import DepartmentMemberEditApply

    with pytest.raises(DepartmentInvalidRolesError):
        await personnel.module.DepartmentService.aapply_member_edit(
            "dept-10",
            personnel.target.user_id,
            DepartmentMemberEditApply(user_name="RequestedNickname", primary_role_ids=[999], group_ids=[]),
            personnel.actor,
        )
    personnel.groups.assert_not_awaited()
    assert snapshot(personnel) == ("OriginalNickname", False, 0, 0)


async def test_success_commits_nickname_only_after_the_existing_role_transaction(personnel, monkeypatch):
    """AC-18, AC-22, AC-24: role commit precedes one atomic nickname and audit commit."""
    from bisheng.department.domain.schemas.department_schema import DepartmentMemberEditApply

    original_rename = NicknameService.arename_managed

    async def before_nickname(*args, **kwargs):
        assert snapshot(personnel) == ("OriginalNickname", False, 0, 0)
        assert [row.role_id for row in UserRoleDao.get_user_roles(personnel.target.user_id)] == [3]
        return await original_rename(*args, **kwargs)

    monkeypatch.setattr(NicknameService, "arename_managed", before_nickname)
    await personnel.module.DepartmentService.aapply_member_edit(
        "dept-10",
        personnel.target.user_id,
        DepartmentMemberEditApply(user_name="𠮷" * 32, primary_role_ids=[3]),
        personnel.actor,
        ip_address="198.51.100.8",
    )
    assert snapshot(personnel) == ("𠮷" * 32, True, 1, 0)
    with Session(personnel.engine) as session:
        user = session.get(User, personnel.target.user_id)
        assert user.external_id == "000TargetCase" and user.legacy_sso_name == "OriginalNickname"
        audit = session.exec(select(AuditLog)).one()
        assert audit.operator_id == personnel.operator.user_id and audit.operator_name == "OperatorNickname"
        assert audit.ip_address == "198.51.100.8"
        assert audit.audit_metadata == {
            "field": "user_name",
            "before": "OriginalNickname",
            "after": "𠮷" * 32,
            "result": "success",
        }


async def test_historical_original_is_not_trimmed_or_revalidated(personnel):
    """AC-06, AC-19: submitting an unchanged historical value is a true no-op."""
    original = " old nickname " + "x" * 40
    with Session(personnel.engine) as session:
        user = session.get(User, personnel.target.user_id)
        user.user_name = original
        session.add(user)
        session.commit()
    await personnel.edit(user_name=original)
    assert snapshot(personnel) == (original, False, 0, 0)
    with Session(personnel.engine) as session:
        assert session.exec(select(AuditLog)).all() == []


async def test_final_audit_failure_rolls_back_only_the_nickname_transaction(personnel, monkeypatch):
    """AC-23, AC-24: approved separate role writes remain; nickname state rolls back."""
    from bisheng.department.domain.schemas.department_schema import DepartmentMemberEditApply

    monkeypatch.setattr(personnel.repository, "stamp", Mock(side_effect=RuntimeError("audit unavailable")))
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await personnel.module.DepartmentService.aapply_member_edit(
            "dept-10",
            personnel.target.user_id,
            DepartmentMemberEditApply(user_name="RequestedNickname", primary_role_ids=[3]),
            personnel.actor,
        )
    assert snapshot(personnel) == ("OriginalNickname", False, 0, 0)
    assert [row.role_id for row in UserRoleDao.get_user_roles(personnel.target.user_id)] == [3]
    with Session(personnel.engine) as session:
        assert session.exec(select(AuditLog)).all() == []


@pytest.mark.parametrize("mode", ["affiliate", "synced"])
async def test_readonly_sources_do_not_gain_nickname_write_access(personnel, mode):
    """AC-18, AC-25: only the original local-primary management path can rename."""
    if mode == "affiliate":
        personnel.membership.is_primary = 0
    else:
        with Session(personnel.engine) as session:
            user = session.get(User, personnel.target.user_id)
            user.source = "generic_api"
            session.add(user)
            session.commit()
    from bisheng.department.domain.schemas.department_schema import DepartmentMemberEditApply

    await personnel.module.DepartmentService.aapply_member_edit(
        "dept-10", personnel.target.user_id, DepartmentMemberEditApply(user_name="RequestedNickname"), personnel.actor
    )
    assert snapshot(personnel) == ("OriginalNickname", False, 0, 0)


async def test_out_of_scope_request_is_rejected_before_nickname_work(personnel):
    """AC-18: do not replace the original department permission boundary."""
    personnel.permission.side_effect = DepartmentPermissionDeniedError()
    with pytest.raises(DepartmentPermissionDeniedError):
        await personnel.edit(user_name="RequestedNickname")
    assert snapshot(personnel) == ("OriginalNickname", False, 0, 0)


async def test_failure_audit_database_error_does_not_replace_validation_error(personnel, monkeypatch):
    """AC-23, AC-31: a rejected attempt stays rejected if failure logging is unavailable."""
    monkeypatch.setattr(
        personnel.repository, "_record_failure", Mock(side_effect=OperationalError("test-only", {}, RuntimeError()))
    )
    with pytest.raises(NicknameValidationError):
        await personnel.edit(user_name="x" * 33)
    assert snapshot(personnel) == ("OriginalNickname", False, 0, 0)


async def test_super_admin_target_does_not_gain_a_management_rename_path(personnel):
    """AC-18: retain the existing super-administrator target protection."""
    with Session(personnel.engine) as session:
        session.add(UserRole(user_id=personnel.target.user_id, role_id=1))
        session.commit()
    with pytest.raises(DepartmentPermissionDeniedError):
        await personnel.edit(user_name="RequestedNickname")
    assert snapshot(personnel) == ("OriginalNickname", False, 0, 0)


@pytest.mark.parametrize("proposed, expected_code", [("NicknameFromHttp", 200), ("x" * 33, 10614)])
async def test_real_member_route_preserves_actor_ip_and_field_error(personnel, proposed, expected_code):
    """AC-18, AC-24, AC-31: the real router forwards the authenticated editor and IP."""
    import httpx
    from fastapi import FastAPI

    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.department.api.endpoints.department_member import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/departments")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: personnel.actor
    transport = httpx.ASGITransport(app=app, client=("198.51.100.9", 41000))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/departments/dept-10/members/{personnel.target.user_id}/apply-edit",
            json={"user_name": proposed, "primary_role_ids": [2]},
        )
    assert response.status_code == 200 and response.json()["status_code"] == expected_code
    with Session(personnel.engine) as session:
        user = session.get(User, personnel.target.user_id)
        assert user.user_name == (proposed if expected_code == 200 else "OriginalNickname")
        audit = session.exec(select(AuditLog)).one()
        assert audit.operator_id == personnel.operator.user_id and audit.ip_address == "198.51.100.9"
