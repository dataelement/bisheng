"""Chat canonical visibility keeps original scope, identity and messages. AC-35/79/82/83/91."""

from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from bisheng.api.v1 import chat as endpoint
from bisheng.common.chat.client import ChatMessageExecution
from bisheng.common.chat.manager import ChatManager
from bisheng.common.chat.types import WorkType
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.flow import AppInvalidCursorError
from bisheng.common.errcode.open_api import PersonalTokenDataScopeError, ServiceAccountOwnerTenantMismatchError
from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.common.schemas.api import PageInfiniteCursorData
from bisheng.database.models.flow import FlowStatus, FlowType
from bisheng.permission.application import business_authorization as business
from bisheng.permission.application.identity import (
    reset_current_permission_actor,
    set_current_permission_actor,
)
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from test.knowledge_unification.test_perm_runtime import decision


@pytest.fixture
def chat_http(monkeypatch):
    user = UserPayload(user_id=7, tenant_id=101, user_role=[])
    page = PageInfiniteCursorData(
        data=[{"id": "visible-app", "actions": ["visible"], "can_share": False}],
        page_size=7,
        has_more=True,
        next_cursor="opaque/+==",
    )
    ranked, updated = AsyncMock(return_value=page), AsyncMock(return_value=page)
    share = AsyncMock()
    monkeypatch.setattr(endpoint.WorkFlowService, "get_online_flows_cursor", ranked)
    monkeypatch.setattr(endpoint.WorkFlowService, "get_all_flows_envelope", updated)
    monkeypatch.setattr(endpoint.WorkFlowService, "aenrich_apps_can_share", share)
    app = FastAPI()
    app.include_router(endpoint.router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: user
    return SimpleNamespace(app=app, user=user, page=page, ranked=ranked, updated=updated, share=share)


@pytest.mark.parametrize("action", [None, "use", "visible"])
@pytest.mark.parametrize("sort_by", [None, "update_time"])
async def test_actual_http_default_and_legacy_action_are_canonical_with_original_filters(chat_http, action, sort_by):
    params = {
        "keyword": "policy%_/",
        "tag_id": 19,
        "flow_type": FlowType.WORKFLOW.value,
        "limit": 7,
        "cursor": "unchanged/+==",
        "search_description": "true",
    }
    if action is not None:
        params["action"] = action
    if sort_by is not None:
        params["sort_by"] = sort_by
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=chat_http.app), base_url="http://asgi", trust_env=False
    ) as client:
        response = await client.get("/api/v1/chat/online", params=params)
    assert response.status_code == 200
    assert response.json() == {"status_code": 200, "status_message": "SUCCESS", "data": chat_http.page.model_dump()}
    selected = chat_http.updated if sort_by else chat_http.ranked
    selected.assert_awaited_once_with(
        chat_http.user,
        "policy%_/",
        FlowStatus.ONLINE.value,
        19,
        FlowType.WORKFLOW.value,
        cursor="unchanged/+==",
        page_size=7,
        search_description=True,
        action="visible",
    )
    assert selected.await_args.args[0] is chat_http.user
    (chat_http.ranked if sort_by else chat_http.updated).assert_not_awaited()
    if sort_by:
        chat_http.share.assert_awaited_once_with(chat_http.user, chat_http.page.data)
    else:
        chat_http.share.assert_not_awaited()


async def test_openapi_advertises_visible_without_removing_the_legacy_query_alias(chat_http):
    operation = chat_http.app.openapi()["paths"]["/api/v1/chat/online"]["get"]
    action = next(parameter for parameter in operation["parameters"] if parameter["name"] == "action")
    assert action["schema"]["default"] == "visible"
    assert action["schema"]["pattern"] == "^(visible|use)$"


@pytest.mark.parametrize("action", ["use_kb", "edit", "publish", "delete", "unknown"])
async def test_other_http_actions_stay_invalid_before_list_or_share(chat_http, action):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=chat_http.app), base_url="http://asgi", trust_env=False
    ) as client:
        response = await client.get("/api/v1/chat/online", params={"action": action})
    assert response.status_code == 422
    chat_http.ranked.assert_not_awaited()
    chat_http.updated.assert_not_awaited()
    chat_http.share.assert_not_awaited()


@pytest.mark.parametrize("sort_by", [None, "update_time"])
@pytest.mark.parametrize("error_type", [AppInvalidCursorError, PersonalTokenDataScopeError])
async def test_original_cursor_and_scope_failures_are_not_swallowed(chat_http, sort_by, error_type):
    error = error_type()
    (chat_http.updated if sort_by else chat_http.ranked).side_effect = error
    params = {"action": "use", "cursor": "old-use-context"}
    if sort_by:
        params["sort_by"] = sort_by
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=chat_http.app), base_url="http://asgi", trust_env=False
    ) as client:
        with pytest.raises(error_type) as raised:
            await client.get("/api/v1/chat/online", params=params)
    assert raised.value is error
    chat_http.share.assert_not_awaited()


@pytest.fixture
def admission(monkeypatch):
    runtime, fga = decision()
    runtime._catalog.effective_actions.return_value = ("visible",)
    runtime._catalog.is_action_effective.side_effect = lambda resource_type, action: action == "visible"
    actor = PermissionActor(subject_type="user", subject_id=42, tenant_id=101)
    user = UserPayload(user_id=42, tenant_id=101, user_role=[])
    targets = {}

    async def resolve(*, resource_type, resource_id, actor, action):
        assert action == "visible"
        key = (resource_type, resource_id)
        targets.setdefault(
            key,
            VerifiedPermissionTarget.from_business_service(
                tenant_id=101,
                resource_type=resource_type,
                resource_id=resource_id,
                resource_version=1,
                context_version="original-current",
            ),
        )
        return targets[key]

    registry = SimpleNamespace(resolve=AsyncMock(side_effect=resolve))
    monkeypatch.setattr(business, "get_f048_resource_registry", AsyncMock(return_value=registry))
    monkeypatch.setattr(business, "get_f048_runtime", AsyncMock(return_value=runtime))
    resolver = AsyncMock(wraps=business.resolve_permission_actor)
    monkeypatch.setattr(business, "resolve_permission_actor", resolver)
    token = set_current_permission_actor(actor)
    try:
        yield SimpleNamespace(
            runtime=runtime,
            fga=fga,
            user=user,
            actor=actor,
            registry=registry,
            resolver=resolver,
            manager=object.__new__(ChatManager),
            client=SimpleNamespace(handle_message=AsyncMock()),
        )
    finally:
        reset_current_permission_actor(token)


@pytest.mark.parametrize("work_type", [WorkType.GPTS, WorkType.WORKFLOW])
@pytest.mark.parametrize("visible", [True, False])
async def test_real_f048_visible_only_catalog_controls_dispatch_without_changing_payload(admission, work_type, visible):
    value = admission
    value.fga.check.return_value = visible
    payload = {"action": "chat", "messages": [{"role": "user", "content": "old text"}], "version_id": "historical"}
    original = deepcopy(payload)
    assert (
        await value.manager._dispatch_message(
            value.client, payload, login_user=value.user, work_type=work_type, client_id="trusted-root"
        )
        is visible
    )
    assert value.resolver.await_args.args[0] is value.user
    value.registry.resolve.assert_awaited_once_with(
        resource_type=work_type.value, resource_id="trusted-root", actor=value.actor, action="visible"
    )
    assert value.fga.check.await_args.kwargs["relation"] == "visible"
    assert value.fga.check.await_args.kwargs["user"] == "user:42"
    if visible:
        value.client.handle_message.assert_awaited_once_with(payload)
        assert value.client.handle_message.await_args.args[0] is payload
    else:
        value.client.handle_message.assert_not_awaited()
    assert payload == original


@pytest.mark.parametrize("work_type", [WorkType.GPTS, WorkType.WORKFLOW])
@pytest.mark.parametrize("denial", ["tenant", "data_scope"])
async def test_actual_f048_tenant_and_data_scope_denials_precede_message_dispatch(
    admission, monkeypatch, work_type, denial
):
    monkeypatch.setattr(
        "bisheng.permission.domain.services.permission_action_service.get_data_scope_resolver", lambda: None
    )
    actor = PermissionActor(
        subject_type="user",
        subject_id=42,
        tenant_id=202 if denial == "tenant" else 101,
        data_scope="OWNED" if denial == "data_scope" else "ALL",
    )
    token = set_current_permission_actor(actor)
    try:
        call = admission.manager._dispatch_message(
            admission.client, {}, login_user=admission.user, work_type=work_type, client_id="trusted-root"
        )
        if denial == "data_scope":
            with pytest.raises(PersonalTokenDataScopeError):
                await call
        else:
            assert not await call
    finally:
        reset_current_permission_actor(token)
    admission.fga.check.assert_not_awaited()
    admission.client.handle_message.assert_not_awaited()


@pytest.mark.parametrize("work_type", [WorkType.GPTS, WorkType.WORKFLOW])
async def test_missing_business_source_is_not_a_legacy_history_fallback(admission, work_type):
    error = PermissionInvalidResourceError()
    admission.registry.resolve.side_effect = error
    with pytest.raises(PermissionInvalidResourceError) as raised:
        await admission.manager._dispatch_message(
            admission.client,
            {"history": [{"content": "saved"}]},
            login_user=admission.user,
            work_type=work_type,
            client_id="deleted-root",
        )
    assert raised.value is error
    admission.fga.check.assert_not_awaited()
    admission.client.handle_message.assert_not_awaited()


@pytest.mark.parametrize("denied", [False, True])
async def test_fresh_admission_runs_first_and_uses_its_exact_original_operator(admission, denied):
    old = UserPayload(user_id=7, tenant_id=101, user_role=[])
    snapshot = {"tenant_id": 101, "resource_owner_user_id": 42, "source": "frozen"}
    execution = ChatMessageExecution(operator=admission.user, execution_snapshot=snapshot)
    payload = {"message": "next", "history": [{"content": "past"}]}

    @asynccontextmanager
    async def current_message():
        if denied:
            raise ServiceAccountOwnerTenantMismatchError()
        yield execution

    call = admission.manager._dispatch_message(
        admission.client,
        payload,
        login_user=old,
        work_type=WorkType.GPTS,
        client_id="trusted-root",
        message_admission=current_message,
    )
    if denied:
        with pytest.raises(ServiceAccountOwnerTenantMismatchError):
            await call
        admission.resolver.assert_not_awaited()
        admission.registry.resolve.assert_not_awaited()
        admission.fga.check.assert_not_awaited()
        admission.client.handle_message.assert_not_awaited()
    else:
        assert await call
        assert admission.resolver.await_args.args[0] is execution.operator is admission.user
        admission.client.handle_message.assert_awaited_once_with(payload, execution_context=execution)
        assert admission.client.handle_message.await_args.args[0] is payload
    assert snapshot == {"tenant_id": 101, "resource_owner_user_id": 42, "source": "frozen"}
    assert old.user_id == 7
