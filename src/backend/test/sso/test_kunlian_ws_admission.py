"""T045 覆盖 AC-08, AC-12, AC-13, AC-14, AC-17, AC-25。"""

import asyncio
from contextlib import asynccontextmanager
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.common.chat.client import ChatMessageExecution
from bisheng.common.chat.clients.workflow_client import WorkflowClient
from bisheng.common.chat.manager import ChatManager
from bisheng.common.chat.types import WorkType
from bisheng.common.errcode.sso_sync import KunlianSessionExpiredError
from test.sso import test_kunlian_http_admission as http_tests

owner = http_tests.owner
directory_store = http_tests.directory_store
projection = http_tests.projection
login = http_tests.login
browser_api = http_tests.browser_api


async def test_workflow_messages_use_current_operator_and_reject_before_dispatch(monkeypatch):
    from bisheng.common.chat.clients import base as base_module

    queued = []
    monkeypatch.setattr(base_module.thread_pool, "submit", lambda *args, **kwargs: queued.append((args, kwargs)))
    client = WorkflowClient.__new__(WorkflowClient)
    client.user_id, client.login_user = 1, SimpleNamespace(user_id=1)
    client.client_key, client.kwargs = "fixture", {}
    client.task_ids = []
    client.execution_snapshot, client.session_subject = None, None
    seen = []

    async def handle(self, message):
        before = self.user_id
        await asyncio.sleep(0)
        seen.append((message["action"], before, self.user_id, self.login_user.user_id))

    client._handle_message = MethodType(handle, client)
    manager = ChatManager()
    manager._has_use_action = AsyncMock(return_value=True)
    subjects = [SimpleNamespace(user_id=2), SimpleNamespace(user_id=3)]

    @asynccontextmanager
    async def admission():
        yield ChatMessageExecution(operator=subjects.pop(0), execution_snapshot={}, session_subject=None)

    for action in ("init_data", "input"):
        assert await manager._dispatch_message(
            client,
            {"action": action},
            login_user=client.login_user,
            work_type=WorkType.WORKFLOW,
            client_id="workflow",
            message_admission=admission,
        )
    await asyncio.gather(*(args[1](*args[2:]) for args, _ in queued))
    assert sorted(seen) == [("init_data", 2, 2, 2), ("input", 3, 3, 3)]
    assert client.user_id == client.login_user.user_id == 1
    assert [call.args[0].user_id for call in manager._has_use_action.await_args_list] == [2, 3]

    @asynccontextmanager
    async def denied():
        raise KunlianSessionExpiredError()
        yield

    manager._has_use_action.reset_mock()
    with pytest.raises(KunlianSessionExpiredError):
        await manager._dispatch_message(
            client,
            {"action": "stop"},
            login_user=client.login_user,
            work_type=WorkType.WORKFLOW,
            client_id="workflow",
            message_admission=denied,
        )
    assert len(queued) == 2
    manager._has_use_action.assert_not_awaited()

    @asynccontextmanager
    async def current_stop():
        yield ChatMessageExecution(operator=SimpleNamespace(user_id=4), execution_snapshot=None)

    assert await manager._dispatch_message(
        client,
        {"action": "stop"},
        login_user=client.login_user,
        work_type=WorkType.WORKFLOW,
        client_id="workflow",
        message_admission=current_stop,
    )
    assert seen[-1] == ("stop", 4, 4, 4)
    assert client.user_id == client.login_user.user_id == 1


@pytest.mark.parametrize("case", ["origin", "query_only", "query_and_cookie", "bearer", "temporary"])
async def test_socket_credentials_and_origin_refuse_before_legacy_user_path(browser_api, monkeypatch, case):
    from fastapi import WebSocket, WebSocketException

    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.common.errcode.sso_sync import KunlianDependencyUnavailableError

    client, _, cookie, _, idp, _, _ = browser_api
    app = client._transport.app
    headers = [(b"cookie", f"{http_tests.COOKIE}={cookie}".encode()), (b"origin", b"https://fixture.example")]
    query = b""
    if case == "origin":
        headers[-1] = (b"origin", b"https://untrusted.example")
    elif case in {"query_only", "query_and_cookie"}:
        query = ("t=" + cookie).encode()
        if case == "query_only":
            headers = headers[1:]
    elif case == "bearer":
        headers.append((b"authorization", ("Bearer " + cookie).encode()))
    else:
        idp.introspect.side_effect = KunlianDependencyUnavailableError()
    monkeypatch.setattr(UserPayload, "init_login_user", AsyncMock(side_effect=AssertionError("legacy login path")))
    websocket = WebSocket(
        {
            "type": "websocket",
            "app": app,
            "path": "/api/v1/workflow/chat/fixture",
            "query_string": query,
            "headers": headers,
        },
        receive=AsyncMock(),
        send=AsyncMock(),
    )
    with pytest.raises(WebSocketException) as error:
        await UserPayload.get_login_user_from_ws(websocket, http_tests.auth())
    assert error.value.code == (1013 if case == "temporary" else 1008)
    if case != "temporary":
        idp.introspect.assert_not_awaited()


async def test_admission_disconnect_keeps_existing_debug_workflow_running():
    client = WorkflowClient.__new__(WorkflowClient)
    client.login_user = SimpleNamespace(auth_source="kunlian")
    client.chat_id, client.ws_closed = "", False
    workflow = SimpleNamespace(async_set_workflow_stop=AsyncMock())
    client.workflow = workflow
    await client.close()
    assert client.ws_closed and client.workflow is workflow
    workflow.async_set_workflow_stop.assert_not_awaited()


async def test_no_callback_cannot_reuse_kunlian_handshake_identity():
    from bisheng.common.errcode.sso_sync import KunlianTrustRejectedError

    manager = ChatManager()
    manager._has_use_action = AsyncMock()
    with pytest.raises(KunlianTrustRejectedError):
        await manager._dispatch_message(
            SimpleNamespace(handle_message=AsyncMock()),
            {"action": "input"},
            login_user=SimpleNamespace(auth_source="kunlian"),
            work_type=WorkType.WORKFLOW,
            client_id="fixture",
        )
    manager._has_use_action.assert_not_awaited()


async def test_long_socket_idle_does_not_authorize_and_denial_keeps_started_work(monkeypatch):
    from bisheng.common.chat import manager as module
    from bisheng.common.chat.clients import base

    websocket = SimpleNamespace(
        accept=AsyncMock(),
        close=AsyncMock(),
        send_json=AsyncMock(),
        receive_json=AsyncMock(
            side_effect=[
                TimeoutError(),
                TimeoutError(),
                {"action": "init_data"},
                {"action": "input"},
                {"action": "stop"},
            ]
        ),
    )
    operator = SimpleNamespace(user_id=1, tenant_id=7, auth_source="kunlian")
    client = WorkflowClient.__new__(WorkflowClient)
    client.client_key, client.chat_id, client.task_ids, client.ws_closed = "fixture", "", [], False
    client.login_user, client.user_id, client.websocket = operator, 1, websocket
    started = SimpleNamespace(async_set_workflow_stop=AsyncMock())
    client.workflow = started
    queued = []
    monkeypatch.setattr(base.thread_pool, "submit", lambda *args, **kwargs: queued.append(args))
    runtime = object()

    def create_client(*args, **kwargs):
        assert kwargs["platform_agent_runtime"] is runtime
        return client

    monkeypatch.setattr(module, "WorkflowClient", create_client)
    monkeypatch.setattr(
        module.WorkFlowService, "get_one_workflow_simple_info", AsyncMock(return_value=SimpleNamespace(name="fixture"))
    )
    monkeypatch.setattr(module.telemetry_service, "log_event", AsyncMock())
    manager = ChatManager()
    manager._has_use_action = AsyncMock(return_value=True)
    attempts = []

    @asynccontextmanager
    async def admission():
        attempts.append(1)
        if len(attempts) == 3:
            raise KunlianSessionExpiredError()
        yield ChatMessageExecution(operator=operator, execution_snapshot=None)

    await manager.dispatch_client(
        websocket,
        "fixture-flow",
        "",
        operator,
        WorkType.WORKFLOW,
        websocket,
        message_admission=admission,
        platform_agent_runtime=runtime,
    )
    assert len(attempts) == 3 and len(queued) == 2 and manager._has_use_action.await_count == 2
    started.async_set_workflow_stop.assert_not_awaited()
    assert client.workflow is started and client.ws_closed
    assert websocket.send_json.call_args.args[0]["message"]["data"]["reason_code"] == "SESSION_EXPIRED"


async def test_real_workflow_send_continue_and_stop_preserve_current_identity_and_state(monkeypatch):
    from bisheng.common.chat.clients import base
    from bisheng.common.chat.clients import workflow_client as module
    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.workflow.common.workflow import WorkflowStatus

    queued = []
    monkeypatch.setattr(base.thread_pool, "submit", lambda *args, **kwargs: queued.append(args))
    callback = SimpleNamespace(
        unique_id="fixture-job",
        workflow_id="fixture-flow",
        chat_id="fixture-chat",
        user_id=2,
        async_set_workflow_data=AsyncMock(),
        async_set_workflow_status=AsyncMock(),
        async_get_workflow_status=AsyncMock(return_value={"status": WorkflowStatus.INPUT.value}),
        async_set_user_input=AsyncMock(),
        async_set_workflow_stop=AsyncMock(),
    )
    create_callback = Mock(return_value=callback)
    # F119 正式入口从服务端读取发布图。身份测试保留普通空图。
    monkeypatch.setattr(module.FlowDao, "get_flow_by_id", lambda _: SimpleNamespace(data={}))
    execute, resume = Mock(), Mock()
    monkeypatch.setattr(module, "RedisCallback", create_callback)
    monkeypatch.setattr(module, "execute_workflow", SimpleNamespace(apply_async=execute))
    monkeypatch.setattr(module, "continue_workflow", SimpleNamespace(apply_async=resume))
    client = WorkflowClient.__new__(WorkflowClient)
    client.client_key, client.client_id, client.chat_id = "fixture-client", "fixture-flow", "fixture-chat"
    client.user_id, client.login_user = 1, SimpleNamespace(user_id=1, auth_source="kunlian")
    client.task_ids, client.workflow, client.ws_closed = [], None, False
    client.session_subject, client.execution_snapshot = None, None
    client.check_status = AsyncMock(return_value=(True, "fixture-job"))
    client.workflow_run, client.send_response = AsyncMock(return_value=True), AsyncMock()
    client.get_execute_worker, client.ensure_workflow_available = (
        AsyncMock(return_value="fixture-queue"),
        AsyncMock(return_value=True),
    )

    def execution(uid):
        return ChatMessageExecution(
            operator=SimpleNamespace(user_id=uid, tenant_id=7, auth_source="kunlian"),
            execution_snapshot=None,
            causal_context={
                "kind": "kunlian_causal",
                "user_id": uid,
                "tenant_id": 7,
                "binding_id": "a" * 64,
                "session_hash": "b" * 64,
                "request_id": "fixture-message",
            },
        )

    with tenant_execution_scope(7):
        await client.handle_message({"action": "init_data", "data": {}}, execution_context=execution(2))
        args = queued.pop()
        await args[1](*args[2:])
    # 单独消费捕获任务。模拟真实异步队列边界。
    if not execute.called:
        raise AssertionError("workflow send was not dispatched")
    assert execute.call_args.args[0][3:6] == [2, "platform", None]
    assert execute.call_args.kwargs["headers"]["kunlian_causal_context"]["user_id"] == 2
    assert client.workflow is callback and client.user_id == 1
    with tenant_execution_scope(7):
        await client.handle_message(
            {"action": "input", "data": {"node": {"data": "next"}}}, execution_context=execution(3)
        )
        args = queued.pop()
        await args[1](*args[2:])
        await client.handle_message({"action": "stop"}, execution_context=execution(4))
    assert resume.call_args.args[0][3:6] == [3, "platform", None]
    assert resume.call_args.kwargs["headers"]["tenant_id"] == 7
    callback.async_set_workflow_stop.assert_awaited_once()
    assert client.user_id == 1 and client.workflow is callback


def test_registered_workflow_tasks_consume_causal_headers_without_minting_identity():
    import subprocess
    import sys
    import textwrap

    script = textwrap.dedent("""
        import importlib
        import importlib.util
        import sys
        from pathlib import Path
        from types import ModuleType
        from celery import Celery
        for name in ('celery.schedules', 'celery.app', 'celery.app.task', 'celery.signals'):
            importlib.import_module(name)
        app = Celery('f118-workflow-fixture', broker='memory://', backend='cache+memory://')
        from test.fixtures.mock_services import premock_import_chain
        premock_import_chain()
        main = ModuleType('bisheng.worker.main')
        main.bisheng_celery = app
        sys.modules['bisheng.worker.main'] = main
        for name, directory in (('bisheng.worker', 'bisheng/worker'), ('bisheng.worker.workflow', 'bisheng/worker/workflow')):
            package = ModuleType(name)
            package.__path__ = [str(Path(directory).resolve())]
            sys.modules[name] = package
        importlib.import_module('bisheng.worker.tenant_context')
        name = 'bisheng.worker.workflow.tasks'
        spec = importlib.util.spec_from_file_location(name, 'bisheng/worker/workflow/tasks.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        from bisheng.common.errcode.sso_sync import KunlianTrustRejectedError
        from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope
        from bisheng.core.logger import trace_id_var
        from bisheng.permission.application.identity import get_current_permission_actor
        seen = []
        def execute(unique_id, workflow_id, chat_id, user_id, source):
            seen.append((user_id, get_current_tenant_id(), trace_id_var.get(), get_current_permission_actor()))
        module._execute_workflow = module._continue_workflow = execute
        module._log_workflow_telemetry = lambda *args: None
        causal = {'kind': 'kunlian_causal', 'user_id': 2, 'tenant_id': 7, 'binding_id': 'a'*64, 'session_hash': 'b'*64, 'request_id': 'fixture-message'}
        with tenant_execution_scope(9):
            for task_name in ('execute_workflow', 'continue_workflow'):
                task = app.tasks[name + '.' + task_name]
                task.apply(args=['fixture-job', 'fixture-flow', 'fixture-chat', 2], headers={'tenant_id': 7, 'kunlian_causal_context': causal}, throw=True).get()
                assert get_current_tenant_id() == 9
                for bad in ({**causal, 'user_id': 99}, {**causal, 'tenant_id': 8}, {**causal, 'reference': 'forged-browser-reference'}):
                    try:
                        task.apply(args=['fixture-job', 'fixture-flow', 'fixture-chat', 2], headers={'tenant_id': 7, 'kunlian_causal_context': bad}, throw=True).get()
                    except KunlianTrustRejectedError:
                        pass
                    else:
                        raise AssertionError('unverified causal metadata reached workflow execution')
        assert seen == [(2, 7, 'fixture-job', None), (2, 7, 'fixture-job', None)], seen
        app.close()
        print('PASS real Celery workflow causal boundary')
    """)
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS real Celery workflow causal boundary" in result.stdout


@pytest.mark.parametrize("entry", ["workflow", "assistant"])
async def test_actual_websocket_router_admits_handshake_and_each_message(browser_api, monkeypatch, entry):
    from importlib import import_module

    from fastapi import APIRouter
    from starlette.requests import HTTPConnection

    from bisheng.user.domain.services.auth import AuthJwt

    client, _, cookie, _, idp, _, _ = browser_api
    app = client._transport.app
    module = import_module("bisheng.api.v1." + entry)
    api = APIRouter(prefix="/api/v1")
    api.include_router(module.router)
    app.include_router(api)

    def socket_auth(connection: HTTPConnection):
        return http_tests.auth(connection if connection.scope["type"] == "http" else None)

    app.dependency_overrides[AuthJwt] = socket_auth
    monkeypatch.setattr(module, "require_business_action", AsyncMock())
    seen = []

    async def dispatch(*args, **kwargs):
        if entry == "workflow":
            from bisheng.workflow.application.platform_agent import BrowserPlatformAgentRuntime

            assert isinstance(kwargs["platform_agent_runtime"], BrowserPlatformAgentRuntime)
        websocket = args[0]
        await websocket.accept()
        for _ in range(2):
            async with kwargs["message_admission"]() as execution:
                assert execution.operator.user_id == args[3].user_id
                assert execution.execution_snapshot is None
                assert set(execution.causal_context) == {
                    "kind",
                    "user_id",
                    "tenant_id",
                    "binding_id",
                    "session_hash",
                    "request_id",
                }
                assert "reference" not in execution.causal_context
                seen.append(execution)
        await websocket.close()

    monkeypatch.setattr(module.chat_manager, "dispatch_client", dispatch)
    headers = [(b"cookie", f"{http_tests.COOKIE}={cookie}".encode()), (b"origin", b"https://fixture.example")]
    frames = []
    connected = False

    async def receive():
        nonlocal connected
        if not connected:
            connected = True
            return {"type": "websocket.connect"}
        return {"type": "websocket.disconnect", "code": 1000}

    async def send(frame):
        frames.append(frame)

    path = "/api/v1/" + entry + "/chat/fixture-app"
    await app(
        {
            "type": "websocket",
            "asgi": {"version": "3.0"},
            "scheme": "wss",
            "path": path,
            "raw_path": path.encode(),
            "root_path": "",
            "query_string": b"",
            "headers": headers,
            "client": ("192.0.2.10", 4000),
            "server": ("fixture.example", 443),
            "subprotocols": [],
        },
        receive,
        send,
    )
    assert frames[0]["type"] == "websocket.accept" and len(seen) == 2
    assert idp.introspect.await_count == 3
