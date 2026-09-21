from types import SimpleNamespace

import pytest

from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.common.errcode.public_endpoints import PublicGuestAccessDisabledError
from bisheng.public_endpoints.domain.context import (
    PublicApiPrincipal,
    reset_current_public_api_principal,
    set_current_public_api_principal,
)
from bisheng.public_endpoints.domain.services import guest_link, guest_policy
from bisheng.public_endpoints.domain.services.guest_link import (
    AppGuestLink,
    GuestLinkPatchRequest,
    guest_link_config_key,
    parse_app_guest_link,
)


def test_missing_row_means_enabled_and_follow_default() -> None:
    parsed = parse_app_guest_link(None, strict=False)
    assert parsed == AppGuestLink(enabled=True, user_id=None, updated_by=None)
    assert guest_link_config_key("workflow", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa") == (
        "guest_link:workflow:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    )
    assert guest_link_config_key("assistant", "b" * 32) != guest_link_config_key("workflow", "b" * 32)


def test_is_public_published_resource_binds_current_id_only() -> None:
    token = set_current_public_api_principal(
        PublicApiPrincipal(
            tenant_id=23,
            operator_user_id=41,
            operator_name="guest",
            resource_type="workflow",
            resource_id="flow-1",
        )
    )
    try:
        assert guest_policy.is_public_published_resource("flow-1", "workflow") is True
        assert guest_policy.is_public_published_resource("flow-2", "workflow") is False
        assert guest_policy.is_public_published_resource("flow-1", "assistant") is False
    finally:
        reset_current_public_api_principal(token)
    assert guest_policy.is_public_published_resource("flow-1", "workflow") is False


def test_celery_skip_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(guest_policy.MessageSessionDao, "get_one", lambda _chat_id: None)
    assert (
        guest_policy.should_skip_public_workflow_use(
            channel="public_v3",
            chat_id="chat-1",
            workflow_id="flow-1",
        )
        is False
    )

    monkeypatch.setattr(
        guest_policy.MessageSessionDao,
        "get_one",
        lambda _chat_id: SimpleNamespace(flow_id="other-flow"),
    )
    assert (
        guest_policy.should_skip_public_workflow_use(
            channel="public_v3",
            chat_id="chat-1",
            workflow_id="flow-1",
        )
        is False
    )

    monkeypatch.setattr(
        guest_policy.MessageSessionDao,
        "get_one",
        lambda _chat_id: SimpleNamespace(flow_id="flow-1"),
    )
    assert (
        guest_policy.should_skip_public_workflow_use(
            channel="public_v3",
            chat_id="chat-1",
            workflow_id="flow-1",
        )
        is True
    )
    assert (
        guest_policy.should_skip_public_workflow_use(
            channel="open_api",
            chat_id="chat-1",
            workflow_id="flow-1",
        )
        is False
    )


@pytest.fixture
def operator_lookups(monkeypatch):
    state = SimpleNamespace(
        enable_guest_access=True,
        default_user=41,
        users={
            41: SimpleNamespace(user_id=41, user_name="guest", delete=0),
            7: SimpleNamespace(user_id=7, user_name="alice", delete=0),
            1: SimpleNamespace(user_id=1, user_name="admin", delete=0),
        },
        memberships={
            (41, 23): SimpleNamespace(status="active"),
            (7, 23): SimpleNamespace(status="active"),
        },
        tenant=SimpleNamespace(status="active"),
        app_row=None,
        privileged=set(),
        share=True,
        visible=True,
        saved=None,
    )

    async def config(_key):
        return {"user": state.default_user, "enable_guest_access": state.enable_guest_access}

    async def aget_user(user_id):
        return state.users.get(user_id)

    async def aget_user_by_ids(user_ids):
        return [state.users[i] for i in user_ids if i in state.users]

    async def aget_user_tenant(user_id, tenant_id):
        return state.memberships.get((user_id, tenant_id))

    async def aget_by_id(_tenant_id):
        return state.tenant

    async def load_resource(_resource_type, _resource_id):
        return SimpleNamespace(tenant_id=23), 23, "Demo", "flow-1"

    async def load_row(_resource_type, _resource_id, *, strict=False):
        del strict
        return state.app_row or AppGuestLink()

    async def save_row(_resource_type, _resource_id, link, *, updated_by):
        state.saved = (link, updated_by)
        state.app_row = link

    async def check_action(_user, *, resource_type, resource_id, action):
        del resource_type, resource_id
        if action == "share":
            return state.share
        if action == "visible":
            return state.visible
        return False

    async def forbidden(user_id, _tenant_id):
        return user_id in state.privileged

    async def candidates(_tenant_id, *, pinned_ids):
        del pinned_ids
        return [{"user_id": 7, "user_name": "alice"}]

    async def system_default():
        return state.enable_guest_access, state.default_user

    monkeypatch.setattr(guest_policy, "settings", SimpleNamespace(aget_from_db=config))
    monkeypatch.setattr(guest_policy.UserDao, "aget_user", aget_user)
    monkeypatch.setattr(guest_policy.UserTenantDao, "aget_user_tenant", aget_user_tenant)
    monkeypatch.setattr(guest_policy.TenantDao, "aget_by_id", aget_by_id)
    monkeypatch.setattr(guest_link, "load_app_guest_link", load_row)
    monkeypatch.setattr(guest_link, "save_app_guest_link", save_row)
    monkeypatch.setattr(guest_link, "_load_resource", load_resource)
    monkeypatch.setattr(guest_link, "check_business_action", check_action)
    monkeypatch.setattr(guest_link, "_is_forbidden_operator", forbidden)
    monkeypatch.setattr(guest_link, "_candidate_users", candidates)
    monkeypatch.setattr(guest_link.UserDao, "aget_user", aget_user)
    monkeypatch.setattr(guest_link.UserDao, "aget_user_by_ids", aget_user_by_ids)
    monkeypatch.setattr(guest_link.UserTenantDao, "aget_user_tenant", aget_user_tenant)
    monkeypatch.setattr(guest_link.TenantDao, "aget_by_id", aget_by_id)
    monkeypatch.setattr(guest_link, "_system_default_operator", system_default)
    return state


async def _async_value(value):
    return value


async def test_app_switch_off_is_26103(operator_lookups, monkeypatch) -> None:
    operator_lookups.app_row = AppGuestLink(enabled=False, user_id=None)
    monkeypatch.setattr(guest_policy, "load_app_guest_link", lambda *a, **k: _async_value(operator_lookups.app_row))
    with pytest.raises(PublicGuestAccessDisabledError) as caught:
        await guest_policy._load_default_operator(23, "workflow", "flow-1")
    assert caught.value.code == 26103


async def test_specified_user_overrides_default(operator_lookups, monkeypatch) -> None:
    operator_lookups.app_row = AppGuestLink(enabled=True, user_id=7)

    async def load_row(*_args, **_kwargs):
        return operator_lookups.app_row

    monkeypatch.setattr(guest_policy, "load_app_guest_link", load_row)
    monkeypatch.setattr(
        "bisheng.user.domain.services.auth.UserRoleDao.aget_user_roles",
        lambda _user_id: _async_value([]),
    )
    monkeypatch.setattr(
        "bisheng.utils.http_middleware._check_is_global_super",
        lambda *_args, **_kwargs: _async_value(False),
    )
    monkeypatch.setattr(
        "bisheng.permission.application.relation_api.is_tenant_admin",
        lambda *_args, **_kwargs: _async_value(False),
    )
    operator = await guest_policy._load_default_operator(23, "workflow", "flow-1")
    assert operator.user_id == 7


async def test_follow_default_outside_tenant_is_26103(operator_lookups, monkeypatch) -> None:
    operator_lookups.memberships.pop((41, 23), None)
    monkeypatch.setattr(guest_policy, "load_app_guest_link", lambda *a, **k: _async_value(AppGuestLink()))
    monkeypatch.setattr(
        "bisheng.user.domain.services.auth.UserRoleDao.aget_user_roles",
        lambda _user_id: _async_value([]),
    )
    with pytest.raises(PublicGuestAccessDisabledError) as caught:
        await guest_policy._load_default_operator(23, "workflow", "flow-1")
    assert caught.value.code == 26103


async def test_patch_rejects_missing_share(operator_lookups) -> None:
    operator_lookups.share = False
    login = SimpleNamespace(user_id=9, user_name="editor")
    with pytest.raises(UnAuthorizedError):
        await guest_link.patch_guest_link_settings(
            login,
            "workflow",
            "flow-1",
            GuestLinkPatchRequest(enabled=False),
        )


async def test_patch_rejects_new_admin(operator_lookups) -> None:
    operator_lookups.privileged.add(1)
    login = SimpleNamespace(user_id=9, user_name="editor")
    with pytest.raises(UnAuthorizedError):
        await guest_link.patch_guest_link_settings(
            login,
            "workflow",
            "flow-1",
            GuestLinkPatchRequest(enabled=True, user_id=1),
        )


async def test_patch_follow_default_does_not_validate_admin(operator_lookups) -> None:
    operator_lookups.privileged.add(41)
    operator_lookups.app_row = AppGuestLink(enabled=True, user_id=7)
    login = SimpleNamespace(user_id=9, user_name="editor")
    data = await guest_link.patch_guest_link_settings(
        login,
        "workflow",
        "flow-1",
        GuestLinkPatchRequest.model_validate({"enabled": True, "user_id": None}),
    )
    assert operator_lookups.saved[0].user_id is None
    assert data["follow_system_default"] is True


async def test_patch_keeps_existing_admin_operator(operator_lookups) -> None:
    operator_lookups.privileged.add(7)
    operator_lookups.app_row = AppGuestLink(enabled=True, user_id=7)
    login = SimpleNamespace(user_id=9, user_name="editor")
    await guest_link.patch_guest_link_settings(
        login,
        "workflow",
        "flow-1",
        GuestLinkPatchRequest(enabled=True, user_id=7),
    )
    assert operator_lookups.saved[0].user_id == 7
