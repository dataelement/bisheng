"""Pending personal reviews can join a real external Session. 覆盖 AC: AC-68, AC-79, AC-83, AC-87, AC-88, AC-89, AC-91."""

from contextlib import asynccontextmanager

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.application.app_review import pending_app_reviews
from bisheng.approval.domain.models.approval_instance import ApprovalInstance, ApprovalTask
from bisheng.approval.domain.repositories import app_review_repository as repository
from bisheng.core.context.tenant import current_tenant_id, get_current_tenant_id, set_current_tenant_id


@pytest.fixture
async def reviews(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'reviews.db'}")
    metadata = sa.MetaData()
    for model in (ApprovalInstance, ApprovalTask):
        sa.Table(
            model.__tablename__,
            metadata,
            *[
                sa.Column(
                    col.name,
                    col.type.copy(),
                    primary_key=col.primary_key,
                    nullable=col.nullable,
                    server_default=sa.text("CURRENT_TIMESTAMP")
                    if col.name in {"create_time", "update_time"}
                    else col.server_default,
                )
                for col in model.__table__.columns
            ],
        )
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        for index, version in ((1, "v1"), (2, "v2")):
            await connection.execute(
                sa.insert(ApprovalInstance).values(
                    id=index,
                    tenant_id=101,
                    scenario_code="app_publish_request",
                    scenario_name="app",
                    handler_key="app",
                    business_key=f"app:{version}",
                    business_resource_type="app",
                    business_resource_id="app",
                    business_name="app",
                    applicant_user_id=4,
                    applicant_user_name="owner",
                    status="pending",
                    payload_snapshot={"version_id": version},
                    detail_snapshot={},
                )
            )
            await connection.execute(
                sa.insert(ApprovalTask).values(
                    id=index,
                    tenant_id=101,
                    instance_id=index,
                    flow_version_id=1,
                    node_code="review",
                    node_name="review",
                    node_order=0,
                    approver_user_id=22,
                    approver_source_type="direct_user",
                    node_mode="or",
                    status="pending",
                )
            )

    @asynccontextmanager
    async def factory():
        async with AsyncSession(engine) as session:
            yield session

    monkeypatch.setattr(repository, "get_async_db_session", factory)
    token = set_current_tenant_id(303)
    try:
        yield engine
    finally:
        current_tenant_id.reset(token)
        await engine.dispose()


async def test_external_session_keeps_personal_scope_original_and_only_requested_version(reviews, monkeypatch):
    @asynccontextmanager
    async def forbidden_factory():
        raise AssertionError("external review must not open another Session")
        yield

    monkeypatch.setattr(repository, "get_async_db_session", forbidden_factory)
    async with AsyncSession(reviews) as session, session.begin():
        result = await pending_app_reviews(22, "app", {"v1"}, session=session, for_update=True)
        assert [(item.tenant_id, item.version_id, item.task_id) for item in result] == [(101, "v1", 1)]
        assert not session.identity_map and not session.dirty
        assert get_current_tenant_id() == 303
        assert await pending_app_reviews(99, "app", {"v1"}, session=session) == ()
        assert await pending_app_reviews(22, "unrelated", {"v1"}, session=session) == ()


async def test_task_and_instance_current_terminal_changes_are_not_stale(reviews):
    async with AsyncSession(reviews) as session, session.begin():
        assert len(await pending_app_reviews(22, "app", {"v1"}, session=session)) == 1
        await session.execute(sa.update(ApprovalTask).where(ApprovalTask.id == 1).values(status="approved"))
        assert await pending_app_reviews(22, "app", {"v1"}, session=session, for_update=True) == ()
        await session.execute(sa.update(ApprovalInstance).where(ApprovalInstance.id == 2).values(status="cancelled"))
        assert await pending_app_reviews(22, "app", {"v2"}, session=session, for_update=True) == ()


async def test_legacy_no_session_caller_retains_result_and_does_not_switch_tenant(reviews):
    result = await pending_app_reviews(22, "app", {"v1", "v2"})
    assert {item.version_id for item in result} == {"v1", "v2"}
    assert get_current_tenant_id() == 303
