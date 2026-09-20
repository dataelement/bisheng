"""Department/role grants resolve to one immediate per-user model allowance."""

import pytest
from sqlalchemy import Column, DateTime, Integer, MetaData, Table, create_engine, delete, text
from sqlmodel import Session, select

from bisheng.common.errcode.dsh import DshOperationConflictError, DshSeatLimitReachedError
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.database.models.department import Department, UserDepartment
from bisheng.database.models.role import Role
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.dsh.domain.models.admin_operation import DshAdminOperation
from bisheng.dsh.domain.models.model_call import DshModelCall
from bisheng.dsh.domain.models.monthly_usage import DshMonthlyUsage
from bisheng.dsh.domain.models.subject_policy import DshSubjectPolicy, DshSubjectPolicyAudit
from bisheng.dsh.domain.models.user_policy import DshUserPolicy
from bisheng.dsh.domain.repositories.subject_policy import DshSubjectPolicyRepository
from bisheng.dsh.domain.repositories.usage import DshUsageRepository
from bisheng.user.domain.models.user import User
from bisheng.user.domain.models.user_role import UserRole
from test.dsh.test_quota_admission import running
from test.dsh.test_quota_settlement import terminal


@pytest.fixture
def subject_store(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'subject-policy.db'}")
    Table(
        "userrole",
        MetaData(),
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("user_id", Integer, nullable=False),
        Column("role_id", Integer, nullable=False),
        Column("tenant_id", Integer, nullable=False, server_default=text("1")),
        Column("create_time", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
        Column("update_time", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    ).create(engine)
    for model in (
        Tenant,
        User,
        Department,
        Role,
        UserDepartment,
        UserTenant,
        DshUserPolicy,
        DshAdminOperation,
        DshModelCall,
        DshMonthlyUsage,
        DshSubjectPolicy,
        DshSubjectPolicyAudit,
    ):
        model.__table__.create(engine)
    token = set_current_tenant_id(2)
    with Session(engine) as session, session.begin():
        session.add_all(
            [
                Tenant(id=2, tenant_code="tenant-2", tenant_name="测试组织"),
                User(user_id=20, user_name="admin", password="x"),
                User(user_id=21, user_name="guest", password="x"),
                Department(id=10, dept_id="root", name="研发中心", tenant_id=2, parent_id=None, path="/10/"),
                Department(id=11, dept_id="child", name="平台组", tenant_id=2, parent_id=10, path="/10/11/"),
                Department(
                    id=12,
                    dept_id="first-root",
                    name="综合管理部",
                    tenant_id=2,
                    parent_id=None,
                    path="/12/",
                    sort_order=-1,
                ),
                Role(id=41, role_name="产品经理", role_type="tenant", tenant_id=2),
                Role(id=42, role_name="审阅者", role_type="global", tenant_id=1),
                UserTenant(id=1, user_id=20, tenant_id=2, status="active", is_active=1),
                UserTenant(id=2, user_id=21, tenant_id=2, status="active", is_active=1),
                UserDepartment(id=100, user_id=20, department_id=11),
                UserRole(id=200, user_id=20, role_id=41, tenant_id=2),
            ]
        )
    yield engine
    current_tenant_id.reset(token)
    engine.dispose()


def update(repository, subject_type, subject_id, limit, *, expected=0, enabled=True):
    return repository.update(
        subject_type=subject_type,
        subject_id=subject_id,
        model_id=7,
        actor_user_id=90,
        expected_version=expected,
        monthly_token_limit=limit,
        enabled=enabled,
    )


def test_parent_department_future_member_and_role_overlap_use_highest_limit(subject_store):
    with Session(subject_store) as session, session.begin():
        repository = DshSubjectPolicyRepository(session)
        update(repository, "DEPARTMENT", 10, 100)
        update(repository, "ROLE", 41, 300)
        session.add(
            DshUserPolicy(
                tenant_id=2,
                user_id=20,
                model_id=7,
                monthly_token_limit=200,
                enabled=1,
                version=1,
                quota_sync_state="READY",
                quota_epoch=1,
                updated_by=90,
            )
        )
    with Session(subject_store) as session, session.begin():
        repository = DshSubjectPolicyRepository(session)
        policy = repository.effective(20)
        assert policy.allowed_model_ids == [7]
        assert policy.rows[0].monthly_token_limit == 300
        session.exec(delete(UserRole).where(UserRole.user_id == 20, UserRole.role_id == 41))
        session.flush()
        assert repository.effective(20).rows[0].monthly_token_limit == 200
        direct = session.exec(select(DshUserPolicy).where(DshUserPolicy.user_id == 20)).one()
        direct.enabled = 0
        session.add(UserDepartment(id=101, user_id=21, department_id=11))
        session.flush()
        assert repository.effective(20).rows[0].monthly_token_limit == 100
        assert repository.effective(21).rows[0].monthly_token_limit == 100


def test_department_grant_rejects_the_complete_change_when_seats_are_insufficient(subject_store):
    with Session(subject_store) as session, session.begin():
        session.add(UserDepartment(id=101, user_id=21, department_id=11))
        repository = DshSubjectPolicyRepository(session)
        with pytest.raises(DshSeatLimitReachedError):
            repository.update(
                subject_type="DEPARTMENT",
                subject_id=10,
                model_id=7,
                actor_user_id=90,
                expected_version=0,
                monthly_token_limit=100,
                enabled=True,
                seat_limit=1,
            )
        assert repository.inventory(7)["departments"][1]["version"] == 0
        assert session.exec(select(DshSubjectPolicyAudit)).all() == []


def test_user_permission_page_explains_department_role_and_legacy_sources(subject_store):
    with Session(subject_store) as session, session.begin():
        repository = DshSubjectPolicyRepository(session)
        update(repository, "DEPARTMENT", 10, 100)
        update(repository, "ROLE", 41, 300)
        session.add(
            DshUserPolicy(
                tenant_id=2,
                user_id=20,
                model_id=7,
                monthly_token_limit=200,
                enabled=1,
                version=1,
                quota_sync_state="READY",
                quota_epoch=1,
                updated_by=90,
            )
        )
        session.flush()
        page = repository.user_permissions(
            [(20, "admin"), (21, "guest")],
            model_id=7,
            limit=20,
            selected_department_id=10,
        )
        assert page["has_more"] is False and page["next_cursor"] is None
        admin = page["items"][0]
        assert admin["user_name"] == "admin"
        assert admin["department_match"] == "DESCENDANT"
        assert admin["departments"] == [{"id": 11, "name": "平台组", "is_primary": True}]
        assert admin["roles"] == [{"id": 41, "name": "产品经理"}]
        assert admin["authorized"] is True and admin["monthly_token_limit"] == 300
        assert {
            (source["subject_type"], source["monthly_token_limit"], source["inherited"], source["winning"])
            for source in admin["sources"]
        } == {
            ("DEPARTMENT", 100, True, False),
            ("ROLE", 300, False, True),
            ("USER", 200, False, False),
        }
        assert page["items"][1]["authorized"] is False
        assert repository.department_scope_ids(10, include_descendants=False) == [10]
        assert repository.department_scope_ids(10, include_descendants=True) == [10, 11]


def test_inventory_versions_and_immutable_audit(subject_store):
    with Session(subject_store) as session, session.begin():
        repository = DshSubjectPolicyRepository(session)
        inventory = repository.inventory(7)
        assert [(row["name"], row["depth"]) for row in inventory["departments"]] == [
            ("综合管理部", 0),
            ("研发中心", 0),
            ("平台组", 1),
        ]
        assert {row["name"] for row in inventory["roles"]} == {"产品经理", "审阅者"}
        first = update(repository, "DEPARTMENT", 10, 100)
        assert first["version"] == 1
        second = update(repository, "DEPARTMENT", 10, 250, expected=1)
        assert second["version"] == 2
        with pytest.raises(DshOperationConflictError):
            update(repository, "DEPARTMENT", 10, 300, expected=1)
        audits = session.exec(select(DshSubjectPolicyAudit).order_by(DshSubjectPolicyAudit.id)).all()
        assert audits[0].before_values is None
        assert audits[0].after_values["monthly_token_limit"] == 100
        assert audits[1].before_values["version"] == 1
        assert audits[1].after_values["monthly_token_limit"] == 250


def test_subject_only_member_usage_projects_without_direct_user_policy(subject_store):
    with Session(subject_store) as session, session.begin():
        repository = DshSubjectPolicyRepository(session)
        update(repository, "DEPARTMENT", 10, 100)
        session.add(UserDepartment(id=101, user_id=21, department_id=11))
    event = terminal(running(model=7)).model_copy(update={"user_id": 21})
    with Session(subject_store) as session, session.begin():
        membership = session.exec(select(UserTenant).where(UserTenant.user_id == 21)).one()
        membership.status = "disabled"
        membership.is_active = None
    with Session(subject_store) as session, session.begin():
        assert DshUsageRepository(session).project_batch([event]) == 1
    with Session(subject_store) as session:
        call = session.exec(select(DshModelCall).where(DshModelCall.request_id == event.request_id)).one()
        total = session.exec(select(DshMonthlyUsage).where(DshMonthlyUsage.user_id == 21)).one()
        assert call.total_tokens == 300
        assert total.used_tokens == 300
