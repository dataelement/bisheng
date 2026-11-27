"""受影响用户展开、去重、跨租户与草稿绑定分页单测。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.permission import (
    PermissionImpactExpiredError,
    PermissionVersionConflictError,
)
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models.department import Department, UserDepartment
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.database.models.user_group import UserGroup
from bisheng.user.domain.models.user import User
from bisheng.permission.domain.models import (
    AuthorizationModelRelease,
    PermissionAction,
    PermissionActionResourceScope,
    PermissionCatalogProjectionTuple,
    PermissionCatalogRelease,
    PermissionGrant,
    PermissionGrantAssignee,
    PermissionModel,
    PermissionModelAction,
    PermissionProjectionOperation,
    PermissionVisibleSourceProjection,
)
from bisheng.permission.domain.schemas import (
    CatalogChangeRequest,
    CatalogChangeType,
    CatalogDraftRequest,
    CatalogPublishRequest,
)
from bisheng.permission.domain.services.grant_source_service import GrantSourceService
from test.permission.test_f048_catalog_runtime import (
    TABLE_NAMES,
    FakeCatalogMarker,
    InMemoryCatalogFGA,
    _api,
    _seed_current,
)


@pytest.fixture
async def affected_session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        *(SQLModel.metadata.tables[name] for name in TABLE_NAMES),
        Tenant.__table__,
        User.__table__,
        UserTenant.__table__,
        Department.__table__,
        UserDepartment.__table__,
    ]
    metadata = sa.MetaData()
    for table in tables:
        cloned = table.to_metadata(metadata)
        if "id" in cloned.c:
            cloned.c.id.type = sa.Integer()
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        # SQLite 不支持复合主键上的 AUTOINCREMENT，手动创建 usergroup 表
        await connection.execute(
            sa_text(
                "CREATE TABLE usergroup ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "user_id INTEGER NOT NULL, "
                "group_id INTEGER NOT NULL, "
                "is_group_admin BOOLEAN NOT NULL DEFAULT 0, "
                "remark VARCHAR(255), "
                "tenant_id INTEGER NOT NULL DEFAULT 1, "
                "create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, "
                "update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)"
            )
        )

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def factory():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    try:
        yield factory
    finally:
        await engine.dispose()


async def test_affected_users_expand_dedup_cross_tenant_pagination_and_expiry(
    affected_session_factory,
) -> None:
    """验证展开（直接/部门含子部门/用户组）、去重、同名区分、排服务账号与停用用户、跨租户分页、零影响及过期/版本冲突校验。"""
    fga = InMemoryCatalogFGA()
    marker = FakeCatalogMarker()
    current = await _seed_current(affected_session_factory, fga)
    sources = GrantSourceService()

    with bypass_tenant_filter():
        async with affected_session_factory() as session:
            async with session.begin():
                session.add_all(
                    [
                        Tenant(id=1, tenant_code="root", tenant_name="总部租户"),
                        Tenant(id=2, tenant_code="sub", tenant_name="华东子公司"),
                    ]
                )
                session.add_all(
                    [
                        User(user_id=101, user_name="alice", password="x", delete=0),
                        User(user_id=102, user_name="bob", password="x", delete=0),
                        User(user_id=103, user_name="charlie", password="x", delete=0),
                        # 同名不同 user_id（跨租户）
                        User(user_id=201, user_name="alice", password="x", delete=0),
                        # 已停用用户，不应计入
                        User(user_id=104, user_name="disabled_user", password="x", delete=1),
                    ]
                )
                session.add_all(
                    [
                        UserTenant(id=1, user_id=101, tenant_id=1, status="active", is_active=1),
                        UserTenant(id=2, user_id=102, tenant_id=1, status="active", is_active=1),
                        UserTenant(id=3, user_id=103, tenant_id=1, status="active", is_active=1),
                        UserTenant(id=4, user_id=201, tenant_id=2, status="active", is_active=1),
                        UserTenant(id=5, user_id=104, tenant_id=1, status="active", is_active=1),
                    ]
                )
                session.add_all(
                    [
                        Department(id=10, dept_id="D10", name="研发部", tenant_id=1, path="/10/"),
                        Department(id=11, dept_id="D11", name="后端组", parent_id=10, tenant_id=1, path="/10/11/"),
                    ]
                )
                session.add_all(
                    [
                        # 101 在研发部，102 在子部门后端组，104 已停用也在研发部
                        UserDepartment(id=1, user_id=101, department_id=10),
                        UserDepartment(id=2, user_id=102, department_id=11),
                        UserDepartment(id=3, user_id=104, department_id=10),
                    ]
                )
                session.add_all(
                    [
                        # 用户组 50 包含 101（与直接/部门重叠）和 103
                        UserGroup(id=1, user_id=101, group_id=50, is_group_admin=False, tenant_id=1),
                        UserGroup(id=2, user_id=103, group_id=50, is_group_admin=True, tenant_id=1),
                    ]
                )

                # 租户1 上使用 collaborator 模板的两条授权（folder 1 和 folder 2）
                grant1 = PermissionGrant(
                    tenant_id=1,
                    resource_type="folder",
                    resource_id="f-1",
                    model_key="collaborator",
                    state="ACTIVE",
                    projection_state="CURRENT",
                )
                grant2 = PermissionGrant(
                    tenant_id=2,
                    resource_type="folder",
                    resource_id="f-2",
                    model_key="collaborator",
                    state="ACTIVE",
                    projection_state="CURRENT",
                )
                session.add_all([grant1, grant2])
                await session.flush()

                assignee_specs = [
                    (1, int(grant1.id), sources.canonicalize_source(source_id=1, subject_type="user", subject_id="101", source_type="DIRECT")),
                    (1, int(grant1.id), sources.canonicalize_source(source_id=2, subject_type="department", subject_id="10", userset_relation="subtree_member", include_children=True, source_type="DEPARTMENT")),
                    (1, int(grant1.id), sources.canonicalize_source(source_id=3, subject_type="user_group", subject_id="50", userset_relation="member", source_type="USER_GROUP")),
                    # 服务账号应被排除
                    (1, int(grant1.id), sources.canonicalize_source(source_id=4, subject_type="service_account", subject_id="999", source_type="DIRECT")),
                    # 租户2 直接授权给同名用户 201
                    (2, int(grant2.id), sources.canonicalize_source(source_id=5, subject_type="user", subject_id="201", source_type="DIRECT")),
                ]
                for tenant_id, grant_id, src in assignee_specs:
                    session.add(
                        PermissionGrantAssignee(
                            tenant_id=tenant_id,
                            grant_id=grant_id,
                            subject_type=src.subject_type,
                            subject_id=src.subject_id,
                            userset_relation=src.userset_relation,
                            include_children=src.include_children,
                            source_type=src.source_type,
                            source_ref=src.source_ref,
                            source_locator=src.source_locator,
                            source_fingerprint=src.source_fingerprint,
                            projected_subject=src.projected_subject,
                            protected=src.protected,
                            state="ACTIVE",
                        )
                    )

    api = _api(affected_session_factory, fga, marker)

    # 1) 仅修改名称不改变有效操作 -> 受影响用户应为 0
    rename_draft = await api.create_draft(
        request=CatalogDraftRequest(
            idempotency_key="rename-only",
            base_release_id=int(current.id),
            changes=(
                CatalogChangeRequest(
                    type=CatalogChangeType.UPDATE_MODEL,
                    model_key="collaborator",
                    name="协作者改名",
                ),
            ),
        ),
        operator_id=7,
    )
    assert rename_draft["impact"]["affected_user_count"] == 0
    assert rename_draft["impact"]["affected_users"] == []
    assert rename_draft["impact"]["affected_users_has_more"] is False

    # 2) 修改 collaborator 有效操作（新增 download）-> 展开去重应为 4 人：101, 201 (同名 alice), 102 (bob), 103 (charlie)
    edit_draft = await api.create_draft(
        request=CatalogDraftRequest(
            idempotency_key="edit-collab-actions",
            base_release_id=int(current.id),
            changes=(
                CatalogChangeRequest(
                    type=CatalogChangeType.UPDATE_MODEL,
                    model_key="collaborator",
                    action_codes=("download", "edit"),
                ),
            ),
        ),
        operator_id=7,
    )
    impact = edit_draft["impact"]
    assert impact["affected_user_count"] == 4
    assert impact["affected_users_cross_tenant"] is True
    assert impact["affected_users_has_more"] is False
    assert [(u["user_id"], u["username"], u["tenant_name"]) for u in impact["affected_users"]] == [
        (101, "alice", "总部租户"),
        (201, "alice", "华东子公司"),
        (102, "bob", "总部租户"),
        (103, "charlie", "总部租户"),
    ]

    # 3) 草稿绑定分页查询（page_size=2）
    page1 = await api.list_draft_affected_users(
        draft_id=edit_draft["draft_id"],
        operator_id=7,
        page=1,
        page_size=2,
    )
    page2 = await api.list_draft_affected_users(
        draft_id=edit_draft["draft_id"],
        operator_id=7,
        page=2,
        page_size=2,
    )
    assert page1["total"] == 4
    assert page1["has_more"] is True
    assert page1["cross_tenant"] is True
    assert [u["user_id"] for u in page1["items"]] == [101, 201]
    assert page2["total"] == 4
    assert page2["has_more"] is False
    assert [u["user_id"] for u in page2["items"]] == [102, 103]

    # 4) 草稿过期后拒绝返回分页名单
    async with affected_session_factory() as session:
        async with session.begin():
            row = await session.get(PermissionCatalogRelease, edit_draft["draft_id"])
            row.expires_at = (datetime.now(UTC) - timedelta(minutes=1)).replace(tzinfo=None)
    with pytest.raises(PermissionImpactExpiredError):
        await api.list_draft_affected_users(
            draft_id=edit_draft["draft_id"],
            operator_id=7,
            page=1,
            page_size=2,
        )

    # 5) 恢复未过期但发布另一个草稿导致基准版本变更 -> 报 PermissionVersionConflictError
    async with affected_session_factory() as session:
        async with session.begin():
            row = await session.get(PermissionCatalogRelease, edit_draft["draft_id"])
            row.expires_at = (datetime.now(UTC) + timedelta(minutes=10)).replace(tzinfo=None)
    await api.publish_draft(
        draft_id=rename_draft["draft_id"],
        request=CatalogPublishRequest(
            expected_current_release_id=int(current.id),
            idempotency_key="pub-rename-only",
            confirmed=True,
        ),
        operator_id=7,
    )
    with pytest.raises(PermissionVersionConflictError):
        await api.list_draft_affected_users(
            draft_id=edit_draft["draft_id"],
            operator_id=7,
            page=1,
            page_size=2,
        )
