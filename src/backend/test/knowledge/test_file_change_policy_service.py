from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_scenario import (
    ApprovalFlowDefinition,
    ApprovalFlowVersion,
    ApprovalNodeDefinition,
    ApprovalRouteRule,
    ApprovalScenario,
)
from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    ChannelRelationEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    UserRoleEnum,
)
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum, Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_space_file_change_policy import (
    KnowledgeSpaceFileChangePolicy,
    KnowledgeSpaceFileChangePolicyScope,
    KnowledgeSpaceFileChangeSetting,
)
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_repository import (
    KnowledgeSpaceFileChangeRepository,
)
from bisheng.knowledge.domain.schemas.knowledge_space_file_change_schema import (
    KnowledgeSpaceFileChangePolicyUpdateReq,
    KnowledgeSpaceFileChangeSettingBulkItem,
)
from bisheng.knowledge.domain.services.knowledge_space_file_change_policy_service import (
    KnowledgeSpaceFileChangePolicyService,
)


@pytest_asyncio.fixture
async def policy_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        Knowledge.__table__,
        KnowledgeSpaceFileChangePolicy.__table__,
        KnowledgeSpaceFileChangeSetting.__table__,
        DepartmentKnowledgeSpace.__table__,
        SpaceChannelMember.__table__,
        ApprovalScenario.__table__,
        ApprovalRouteRule.__table__,
        ApprovalFlowDefinition.__table__,
        ApprovalFlowVersion.__table__,
        ApprovalNodeDefinition.__table__,
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync_connection: SQLModel.metadata.create_all(sync_connection, tables=tables))
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
def reset_tenant_context():
    token = current_tenant_id.set(None)
    yield
    current_tenant_id.reset(token)


def _service(engine) -> KnowledgeSpaceFileChangePolicyService:
    @asynccontextmanager
    async def session_factory():
        async with AsyncSession(bind=engine, expire_on_commit=False) as session:
            yield session

    return KnowledgeSpaceFileChangePolicyService(session_factory=session_factory)


async def _insert_space(
    engine,
    *,
    tenant_id: int,
    space_id: int,
    auth_type: AuthTypeEnum = AuthTypeEnum.PUBLIC,
    knowledge_type: KnowledgeTypeEnum = KnowledgeTypeEnum.SPACE,
) -> None:
    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        async with session.begin():
            session.add(
                Knowledge(
                    id=space_id,
                    tenant_id=tenant_id,
                    user_id=1,
                    name=f"space-{space_id}",
                    type=knowledge_type.value,
                    auth_type=auth_type,
                )
            )


async def _read_policy(engine, tenant_id: int) -> KnowledgeSpaceFileChangePolicy | None:
    async with AsyncSession(bind=engine) as session:
        statement = select(KnowledgeSpaceFileChangePolicy).where(KnowledgeSpaceFileChangePolicy.tenant_id == tenant_id)
        return (await session.exec(statement)).first()


async def _read_setting(engine, tenant_id: int, space_id: int) -> KnowledgeSpaceFileChangeSetting | None:
    async with AsyncSession(bind=engine) as session:
        statement = select(KnowledgeSpaceFileChangeSetting).where(
            KnowledgeSpaceFileChangeSetting.tenant_id == tenant_id,
            KnowledgeSpaceFileChangeSetting.space_id == space_id,
        )
        return (await session.exec(statement)).first()


async def test_missing_policy_defaults_to_enabled_per_space_and_unconfigured_space_requires_approval(policy_engine):
    set_current_tenant_id(17)
    await _insert_space(policy_engine, tenant_id=17, space_id=101)
    service = _service(policy_engine)

    policy = await service.get_policy()

    assert policy.enabled is True
    assert policy.scope == KnowledgeSpaceFileChangePolicyScope.PER_SPACE
    assert await service.is_approval_required(space_id=101) is True
    assert await _read_policy(policy_engine, 17) is None


async def test_non_space_knowledge_row_cannot_receive_file_change_policy(policy_engine):
    set_current_tenant_id(17)
    await _insert_space(
        policy_engine,
        tenant_id=17,
        space_id=101,
        knowledge_type=KnowledgeTypeEnum.NORMAL,
    )

    with pytest.raises(LookupError, match="knowledge space not found"):
        await _service(policy_engine).is_approval_required(space_id=101)


async def test_all_spaces_ignores_saved_per_space_opt_out(policy_engine):
    set_current_tenant_id(17)
    await _insert_space(policy_engine, tenant_id=17, space_id=101)
    service = _service(policy_engine)
    await service.save_space_setting(space_id=101, approval_required=False)
    await service.save_policy(enabled=True, scope=KnowledgeSpaceFileChangePolicyScope.ALL_SPACES)

    assert await service.is_approval_required(space_id=101) is True


async def test_per_space_uses_saved_value_and_defaults_unconfigured_space_to_required(policy_engine):
    set_current_tenant_id(17)
    await _insert_space(policy_engine, tenant_id=17, space_id=101)
    await _insert_space(policy_engine, tenant_id=17, space_id=102)
    service = _service(policy_engine)
    await service.save_space_setting(space_id=101, approval_required=False)
    await service.save_policy(enabled=True, scope=KnowledgeSpaceFileChangePolicyScope.PER_SPACE)

    assert await service.is_approval_required(space_id=101) is False
    assert await service.is_approval_required(space_id=102) is True


async def test_disabled_policy_bypasses_approval_and_reenable_preserves_space_setting(policy_engine):
    set_current_tenant_id(17)
    await _insert_space(policy_engine, tenant_id=17, space_id=101)
    service = _service(policy_engine)
    await service.save_space_setting(space_id=101, approval_required=False)
    await service.save_policy(enabled=False, scope=KnowledgeSpaceFileChangePolicyScope.PER_SPACE)

    assert await service.is_approval_required(space_id=101) is False

    await service.save_policy(enabled=True, scope=KnowledgeSpaceFileChangePolicyScope.PER_SPACE)

    assert await service.is_approval_required(space_id=101) is False
    setting = await _read_setting(policy_engine, 17, 101)
    assert setting is not None and setting.approval_required is False


async def test_private_space_never_requires_approval(policy_engine):
    set_current_tenant_id(17)
    await _insert_space(
        policy_engine,
        tenant_id=17,
        space_id=101,
        auth_type=AuthTypeEnum.PRIVATE,
    )
    service = _service(policy_engine)
    await service.save_policy(enabled=True, scope=KnowledgeSpaceFileChangePolicyScope.ALL_SPACES)
    await service.save_space_setting(space_id=101, approval_required=True)

    assert await service.is_approval_required(space_id=101) is False


async def test_failed_save_rolls_back_without_changing_effective_policy(policy_engine):
    set_current_tenant_id(17)
    service = _service(policy_engine)
    await service.save_policy(
        enabled=True,
        scope=KnowledgeSpaceFileChangePolicyScope.PER_SPACE,
    )

    with pytest.raises(RuntimeError, match="injected save failure"):
        async with AsyncSession(bind=policy_engine, expire_on_commit=False) as session:
            async with session.begin():
                await service.save_policy(
                    enabled=False,
                    scope=KnowledgeSpaceFileChangePolicyScope.ALL_SPACES,
                    session=session,
                )
                raise RuntimeError("injected save failure")

    policy = await service.get_policy()
    assert policy.enabled is True
    assert policy.scope == KnowledgeSpaceFileChangePolicyScope.PER_SPACE
    persisted = await _read_policy(policy_engine, 17)
    assert persisted is not None and persisted.enabled is True
    assert persisted.scope == KnowledgeSpaceFileChangePolicyScope.PER_SPACE


async def test_bulk_configuration_rolls_back_policy_and_every_setting_on_late_failure(
    policy_engine,
    monkeypatch,
):
    set_current_tenant_id(17)
    await _insert_space(policy_engine, tenant_id=17, space_id=101)
    await _insert_space(policy_engine, tenant_id=17, space_id=102)
    service = _service(policy_engine)
    await service.save_policy(enabled=True, scope=KnowledgeSpaceFileChangePolicyScope.PER_SPACE)
    original_save_setting = KnowledgeSpaceFileChangeRepository.save_setting

    async def fail_second_setting(self, *, tenant_id, space_id, approval_required):
        if int(space_id) == 102:
            raise RuntimeError("injected second setting failure")
        return await original_save_setting(
            self,
            tenant_id=tenant_id,
            space_id=space_id,
            approval_required=approval_required,
        )

    monkeypatch.setattr(KnowledgeSpaceFileChangeRepository, "save_setting", fail_second_setting)

    with pytest.raises(RuntimeError, match="second setting"):
        await service.save_configuration(
            policy=KnowledgeSpaceFileChangePolicyUpdateReq(
                enabled=False,
                scope=KnowledgeSpaceFileChangePolicyScope.ALL_SPACES,
            ),
            settings=[
                KnowledgeSpaceFileChangeSettingBulkItem(space_id=101, approval_required=False),
                KnowledgeSpaceFileChangeSettingBulkItem(space_id=102, approval_required=False),
            ],
        )

    policy = await _read_policy(policy_engine, 17)
    assert policy is not None and policy.enabled is True
    assert policy.scope == KnowledgeSpaceFileChangePolicyScope.PER_SPACE
    assert await _read_setting(policy_engine, 17, 101) is None
    assert await _read_setting(policy_engine, 17, 102) is None


async def test_bulk_configuration_rejects_cross_tenant_space_without_partial_write(policy_engine):
    await _insert_space(policy_engine, tenant_id=17, space_id=101)
    await _insert_space(policy_engine, tenant_id=18, space_id=201)
    set_current_tenant_id(17)
    service = _service(policy_engine)

    with pytest.raises(LookupError, match="knowledge space not found"):
        await service.save_configuration(
            policy=KnowledgeSpaceFileChangePolicyUpdateReq(
                enabled=False,
                scope=KnowledgeSpaceFileChangePolicyScope.ALL_SPACES,
            ),
            settings=[
                KnowledgeSpaceFileChangeSettingBulkItem(space_id=101, approval_required=False),
                KnowledgeSpaceFileChangeSettingBulkItem(space_id=201, approval_required=False),
            ],
        )

    assert await _read_policy(policy_engine, 17) is None
    assert await _read_setting(policy_engine, 17, 101) is None


async def test_bulk_configuration_preserves_group_and_department_space_sharing_rows(policy_engine):
    set_current_tenant_id(17)
    await _insert_space(policy_engine, tenant_id=17, space_id=101)
    await _insert_space(policy_engine, tenant_id=17, space_id=103)
    async with AsyncSession(bind=policy_engine, expire_on_commit=False) as session:
        async with session.begin():
            session.add(
                DepartmentKnowledgeSpace(
                    tenant_id=17,
                    department_id=300,
                    space_id=103,
                    created_by=1,
                )
            )
            session.add_all(
                [
                    SpaceChannelMember(
                        business_id="101",
                        business_type=BusinessTypeEnum.SPACE,
                        user_id=9,
                        user_role=UserRoleEnum.MEMBER,
                        relation=ChannelRelationEnum.EDITOR,
                        status=MembershipStatusEnum.ACTIVE,
                    ),
                    SpaceChannelMember(
                        business_id="103",
                        business_type=BusinessTypeEnum.SPACE,
                        user_id=10,
                        user_role=UserRoleEnum.MEMBER,
                        relation=ChannelRelationEnum.VIEWER,
                        status=MembershipStatusEnum.ACTIVE,
                        membership_source="department_admin",
                    ),
                ]
            )

    await _service(policy_engine).save_configuration(
        policy=KnowledgeSpaceFileChangePolicyUpdateReq(
            enabled=True,
            scope=KnowledgeSpaceFileChangePolicyScope.PER_SPACE,
        ),
        settings=[
            KnowledgeSpaceFileChangeSettingBulkItem(space_id=101, approval_required=False),
            KnowledgeSpaceFileChangeSettingBulkItem(space_id=103, approval_required=True),
        ],
    )

    async with AsyncSession(bind=policy_engine) as session:
        spaces = (await session.exec(select(Knowledge).order_by(Knowledge.id))).all()
        binding = (await session.exec(select(DepartmentKnowledgeSpace))).one()
        members = (await session.exec(select(SpaceChannelMember).order_by(SpaceChannelMember.user_id))).all()
    assert [(space.id, space.auth_type) for space in spaces] == [
        (101, AuthTypeEnum.PUBLIC),
        (103, AuthTypeEnum.PUBLIC),
    ]
    assert (binding.tenant_id, binding.department_id, binding.space_id) == (17, 300, 103)
    assert [
        (member.business_id, member.user_id, member.relation, member.membership_source)
        for member in members
    ] == [
        ("101", 9, ChannelRelationEnum.EDITOR, "manual"),
        ("103", 10, ChannelRelationEnum.VIEWER, "department_admin"),
    ]


async def test_tenant_configuration_is_strictly_isolated_without_root_fallback(policy_engine):
    await _insert_space(policy_engine, tenant_id=1, space_id=101)
    await _insert_space(policy_engine, tenant_id=17, space_id=201)
    service = _service(policy_engine)

    set_current_tenant_id(1)
    await service.save_policy(enabled=False, scope=KnowledgeSpaceFileChangePolicyScope.ALL_SPACES)

    set_current_tenant_id(17)
    tenant_policy = await service.get_policy()
    assert tenant_policy.enabled is True
    assert tenant_policy.scope == KnowledgeSpaceFileChangePolicyScope.PER_SPACE
    assert await service.is_approval_required(space_id=201) is True
    assert await _read_policy(policy_engine, 17) is None

    with pytest.raises(LookupError, match="knowledge space not found"):
        await service.is_approval_required(space_id=101)


async def test_service_refuses_to_operate_without_tenant_context(policy_engine):
    service = _service(policy_engine)

    with pytest.raises(RuntimeError, match="tenant context is required"):
        await service.get_policy()


class _NestedTransaction:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def __aenter__(self):
        self.events.append("savepoint.begin")

    async def __aexit__(self, exc_type, _exc, _traceback):
        self.events.append("savepoint.rollback" if exc_type is not None else "savepoint.commit")


class _PolicyResult:
    def __init__(self, row) -> None:
        self.row = row

    def first(self):
        return self.row


class _ConcurrentInsertSession:
    def __init__(self, winning_row: KnowledgeSpaceFileChangePolicy) -> None:
        self.winning_row = winning_row
        self.events: list[str] = []
        self.select_count = 0
        self.statements = []

    async def exec(self, statement):
        self.select_count += 1
        self.statements.append(statement)
        is_locked = statement._for_update_arg is not None
        self.events.append(f"select.{'for_update' if is_locked else 'plain'}")
        return _PolicyResult(None if self.select_count == 1 else self.winning_row)

    def begin_nested(self):
        return _NestedTransaction(self.events)

    def add(self, _row) -> None:
        self.events.append("insert")

    async def flush(self) -> None:
        self.events.append("flush")
        raise IntegrityError("duplicate tenant policy", {}, Exception("duplicate key"))


async def test_concurrent_ensure_rolls_back_savepoint_then_locks_winning_policy_row():
    winner = KnowledgeSpaceFileChangePolicy(id=9, tenant_id=17)
    session = _ConcurrentInsertSession(winner)
    repository = KnowledgeSpaceFileChangeRepository(session)  # type: ignore[arg-type]

    result = await repository.ensure_policy_row(tenant_id=17, for_update=True)

    assert result is winner
    assert session.events == [
        "select.plain",
        "savepoint.begin",
        "insert",
        "flush",
        "savepoint.rollback",
        "select.for_update",
    ]


async def test_repository_bulk_setting_query_always_contains_explicit_tenant_predicate():
    session = SimpleNamespace(exec=None)
    repository = KnowledgeSpaceFileChangeRepository(session)  # type: ignore[arg-type]
    statement = repository.build_settings_by_space_ids_statement(tenant_id=17, space_ids=[1, 2])
    rendered = str(statement)

    assert "knowledge_space_file_change_setting.tenant_id" in rendered
    assert "knowledge_space_file_change_setting.space_id IN" in rendered
