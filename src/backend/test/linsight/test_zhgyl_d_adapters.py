# ruff: noqa: RUF001
"""D release adapters exercised with synthetic bytes, no business data or services."""

import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool
from pydantic import Field

from bisheng.linsight.domain.services import customs_tools as customs
from bisheng.linsight.domain.services import procurement_api_files as procurement
from bisheng.linsight.domain.services import transport_tools as transport


class SyntheticTool(BaseTool):
    name: str = procurement.CODE_TOOL_NAME
    description: str = "Synthetic authorized executor"
    response: object = None
    calls: list = Field(default_factory=list)

    def _run(self, **kwargs):
        raise NotImplementedError

    async def _arun(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def api_response():
    return {
        "success": True,
        "data": {
            "status": 200,
            "data": {
                "result": [{"synthetic": "row"}],
                "query": {"model": "DEMO-Q1", "match_mode": "exact"},
                "pageNum": 1,
                "pageSize": 10,
                "totalElements": 1,
                "totalPages": 1,
                "matchedModelCount": 1,
                "hasNext": False,
                "mock": True,
                "snapshotId": "synthetic-snapshot",
            },
        },
    }


async def test_procurement_persists_exact_json_and_returns_only_small_receipt():
    raw = json.dumps(api_response(), ensure_ascii=False, indent=2)

    async def upload(files):
        assert len(files) == 1
        name, data = files[0]
        assert name.startswith("/uploads/procurement-api/")
        assert data == raw.encode()
        return [SimpleNamespace(path=name, error=None)]

    backend = SimpleNamespace(aupload_files=upload)
    receipt = await procurement.persist_response(raw, backend)
    assert receipt["status"] == "api_json_saved"
    assert receipt["sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    assert receipt["bytes"] == len(raw.encode())
    assert "result" not in receipt and "row" not in json.dumps(receipt)


@pytest.mark.parametrize("error", ["write failed", None])
async def test_procurement_never_treats_cache_or_wrong_path_as_persistence(error):
    backend = SimpleNamespace(aupload_files=AsyncMock(return_value=[SimpleNamespace(path="wrong", error=error)]))
    receipt = await procurement.persist_response(api_response(), backend)
    assert receipt["status"] == "file_error"
    assert "raw_json_file" not in receipt


@pytest.mark.parametrize(
    "response,status",
    [
        ({"success": False}, "api_error"),
        ('{"success": true, "data": NaN}', "invalid_api_response"),
        ({"success": True, "data": {"status": 200, "data": {"result": []}}}, "invalid_api_response"),
    ],
)
async def test_procurement_bad_api_response_does_not_upload(response, status):
    upload = AsyncMock()
    assert (await procurement.persist_response(response, SimpleNamespace(aupload_files=upload)))["status"] == status
    upload.assert_not_called()


@pytest.mark.parametrize(
    "skill,kind",
    [
        ("procurement-history", procurement.ProcurementExecutionTool),
        ("order-tracking", procurement.OrderExecutionTool),
    ],
)
def test_procurement_binds_only_existing_executor(skill, kind):
    tool = SyntheticTool()
    assert procurement.bind_procurement_tools([], object(), [skill]) == []
    assert procurement.bind_procurement_tools([tool], object(), []) == [tool]
    result = procurement.bind_procurement_tools([tool], object(), [skill])
    assert len(result) == 1 and isinstance(result[0], kind) and result[0].inner is tool


@pytest.mark.parametrize(
    "module,skill,kind",
    [
        (transport, "transport-history", transport.TransportTool),
        (customs, "customs-history", customs.CustomsTool),
    ],
)
async def test_deterministic_tools_use_bound_workspace_and_preserve_final(module, skill, kind):
    envelope = {
        "protocol": module.PROTOCOL,
        "status": "final",
        "terminal": True,
        "next_action": "none",
        "answer": "Synthetic final",
        "outcome": "capability_limits",
    }
    inner = SyntheticTool(response={"exitcode": 0, "log": module.MARKER + json.dumps(envelope)})
    workspace = object()
    bind = getattr(module, "bind_" + ("transport" if module is transport else "customs") + "_tools")
    assert bind([], workspace, [skill]) == []
    assert bind([inner], workspace, []) == [inner]
    (tool,) = bind([inner], workspace, [skill])
    assert isinstance(tool, kind) and tool.workspace is workspace and tool.inner is inner
    result = await tool.ainvoke(
        {"name": tool.name, "id": "synthetic", "type": "tool_call", "args": {"request": {"action": "explain_limits"}}}
    )
    assert isinstance(result, ToolMessage)
    assert result.artifact["answer"].endswith("Synthetic final")
    assert "python_code" in inner.calls[0]
    extractor = module.extract_transport_completion if module is transport else module.extract_customs_completion
    assert extractor([result]) == result.artifact["answer"]


async def test_procurement_fixed_completion_survives_tool_message():
    envelope = {
        "protocol": "procurement-fixed-entry-v1",
        "status": "final",
        "terminal": True,
        "next_action": "none",
        "answer": "Synthetic answer",
        "outcome": "no_records",
        "models": [],
    }
    inner = SyntheticTool(response={"exitcode": 0, "log": procurement.FINAL_MARKER + json.dumps(envelope)})
    tool = procurement.ProcurementExecutionTool(inner=inner)
    result = await tool.ainvoke(
        {"name": tool.name, "id": "synthetic", "type": "tool_call", "args": {"request": {"action": "help"}}}
    )
    assert procurement.extract_procurement_completion([result]).endswith("Synthetic answer")
    assert "request" not in inner.calls[0] and "python_code" in inner.calls[0]


@pytest.mark.parametrize("module,kind", [(transport, transport.TransportTool), (customs, customs.CustomsTool)])
async def test_fixed_executor_failure_is_explicit_and_never_empty_history(module, kind):
    result, artifact = await kind(inner=SyntheticTool(response={"exitcode": 1}), workspace=object())._arun(
        {"action": "explain_limits"}
    )
    assert json.loads(result)["outcome"] == "execution_error"
    assert artifact["answer"].endswith(module.FAILURE)


def test_native_token_injection_fails_closed_on_wrong_tool():
    inner = SimpleNamespace(
        tool_instance=SimpleNamespace(coroutine=None), tool_id=45, name=procurement.PROCUREMENT_TOOL_NAME
    )
    with pytest.raises(procurement.ProcurementAuthError, match="native_tool_scope_mismatch"):
        procurement.authenticated_native_procurement_tool(inner)


def test_token_cache_and_one_401_refresh_are_bounded(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    config = private / "client.json"
    config.write_text(
        json.dumps(
            {
                "base_url": "https://synthetic.invalid",
                "functionCode": "mock_procurement_history_v1",
                "appKey": "synthetic-key-123",
                "appSecret": "synthetic-secret-123",
            }
        )
    )
    config.chmod(0o600)
    manager = procurement.ProcurementTokenManager(config, private / "cache.json", "https://synthetic.invalid")
    calls = []

    def post(url, body, token=None, limit=None):
        calls.append((url, token))
        if url.endswith("/authapi/getToken"):
            count = sum(1 for url, _ in calls if url.endswith("/authapi/getToken"))
            return 200, json.dumps(
                {"errcode": 0, "access_token": "synthetic-token-" + str(count), "expires_in": 600}
            ).encode()
        return (401, b'{"code":"invalid_token"}') if token.endswith("1") else (200, b'{"ok":true}')

    manager._post = post
    assert (
        manager.query(manager.approved_base + procurement.AUTO_AUTH_CALL, {}, {"requestQuery": {}}, {}) == '{"ok":true}'
    )
    assert manager.token() == "synthetic-token-2"
    assert len(calls) == 4  # token, 401, refresh, successful replay; cache hit does no HTTP.
    assert private.joinpath("cache.json").stat().st_mode & 0o077 == 0
    with pytest.raises(procurement.ProcurementAuthError, match="query_scope_mismatch"):
        manager.query("https://other.invalid", {}, {"requestQuery": {}}, {})
    assert len(calls) == 4


def test_procurement_serialization_binds_only_real_latest_user_ordinal():
    call = {"name": procurement.CODE_TOOL_NAME, "id": "synthetic", "args": {"request": {"action": "show"}}}
    update = procurement.ProcurementSerialMiddleware._serial(
        {
            "messages": [
                HumanMessage(content="查看第2项"),
                AIMessage(content="", tool_calls=[call]),
            ]
        }
    )
    assert update["messages"][0].tool_calls[0]["args"]["request"]["item_index"] == 2
    assert procurement.explicit_input_index([HumanMessage(content="不要改第2项")]) is None


def test_openapi_request_schema_places_parameters_under_properties():
    # Exercise the actual pure method without importing the application bootstrap.
    path = Path(__file__).parents[2] / "bisheng_langchain/gpts/tools/api_tools/openapi.py"
    tree = ast.parse(path.read_text())
    method = next(
        n
        for n in next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "OpenApiTools").body
        if isinstance(n, ast.FunctionDef) and n.name == "parse_args_schema"
    )
    scope = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), str(path), "exec"), scope)
    schema = scope["parse_args_schema"](
        SimpleNamespace(
            params={
                "parameters": [
                    {
                        "name": "requestQuery",
                        "required": True,
                        "description": "synthetic",
                        "schema": {"type": "object", "properties": {"model": {"type": "string"}}},
                    },
                ]
            }
        )
    )
    assert schema["required"] == ["requestQuery"]
    assert schema["properties"]["requestQuery"]["properties"]["model"]["type"] == "string"
    assert "requestQuery" not in schema


@pytest.mark.parametrize(
    "status,body,expected_calls",
    [
        (401, b'{"code":"invalid_token"}', 2),
        (401, b'{"code":"other"}', 1),
        (403, b'{"code":"invalid_token"}', 1),
    ],
)
def test_auth_replay_never_exceeds_one_or_retries_permission_denial(status, body, expected_calls):
    manager = procurement.ProcurementTokenManager()
    manager.token = lambda rejected=None: "synthetic-token-123"
    calls = []

    def post(*args, **kwargs):
        calls.append(args)
        return status, body

    manager._post = post
    with pytest.raises(procurement.ProcurementAuthError, match="query_http_" + str(status)):
        manager.query(manager.approved_base + procurement.AUTO_AUTH_CALL, {}, {"requestQuery": {}}, {})
    assert len(calls) == expected_calls


def test_private_token_configuration_with_world_readable_mode_is_rejected(tmp_path):
    tmp_path.chmod(0o700)
    path = tmp_path / "client.json"
    path.write_text("{}")
    path.chmod(0o644)
    manager = procurement.ProcurementTokenManager(path, tmp_path / "cache.json")
    with pytest.raises(procurement.ProcurementAuthError, match="private_file_permissions"):
        manager.token()


async def test_order_fixed_executor_preserves_answer_without_writing_settings():
    envelope = {
        "protocol": "order-fixed-entry-v1",
        "terminal": True,
        "next_action": "none",
        "answer": "Synthetic order, no settings changed",
    }
    inner = SyntheticTool(response={"exitcode": 0, "log": "__ORDER_FIXED_FINAL__" + json.dumps(envelope)})
    tool = procurement.OrderExecutionTool(inner=inner)
    result = await tool.ainvoke(
        {"name": tool.name, "id": "synthetic", "type": "tool_call", "args": {"request": {"action": "help"}}}
    )
    assert procurement.extract_procurement_completion([result]) == envelope["answer"]
    assert "skills/order-tracking/scripts/run.py" in inner.calls[0]["python_code"]


def test_task_snapshot_uses_fixed_completion_and_clears_pending_tool_flag():
    path = Path(__file__).parents[2] / "bisheng/linsight/domain/task_exec.py"
    tree = ast.parse(path.read_text())
    subject_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "LinsightWorkflowTask")
    method = next(
        n for n in subject_class.body if isinstance(n, ast.FunctionDef) and n.name == "_capture_values_snapshot"
    )
    scope = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), str(path), "exec"), scope)
    subject = SimpleNamespace(_procurement_fixed_entry_enabled=True, _last_ai_has_pending_tool_calls=True)
    message = ToolMessage(
        content="ignored",
        name=procurement.CODE_TOOL_NAME,
        tool_call_id="synthetic",
        artifact=procurement.completion_artifact("Verified fixed answer"),
    )
    scope["_capture_values_snapshot"](subject, {"messages": [message]})
    assert subject._last_assistant_text == "Verified fixed answer"
    assert subject._last_ai_has_pending_tool_calls is False


def test_new_deployment_registration_clones_owner_without_changing_acl_identity(monkeypatch):
    from dataclasses import dataclass, replace

    @dataclass
    class Owner:
        url: str
        params: dict
        async_client: object = None

        async def arun(self, **kwargs):
            return kwargs

        def model_copy(self, *, update):
            return replace(self, **update)

    @dataclass
    class Native:
        coroutine: object

        def model_copy(self, *, update):
            return replace(self, **update)

    @dataclass
    class Executor:
        name: str
        tool_id: int
        tool_instance: object
        user_id: int = 501
        tenant_id: int = 7

        def model_copy(self, *, update):
            return replace(self, **update)

    key = "tool_type_103_df150bfcffc4d3a398f68301818e9165"
    monkeypatch.setattr(procurement, "PROCUREMENT_TOOL_ID", "207")
    monkeypatch.setattr(procurement, "PROCUREMENT_TOOL_NAME", key)
    owner = Owner(procurement.AUTO_AUTH_BASE, {"path": procurement.AUTO_AUTH_CALL, "method": "post"})
    inner = Executor(key, 207, Native(owner.arun))
    copied = procurement.authenticated_native_procurement_tool(inner)
    assert type(copied) is type(inner) and copied is not inner
    assert copied.user_id == inner.user_id and copied.tenant_id == inner.tenant_id
    assert isinstance(copied.tool_instance.coroutine.__self__.async_client, procurement.ProcurementAutoAuthHTTP)
    assert owner.async_client is None  # Other requests never inherit injected credentials.
    for invalid in (replace(inner, tool_id=44), replace(inner, name="other_tool")):
        with pytest.raises(procurement.ProcurementAuthError, match="native_tool_scope_mismatch"):
            procurement.authenticated_native_procurement_tool(invalid)
    owner.params["method"] = "get"
    with pytest.raises(procurement.ProcurementAuthError, match="native_tool_scope_mismatch"):
        procurement.authenticated_native_procurement_tool(inner)
    monkeypatch.setattr(procurement, "PROCUREMENT_TOOL_ID", "not-an-id")
    with pytest.raises(procurement.ProcurementAuthError, match="native_tool_scope_configuration"):
        procurement.authenticated_native_procurement_tool(inner)


@pytest.mark.parametrize(
    "question,history,expected",
    [
        ("当前订单：DEMO-ORDER-001\n\n用户问题：查看这笔订单", False, "DEMO-ORDER-001"),
        ("当前订单：DEMO-ORDER-001\n\n用户问题：那这单几天交付？", True, None),
        ("当前订单：DEMO-ORDER-001\n\n用户问题：切换到 DEMO-ORDER-NOT-EXISTS", True, "DEMO-ORDER-NOT-EXISTS"),
        ("查看 DEMO-ORDER-002 的交付日期", True, "DEMO-ORDER-002"),
        ("查DEMO-ORDER-002还有几天", True, "DEMO-ORDER-002"),
        ("查看DEMO-ORDER-002的物料", True, "DEMO-ORDER-002"),
        ("查SIM-ORDER-1还有几天", True, "SIM-ORDER-1"),
        ("注文DEMO-ORDER-002の納期", True, "DEMO-ORDER-002"),
        ("查DEMO-ORDER-010还有几天", True, "DEMO-ORDER-010"),
        ("查看第一个订单详情", True, None),
        ("show the first order details", True, None),
        ("一番目の注文の詳細", True, None),
        ("show order details", True, None),
        ("this order delivery date", True, None),
        ("この注文の納期は？", True, None),
        ("show order number DEMO-ORDER-002", True, "DEMO-ORDER-002"),
        ("show order no. DEMO-ORDER-002", True, "DEMO-ORDER-002"),
        ("注文番号DEMO-ORDER-002の納期を確認", True, "DEMO-ORDER-002"),
        ("現在の注文：DEMO-ORDER-001\n\nユーザーの質問：この注文の納期は？", True, None),
        ("查看 DEMO-ORDER-001 和 DEMO-ORDER-002", True, "__UNRESOLVED_ORDER_SWITCH__"),
        ("切换到另一笔订单", True, "__UNRESOLVED_ORDER_SWITCH__"),
        ("Current order: DEMO-ORDER-001\n\nUser question: How many days for this order?", True, None),
    ],
)
def test_order_identity_is_bound_to_current_user_not_model_history(question, history, expected):
    content = "# 前情回顾(本会话此前的对话)\n用户: 查看旧订单\n助手: 旧结果\n" if history else ""
    messages = [HumanMessage(content=content + "# 用户问题\n" + question)]
    assert procurement.OrderMiddleware._turn_order(messages) == expected
    call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "order-focus",
                "name": procurement.CODE_TOOL_NAME,
                "args": {"request": {"action": "detail", "order": "DEMO-ORDER-001"}},
            }
        ],
    )
    fixed = procurement.OrderMiddleware._serial({"messages": [*messages, call]})
    actual = (fixed["messages"][0] if fixed else call).tool_calls[0]["args"]["request"]
    assert actual.get("order") == expected


def test_order_fixed_scope_rejects_unknown_then_pronoun_and_accepts_explicit_replacement(tmp_path, monkeypatch):
    import importlib.util
    import shutil

    repo = Path(__file__).parents[4]
    skill = repo / "integrations/zhgyl/skills/order-tracking"
    bundle = tmp_path / "skills/order-tracking"
    shutil.copytree(skill, bundle)
    synthetic = {
        "orders": [
            {
                "id": "SIM-ORDER-1",
                "number": "DEMO-ORDER-001",
                "supplier": "Synthetic",
                "customer": "Synthetic",
                "amount": 1,
                "currency": "CNY",
                "lines": [],
                "invoices": [],
                "settlements": [],
            },
            {
                "id": "SIM-ORDER-2",
                "number": "DEMO-ORDER-002",
                "supplier": "Synthetic",
                "customer": "Synthetic",
                "amount": 2,
                "currency": "CNY",
                "lines": [],
                "invoices": [],
                "settlements": [],
            },
        ]
    }
    (bundle / "assets").mkdir(exist_ok=True)
    (bundle / "assets/orders.json").write_text(json.dumps(synthetic))
    monkeypatch.chdir(tmp_path)
    spec = importlib.util.spec_from_file_location("order_focus_regression", bundle / "scripts/run.py")
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    assert engine.execute({"action": "detail", "order": "DEMO-ORDER-001"})["orders"] == ["DEMO-ORDER-001"]
    assert engine.execute({"action": "detail", "order": "DEMO-ORDER-NOT-EXISTS"})["status"] == "waiting"
    for question in ("那这单几天交付？", "当前订单：DEMO-ORDER-001\n\n用户问题：那这单几天交付？"):
        messages = [
            HumanMessage(content="# 前情回顾\n旧订单已失效\n# 用户问题\n" + question),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "stale",
                        "name": procurement.CODE_TOOL_NAME,
                        "args": {"request": {"action": "detail", "order": "DEMO-ORDER-001"}},
                    }
                ],
            ),
        ]
        changed = procurement.OrderMiddleware._serial({"messages": messages})
        request = changed["messages"][0].tool_calls[0]["args"]["request"]
        result = engine.execute(request)
        assert result["status"] == "waiting" and not result["orders"]
        assert "DEMO-ORDER-001" not in result["answer"]
    assert engine.execute({"action": "detail", "order": "DEMO-ORDER-002"})["orders"] == ["DEMO-ORDER-002"]
    assert engine.execute({"action": "orders", "supplier": "No-such-supplier", "window": "all"})["status"] == "empty"
    assert engine.execute({"action": "detail", "position": 1})["status"] == "waiting"
    for invalid in (
        {"action": "detail", "position": True},
        {"action": "detail", "position": 31},
        {"action": "detail", "position": 1, "order": "DEMO-ORDER-002"},
    ):
        engine.execute({"action": "detail", "order": "DEMO-ORDER-002"})
        with pytest.raises(ValueError):
            engine.execute(invalid)
        assert engine.execute({"action": "detail"})["orders"] == []
    assert engine.execute({"action": "detail", "order": "DEMO-ORDER-00"})["status"] == "waiting"
    assert engine.execute({"action": "detail"})["orders"] == []
    assert engine.execute({"action": "detail", "order": "DEMO-ORDER-001"})["orders"] == ["DEMO-ORDER-001"]
    for index, order in enumerate(engine.D["orders"]):
        order["supplier"] = f"Synthetic-{index}"
        order["lines"] = [
            {
                "material": "Synthetic",
                "part": "P",
                "quantity": 1,
                "unit": "item",
                "price": 1,
                "amount": 1,
                "due": "2026-11-29",
            }
        ]
    listed = engine.execute({"action": "orders", "supplier": "Synthetic-1", "window": "all"})
    assert listed["orders"] == ["DEMO-ORDER-002"]
    ordinal_messages = [
        HumanMessage(content="# 前情回顾\n旧焦点001\n# 用户问题\n查看第一个订单详情"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "position",
                    "name": procurement.CODE_TOOL_NAME,
                    "args": {"request": {"action": "detail", "order": "DEMO-ORDER-001"}},
                }
            ],
        ),
    ]
    fixed = procurement.OrderMiddleware._serial({"messages": ordinal_messages})
    positional = fixed["messages"][0].tool_calls[0]["args"]["request"]
    assert positional == {"action": "detail", "position": 1}
    assert engine.execute(positional)["orders"] == ["DEMO-ORDER-002"]
    assert engine.execute({"action": "detail", "order": "DEMO-ORDER-NOT-EXISTS"})["status"] == "waiting"
    clarified = engine.execute(positional)
    assert clarified["status"] == "waiting" and not clarified["orders"]
    assert engine.execute({"action": "detail"})["orders"] == []
    assert engine.execute({"action": "detail", "order": "DEMO-ORDER-001"})["orders"] == ["DEMO-ORDER-001"]
    first, second, third = (tmp_path / name for name in ("turn-a", "turn-b", "turn-c"))
    for directory in (first, second, third):
        (directory / "scratch").mkdir(parents=True)
    monkeypatch.chdir(first)
    engine.execute({"action": "detail", "order": "DEMO-ORDER-001"})
    engine.execute({"action": "orders", "supplier": "Synthetic-1", "window": "all"})
    state_name = "scratch/order-assistant-context.json"
    shutil.copyfile(first / state_name, second / state_name)
    monkeypatch.chdir(second)
    assert engine.execute({"action": "detail", "position": 1})["orders"] == ["DEMO-ORDER-002"]
    engine.execute({"action": "detail", "order": "DEMO-ORDER-NOT-EXISTS"})
    assert (second / state_name).read_text() == "{}"
    shutil.copyfile(second / state_name, third / state_name)
    monkeypatch.chdir(third)
    assert engine.execute({"action": "detail"})["status"] == "waiting"
    assert engine.execute({"action": "detail", "position": 1})["status"] == "waiting"
    assert engine.execute({"action": "detail", "order": "DEMO-ORDER-001"})["orders"] == ["DEMO-ORDER-001"]
    engine.D["orders"] = [order for order in engine.D["orders"] if order["number"] != "DEMO-ORDER-001"]
    assert engine.execute({"action": "detail"})["status"] == "waiting"
    assert engine.execute({"action": "detail", "order": "DEMO-ORDER-002"})["orders"] == ["DEMO-ORDER-002"]


async def test_order_state_inherits_only_exact_file_and_never_overwrites_newer_tombstone():
    old, new, invalid = "a" * 32, "b" * 32, "c" * 32
    path = "scratch/order-assistant-context.json"
    blobs = {
        f"workspace/{old}/{path}": b'{"order":"DEMO-ORDER-002","visible_orders":["DEMO-ORDER-002"]}',
        f"workspace/{old}/scratch/other.json": b'{"unrelated":"must not inherit"}',
    }

    class Storage:
        bucket = "synthetic"

        def get_object_sync(self, bucket_name, object_name):
            assert bucket_name == self.bucket
            return blobs.get(object_name)

        def put_object_sync(self, bucket_name, object_name, file):
            assert bucket_name == self.bucket
            blobs[object_name] = file

    storage = Storage()
    await procurement.inherit_order_context(storage, old, new)
    assert blobs[f"workspace/{new}/{path}"] == blobs[f"workspace/{old}/{path}"]
    assert f"workspace/{new}/scratch/other.json" not in blobs
    blobs[f"workspace/{new}/{path}"] = b"{}"
    await procurement.inherit_order_context(storage, old, new)
    assert blobs[f"workspace/{new}/{path}"] == b"{}"
    await procurement.inherit_order_context(storage, new, invalid)
    assert blobs[f"workspace/{invalid}/{path}"] == b"{}"
    count = len(blobs)
    await procurement.inherit_order_context(storage, old, "../../outside")
    assert len(blobs) == count


async def test_order_context_restore_rejects_symlinks_and_nonregular_targets(tmp_path):
    from unittest.mock import Mock

    backend = SimpleNamespace(ensure_local=Mock(return_value=str(tmp_path / "scratch/order-assistant-context.json")))
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "scratch").symlink_to(outside, target_is_directory=True)
    assert await procurement.restore_order_context(backend, tmp_path) is None
    (tmp_path / "scratch").unlink()
    (tmp_path / "scratch").mkdir()
    state = tmp_path / "scratch/order-assistant-context.json"
    state.symlink_to(outside / "secret.json")
    assert await procurement.restore_order_context(backend, tmp_path) is None
    state.unlink()
    state.mkdir()
    assert await procurement.restore_order_context(backend, tmp_path) is None
    backend.ensure_local.assert_not_called()
    state.rmdir()
    assert await procurement.restore_order_context(backend, tmp_path) == str(state)
    backend.ensure_local.assert_called_once_with("scratch/order-assistant-context.json")


@pytest.mark.parametrize("changed", [None, "session_id", "user_id", "tenant_id"])
async def test_order_state_inheritance_requires_same_chat_owner_and_tenant(monkeypatch, changed):
    import sys
    from unittest.mock import Mock

    path = Path(__file__).parents[2] / "bisheng/linsight/domain/task_exec.py"
    subject = next(
        n for n in ast.parse(path.read_text()).body if isinstance(n, ast.ClassDef) and n.name == "LinsightWorkflowTask"
    )
    method = next(
        n for n in subject.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_seed_workspace_from_previous"
    )
    session = SimpleNamespace(id="b" * 32, session_id="chat", user_id=1, tenant_id=1, skills=["order-tracking"])
    previous = SimpleNamespace(id="a" * 32, session_id="chat", user_id=1, tenant_id=1)
    if changed:
        setattr(previous, changed, "other" if changed == "session_id" else 2)
    inherited = AsyncMock()
    monkeypatch.setattr(procurement, "inherit_order_context", inherited)
    monkeypatch.setitem(
        sys.modules,
        "bisheng.linsight.domain.services.workspace_backend",
        SimpleNamespace(seed_workspace_from_previous=AsyncMock(return_value=0)),
    )
    scope = {
        "LinsightSessionVersion": object,
        "LinsightSessionVersionDao": SimpleNamespace(
            get_session_versions_by_session_id=AsyncMock(return_value=[previous])
        ),
        "get_minio_storage": AsyncMock(return_value=object()),
        "logger": SimpleNamespace(info=Mock(), warning=Mock()),
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), str(path), "exec"), scope)
    await scope[method.name](object(), session)
    assert inherited.await_count == (1 if changed is None else 0)
