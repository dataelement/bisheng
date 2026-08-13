"""F045 — single space admin for department knowledge spaces.

Unit tests for DepartmentKnowledgeSpaceService admin configuration, atomic
replacement, invalidation (pending-admin state) and the no-creator-footprint
creation path. Collaborating DAOs / FGA / notifications are mocked; the DB
column swap semantics themselves are covered by the DAO conditional UPDATE
(exercised via mocks here, for real in CI integration runs).

AC coverage: AC-01 .. AC-11 (spec.md §2.1–§2.3).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.knowledge_space import (
    SpaceAdminConflictError,
    SpaceAdminInvalidUserError,
    SpaceAdminRequiredError,
    SpacePendingAdminError,
)
from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    UserRoleEnum,
)
from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
    DepartmentKnowledgeSpaceBatchCreateReq,
    DepartmentKnowledgeSpaceBatchItem,
)

# Reuse the heavy-import stub loader owned by the department service suite.
from test.department.test_department_knowledge_space_service import _load_service_class

_SERVICE_MODULE = "bisheng.knowledge.domain.services.department_knowledge_space_service"


def _make_login_user(*, user_id: int = 1, is_admin: bool = True):
    return SimpleNamespace(
        user_id=user_id,
        user_name="admin",
        tenant_id=1,
        is_admin=lambda: is_admin,
    )


def _make_department(*, dept_id: int = 10, name: str = "财务部"):
    return SimpleNamespace(id=dept_id, dept_id=f"BS@{dept_id}", name=name, status="active")


def _binding(*, row_id: int = 5, department_id: int = 10, space_id: int = 101, admin_user_id: int | None = 2):
    return SimpleNamespace(
        id=row_id,
        tenant_id=1,
        department_id=department_id,
        space_id=space_id,
        admin_user_id=admin_user_id,
    )


def _active_user(user_id: int = 2):
    return SimpleNamespace(user_id=user_id, user_name=f"u{user_id}", delete=0)


def _single_tenant_settings():
    return SimpleNamespace(multi_tenant=SimpleNamespace(enabled=False))


# ---------------------------------------------------------------------------
# _validate_admin_candidate — AC-01 / AC-02
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_admin_requires_user_id():
    service = _load_service_class()
    with patch(f"{_SERVICE_MODULE}.settings", _single_tenant_settings()):
        with pytest.raises(SpaceAdminRequiredError):
            await service._validate_admin_candidate(user_id=None, tenant_id=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("user_row", [None, SimpleNamespace(user_id=2, delete=1)])
async def test_validate_admin_rejects_missing_or_disabled_user(user_row):
    service = _load_service_class()
    with (
        patch(f"{_SERVICE_MODULE}.settings", _single_tenant_settings()),
        patch(f"{_SERVICE_MODULE}.UserDao.aget_user", new_callable=AsyncMock, return_value=user_row),
    ):
        with pytest.raises(SpaceAdminInvalidUserError):
            await service._validate_admin_candidate(user_id=2, tenant_id=1)


@pytest.mark.asyncio
async def test_validate_admin_rejects_out_of_tenant_user_when_multi_tenant():
    service = _load_service_class()
    with (
        patch(f"{_SERVICE_MODULE}.settings", SimpleNamespace(multi_tenant=SimpleNamespace(enabled=True))),
        patch(f"{_SERVICE_MODULE}.UserDao.aget_user", new_callable=AsyncMock, return_value=_active_user()),
        patch(
            f"{_SERVICE_MODULE}.UserTenantDao.aget_user_tenant",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        with pytest.raises(SpaceAdminInvalidUserError):
            await service._validate_admin_candidate(user_id=2, tenant_id=1)


@pytest.mark.asyncio
async def test_validate_admin_accepts_active_tenant_user():
    service = _load_service_class()
    with (
        patch(f"{_SERVICE_MODULE}.settings", SimpleNamespace(multi_tenant=SimpleNamespace(enabled=True))),
        patch(f"{_SERVICE_MODULE}.UserDao.aget_user", new_callable=AsyncMock, return_value=_active_user()),
        patch(
            f"{_SERVICE_MODULE}.UserTenantDao.aget_user_tenant",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(is_active=1),
        ),
    ):
        assert await service._validate_admin_candidate(user_id=2, tenant_id=1) == 2


# ---------------------------------------------------------------------------
# batch_create_spaces — AC-01 / AC-02 / AC-03 / AC-04
# ---------------------------------------------------------------------------


def _batch_req(admin_user_id: int | None):
    return DepartmentKnowledgeSpaceBatchCreateReq(
        items=[DepartmentKnowledgeSpaceBatchItem(department_id=10, admin_user_id=admin_user_id)]
    )


@pytest.mark.asyncio
async def test_batch_create_without_admin_creates_nothing():
    service = _load_service_class()
    with (
        patch(f"{_SERVICE_MODULE}.settings", _single_tenant_settings()),
        patch(
            f"{_SERVICE_MODULE}.DepartmentDao.aget_by_ids",
            new_callable=AsyncMock,
            return_value=[_make_department()],
        ),
        patch(
            f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceDao.aget_by_department_ids",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            f"{_SERVICE_MODULE}.KnowledgeSpaceService.create_knowledge_space",
            new_callable=AsyncMock,
        ) as mock_create,
    ):
        with pytest.raises(SpaceAdminRequiredError):
            await service.batch_create_spaces(
                request=SimpleNamespace(),
                login_user=_make_login_user(),
                req=_batch_req(admin_user_id=None),
            )
    mock_create.assert_not_awaited()


@pytest.mark.asyncio
async def test_batch_create_materializes_admin_without_creator_footprint():
    service = _load_service_class()
    created_space = SimpleNamespace(id=101)
    with (
        patch(f"{_SERVICE_MODULE}.settings", _single_tenant_settings()),
        patch(
            f"{_SERVICE_MODULE}.DepartmentDao.aget_by_ids",
            new_callable=AsyncMock,
            return_value=[_make_department()],
        ),
        patch(
            f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceDao.aget_by_department_ids",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(f"{_SERVICE_MODULE}.UserDao.aget_user", new_callable=AsyncMock, return_value=_active_user()),
        patch(
            f"{_SERVICE_MODULE}.KnowledgeSpaceService.create_knowledge_space",
            new_callable=AsyncMock,
            return_value=created_space,
        ) as mock_create,
        patch(
            f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceDao.acreate",
            new_callable=AsyncMock,
        ) as mock_acreate,
        patch(
            f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceService._grant_department_members_viewer",
            new_callable=AsyncMock,
        ),
        patch(
            f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceService._materialize_space_admin",
            new_callable=AsyncMock,
        ) as mock_materialize,
        patch(
            f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceService._notify",
            new_callable=AsyncMock,
        ) as mock_notify,
        patch(
            f"{_SERVICE_MODULE}.KnowledgeSpaceService.get_space_info",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(id=101),
        ),
    ):
        result = await service.batch_create_spaces(
            request=SimpleNamespace(),
            login_user=_make_login_user(),
            req=_batch_req(admin_user_id=2),
        )

    assert len(result) == 1
    # AC-04: the creating super admin leaves no front-facing footprint.
    assert mock_create.await_args.kwargs["materialize_creator"] is False
    # AC-03: the admin column and the materialized admin both point at user 2.
    assert mock_acreate.await_args.kwargs["admin_user_id"] == 2
    mock_materialize.assert_awaited_once_with(space_id=101, user_id=2)
    assert mock_notify.await_args.kwargs["receiver_user_ids"] == [2]


# ---------------------------------------------------------------------------
# replace_admin — AC-05 / AC-06 / AC-07 / AC-11
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replace_admin_swaps_atomically_and_tears_down_old():
    service = _load_service_class()
    calls: list[str] = []
    with (
        patch(f"{_SERVICE_MODULE}.settings", _single_tenant_settings()),
        patch(
            f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceDao.aget_by_department_id",
            new_callable=AsyncMock,
            return_value=_binding(admin_user_id=2),
        ),
        patch(f"{_SERVICE_MODULE}.UserDao.aget_user", new_callable=AsyncMock, return_value=_active_user(3)),
        patch(
            f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceDao.areplace_admin",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_swap,
        patch(
            f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceService._materialize_space_admin",
            new=AsyncMock(side_effect=lambda **kw: calls.append("materialize")),
        ),
        patch(
            f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceService._dematerialize_space_admin",
            new=AsyncMock(side_effect=lambda **kw: calls.append("dematerialize")),
        ),
        patch(f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceService._notify", new_callable=AsyncMock) as mock_notify,
        patch(
            f"{_SERVICE_MODULE}.KnowledgeSpaceService.get_space_info",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(id=101),
        ),
    ):
        await service.replace_admin(
            request=SimpleNamespace(),
            login_user=_make_login_user(),
            department_id=10,
            new_admin_user_id=3,
        )

    assert mock_swap.await_args.kwargs == {
        "row_id": 5,
        "expected_admin_user_id": 2,
        "new_admin_user_id": 3,
    }
    # AC-06: never a zero-admin window — new admin materialized first.
    assert calls == ["materialize", "dematerialize"]
    notified = [c.kwargs["receiver_user_ids"] for c in mock_notify.await_args_list]
    assert [2] in notified and [3] in notified


@pytest.mark.asyncio
async def test_replace_admin_conflict_raises_and_keeps_state():
    service = _load_service_class()
    with (
        patch(f"{_SERVICE_MODULE}.settings", _single_tenant_settings()),
        patch(
            f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceDao.aget_by_department_id",
            new_callable=AsyncMock,
            return_value=_binding(admin_user_id=2),
        ),
        patch(f"{_SERVICE_MODULE}.UserDao.aget_user", new_callable=AsyncMock, return_value=_active_user(3)),
        patch(
            f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceDao.areplace_admin",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceService._materialize_space_admin",
            new_callable=AsyncMock,
        ) as mock_materialize,
    ):
        with pytest.raises(SpaceAdminConflictError):
            await service.replace_admin(
                request=SimpleNamespace(),
                login_user=_make_login_user(),
                department_id=10,
                new_admin_user_id=3,
            )
    mock_materialize.assert_not_awaited()


@pytest.mark.asyncio
async def test_replace_admin_invalid_candidate_keeps_current_admin():
    service = _load_service_class()
    with (
        patch(f"{_SERVICE_MODULE}.settings", _single_tenant_settings()),
        patch(
            f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceDao.aget_by_department_id",
            new_callable=AsyncMock,
            return_value=_binding(admin_user_id=2),
        ),
        patch(f"{_SERVICE_MODULE}.UserDao.aget_user", new_callable=AsyncMock, return_value=None),
        patch(
            f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceDao.areplace_admin",
            new_callable=AsyncMock,
        ) as mock_swap,
    ):
        with pytest.raises(SpaceAdminInvalidUserError):
            await service.replace_admin(
                request=SimpleNamespace(),
                login_user=_make_login_user(),
                department_id=10,
                new_admin_user_id=99,
            )
    mock_swap.assert_not_awaited()


@pytest.mark.asyncio
async def test_replace_admin_on_pending_space_restores_normal_state():
    """AC-11: assigning a valid admin to a pending space clears the state."""
    service = _load_service_class()
    with (
        patch(f"{_SERVICE_MODULE}.settings", _single_tenant_settings()),
        patch(
            f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceDao.aget_by_department_id",
            new_callable=AsyncMock,
            return_value=_binding(admin_user_id=None),
        ),
        patch(f"{_SERVICE_MODULE}.UserDao.aget_user", new_callable=AsyncMock, return_value=_active_user(3)),
        patch(
            f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceDao.areplace_admin",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_swap,
        patch(
            f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceService._materialize_space_admin",
            new_callable=AsyncMock,
        ) as mock_materialize,
        patch(
            f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceService._dematerialize_space_admin",
            new_callable=AsyncMock,
        ) as mock_dematerialize,
        patch(f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceService._notify", new_callable=AsyncMock),
        patch(
            f"{_SERVICE_MODULE}.KnowledgeSpaceService.get_space_info",
            new_callable=AsyncMock,
            return_value=SimpleNamespace(id=101),
        ),
    ):
        await service.replace_admin(
            request=SimpleNamespace(),
            login_user=_make_login_user(),
            department_id=10,
            new_admin_user_id=3,
        )
    assert mock_swap.await_args.kwargs["expected_admin_user_id"] is None
    mock_materialize.assert_awaited_once()
    mock_dematerialize.assert_not_awaited()  # nobody to tear down


# ---------------------------------------------------------------------------
# materialize / dematerialize — AC-03 / AC-07
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dematerialize_restores_promoted_member_role():
    service = _load_service_class()
    module = __import__(_SERVICE_MODULE, fromlist=["SPACE_ADMIN_MEMBERSHIP_SOURCE"])
    member = SpaceChannelMember(
        business_id="101",
        business_type=BusinessTypeEnum.SPACE,
        user_id=2,
        user_role=UserRoleEnum.ADMIN,
        status=MembershipStatusEnum.ACTIVE,
        membership_source=module.SPACE_ADMIN_MEMBERSHIP_SOURCE,
        department_admin_promoted_from_role=UserRoleEnum.MEMBER.value,
    )
    with (
        patch(
            f"{_SERVICE_MODULE}.SpaceChannelMemberDao.async_find_member",
            new_callable=AsyncMock,
            return_value=member,
        ),
        patch(f"{_SERVICE_MODULE}.SpaceChannelMemberDao.update", new_callable=AsyncMock) as mock_update,
        patch(f"{_SERVICE_MODULE}.PermissionService.authorize", new_callable=AsyncMock) as mock_authorize,
    ):
        await service._dematerialize_space_admin(space_id=101, user_id=2)

    assert member.user_role == UserRoleEnum.MEMBER
    assert member.membership_source == "manual"
    assert member.department_admin_promoted_from_role is None
    mock_update.assert_awaited_once_with(member)
    revoke = mock_authorize.await_args.kwargs["revokes"][0]
    assert (revoke.subject_id, revoke.relation) == (2, "manager")


@pytest.mark.asyncio
async def test_dematerialize_removes_pure_admin_row():
    service = _load_service_class()
    module = __import__(_SERVICE_MODULE, fromlist=["SPACE_ADMIN_MEMBERSHIP_SOURCE"])
    member = SpaceChannelMember(
        business_id="101",
        business_type=BusinessTypeEnum.SPACE,
        user_id=2,
        user_role=UserRoleEnum.ADMIN,
        status=MembershipStatusEnum.ACTIVE,
        membership_source=module.SPACE_ADMIN_MEMBERSHIP_SOURCE,
    )
    with (
        patch(
            f"{_SERVICE_MODULE}.SpaceChannelMemberDao.async_find_member",
            new_callable=AsyncMock,
            return_value=member,
        ),
        patch(
            f"{_SERVICE_MODULE}.SpaceChannelMemberDao.delete_space_member",
            new_callable=AsyncMock,
        ) as mock_delete,
        patch(f"{_SERVICE_MODULE}.PermissionService.authorize", new_callable=AsyncMock),
    ):
        await service._dematerialize_space_admin(space_id=101, user_id=2)
    mock_delete.assert_awaited_once_with(101, 2)


@pytest.mark.asyncio
async def test_materialize_promotes_existing_member_and_grants_manager():
    service = _load_service_class()
    member = SpaceChannelMember(
        business_id="101",
        business_type=BusinessTypeEnum.SPACE,
        user_id=2,
        user_role=UserRoleEnum.MEMBER,
        status=MembershipStatusEnum.ACTIVE,
        membership_source="manual",
    )
    with (
        patch(
            f"{_SERVICE_MODULE}.SpaceChannelMemberDao.async_find_member",
            new_callable=AsyncMock,
            return_value=member,
        ),
        patch(f"{_SERVICE_MODULE}.SpaceChannelMemberDao.update", new_callable=AsyncMock),
        patch(f"{_SERVICE_MODULE}.PermissionService.authorize", new_callable=AsyncMock) as mock_authorize,
    ):
        await service._materialize_space_admin(space_id=101, user_id=2)

    assert member.user_role == UserRoleEnum.ADMIN
    assert member.department_admin_promoted_from_role == UserRoleEnum.MEMBER.value
    grant = mock_authorize.await_args.kwargs["grants"][0]
    assert (grant.subject_id, grant.relation) == (2, "manager")


# ---------------------------------------------------------------------------
# handle_admin_invalidated — AC-08 / AC-10
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_admin_invalidated_flips_to_pending_and_notifies_super_admins():
    service = _load_service_class()
    with (
        patch(
            f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceDao.aget_by_admin_user_id",
            new_callable=AsyncMock,
            return_value=[_binding(admin_user_id=2)],
        ),
        patch(
            f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceDao.areplace_admin",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_swap,
        patch(
            f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceService._dematerialize_space_admin",
            new_callable=AsyncMock,
        ) as mock_dematerialize,
        patch(
            f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceService._materialize_space_admin",
            new_callable=AsyncMock,
        ) as mock_materialize,
        patch(
            f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceService._super_admin_user_ids",
            new_callable=AsyncMock,
            return_value=[1, 9],
        ),
        patch(f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceService._notify", new_callable=AsyncMock) as mock_notify,
    ):
        flipped = await service.handle_admin_invalidated(2, operator_user_id=1)

    assert flipped == 1
    # AC-08: column → NULL (pending state).
    assert mock_swap.await_args.kwargs["new_admin_user_id"] is None
    mock_dematerialize.assert_awaited_once_with(space_id=101, user_id=2)
    # AC-10: nobody — super admin included — is auto-promoted.
    mock_materialize.assert_not_awaited()
    assert mock_notify.await_args.kwargs["receiver_user_ids"] == [1, 9]


@pytest.mark.asyncio
async def test_handle_admin_invalidated_skips_rows_reassigned_concurrently():
    service = _load_service_class()
    with (
        patch(
            f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceDao.aget_by_admin_user_id",
            new_callable=AsyncMock,
            return_value=[_binding(admin_user_id=2)],
        ),
        patch(
            f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceDao.areplace_admin",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceService._dematerialize_space_admin",
            new_callable=AsyncMock,
        ) as mock_dematerialize,
        patch(
            f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceService._super_admin_user_ids",
            new_callable=AsyncMock,
            return_value=[1],
        ),
        patch(f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceService._notify", new_callable=AsyncMock) as mock_notify,
    ):
        flipped = await service.handle_admin_invalidated(2)

    assert flipped == 0
    mock_dematerialize.assert_not_awaited()
    mock_notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_admin_invalidated_respects_except_tenant():
    service = _load_service_class()
    stay = _binding(row_id=6, space_id=102)
    stay.tenant_id = 7  # the tenant the user moved INTO — keeps its admin
    with (
        patch(
            f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceDao.aget_by_admin_user_id",
            new_callable=AsyncMock,
            return_value=[stay],
        ),
        patch(
            f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceDao.areplace_admin",
            new_callable=AsyncMock,
        ) as mock_swap,
    ):
        flipped = await service.handle_admin_invalidated(2, except_tenant_id=7)
    assert flipped == 0
    mock_swap.assert_not_awaited()


# ---------------------------------------------------------------------------
# pending-admin gate — AC-09 / AC-11
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pending_space_blocks_admin_gated_operations():
    service = _load_service_class()
    with patch(
        f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceDao.aget_by_space_id",
        new_callable=AsyncMock,
        return_value=_binding(admin_user_id=None),
    ):
        assert await service.is_space_pending_admin(101) is True
        with pytest.raises(SpacePendingAdminError):
            await service.ensure_space_not_pending_admin(101)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "binding",
    [None, "with_admin"],
    ids=["non-department-space", "admin-configured"],
)
async def test_non_pending_space_passes_gate(binding):
    service = _load_service_class()
    row = None if binding is None else _binding(admin_user_id=2)
    with patch(
        f"{_SERVICE_MODULE}.DepartmentKnowledgeSpaceDao.aget_by_space_id",
        new_callable=AsyncMock,
        return_value=row,
    ):
        assert await service.is_space_pending_admin(101) is False
        await service.ensure_space_not_pending_admin(101)  # must not raise
