"""昆联工作流资料同步事件构造、签名投递、持久化重试与修改接口触发测试。"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import urllib.error

import pytest

from bisheng.api.services.flow import FlowService
from bisheng.api.services.workflow import WorkFlowService
from bisheng.api.v1 import workflow as workflow_api
from bisheng.api.v1.schemas import FlowVersionCreate
from bisheng.database.models.flow import FlowStatus, FlowType, FlowUpdate
from bisheng.workflow.application.kunlian_snapshot_sync import (
    KunlianWorkflowSnapshotSyncService,
    build_snapshot_event,
    compute_retry_delay,
    serialize_snapshot_event,
)
from bisheng.workflow.domain.clients.kunlian_snapshot import (
    KunlianSnapshotCallbackClient,
    SnapshotCallbackConfig,
)
from bisheng.workflow.domain.repositories.kunlian_snapshot_outbox import (
    ClaimedSnapshotEvent,
    STATUS_DELIVERED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RETRYING,
)

TEST_WORKFLOW_ID = "999f93b938084ca1811f91b6e0c9f355"
TEST_ACTOR_SUB = "a190cff1-7ec7-4dd3-90c2-53f6a25deda7"
TEST_SECRET_HEX = "d1790f6b5344a446f4c01d08c6f6a0cff1bc39bfa590e71a562b417d393a1aa3"
TEST_KEY_ID = "bisheng-workflow-test-20261117"
TEST_URL = "http://ai-gateway.comlansh.com:30001/api/v1/integrations/bisheng-workflow/snapshots"


class _FakeHttpResponse:
    def __init__(self, status: int, body: bytes, headers: dict[str, str] | None = None):
        self.status = status
        self._body = body
        self.headers = headers or {}

    def read(self, _limit: int = -1) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _InMemoryOutboxRepository:
    def __init__(self, clock):
        self._clock = clock
        self.rows: dict[str, dict] = {}

    async def enqueue(self, *, tenant_id, workflow_id, actor_sub, event_id, payload_json):
        now = self._clock()
        self.rows[event_id] = {
            "event_id": event_id,
            "tenant_id": tenant_id,
            "workflow_id": workflow_id,
            "actor_sub": actor_sub,
            "payload_json": payload_json,
            "status": STATUS_PENDING,
            "attempts": 0,
            "next_retry_at": now,
            "claimed_at": None,
            "delivered_at": None,
            "last_status_code": None,
            "last_request_id": None,
            "last_error": None,
        }
        return self.rows[event_id]

    async def claim_by_event_id(self, tenant_id, event_id, *, claim_ttl_seconds=60, ignore_schedule=False):
        row = self.rows.get(event_id)
        now = self._clock()
        if row is None or row["tenant_id"] != tenant_id or row["status"] not in (STATUS_PENDING, STATUS_RETRYING):
            return None
        if not ignore_schedule and row["next_retry_at"] > now:
            return None
        if row["claimed_at"] is not None and row["claimed_at"] > now - claim_ttl_seconds:
            return None
        row["claimed_at"] = now
        return ClaimedSnapshotEvent(
            event_id=row["event_id"],
            tenant_id=row["tenant_id"],
            workflow_id=row["workflow_id"],
            actor_sub=row["actor_sub"],
            payload_json=row["payload_json"],
            attempts=row["attempts"],
        )

    async def list_due_references(self, *, limit=100, claim_ttl_seconds=60):
        now = self._clock()
        due = []
        for row in self.rows.values():
            if row["status"] in (STATUS_PENDING, STATUS_RETRYING) and row["next_retry_at"] <= now:
                if row["claimed_at"] is None or row["claimed_at"] <= now - claim_ttl_seconds:
                    due.append((row["tenant_id"], row["event_id"]))
        return due[:limit]

    async def mark_delivered(self, tenant_id, event_id, *, status_code, request_id=None):
        row = self.rows[event_id]
        row["status"] = STATUS_DELIVERED
        row["attempts"] += 1
        row["claimed_at"] = None
        row["delivered_at"] = self._clock()
        row["last_status_code"] = status_code
        row["last_request_id"] = request_id
        row["last_error"] = None

    async def mark_retry(self, tenant_id, event_id, *, delay_seconds, status_code=None, request_id=None, error=None):
        row = self.rows[event_id]
        row["status"] = STATUS_RETRYING
        row["attempts"] += 1
        row["claimed_at"] = None
        row["next_retry_at"] = self._clock() + delay_seconds
        row["last_status_code"] = status_code
        row["last_request_id"] = request_id
        row["last_error"] = error

    async def mark_failed(self, tenant_id, event_id, *, status_code=None, request_id=None, error=None):
        row = self.rows[event_id]
        row["status"] = STATUS_FAILED
        row["attempts"] += 1
        row["claimed_at"] = None
        row["last_status_code"] = status_code
        row["last_request_id"] = request_id
        row["last_error"] = error


def test_build_snapshot_event_full_and_optional_rules():
    occurred = datetime(2026, 11, 17, 9, 0, 0, tzinfo=timezone.utc)
    event = build_snapshot_event(
        workflow_id=TEST_WORKFLOW_ID,
        actor_sub=TEST_ACTOR_SUB,
        occurred_at=occurred,
        event_id="workflow-sync-20261117-001",
        include_name=True,
        name="巡检工作流",
        include_description=True,
        description="",
        include_version=True,
        current_version_id=12,
        current_version_name="v1.1",
        include_status=True,
        status=2,
    )
    assert event == {
        "event_id": "workflow-sync-20261117-001",
        "workflow_id": TEST_WORKFLOW_ID,
        "actor_sub": TEST_ACTOR_SUB,
        "occurred_at": "2026-11-17T09:00:00Z",
        "name": "巡检工作流",
        "description": "",
        "current_version_id": "12",
        "current_version_name": "v1.1",
        "status": 2,
    }
    assert isinstance(event["current_version_id"], str)


def test_build_snapshot_event_empty_version_forces_offline_status():
    event = build_snapshot_event(
        workflow_id=TEST_WORKFLOW_ID,
        actor_sub=TEST_ACTOR_SUB,
        include_version=True,
        current_version_id=None,
        current_version_name=None,
        include_status=True,
        status=2,
    )
    assert event is not None
    assert event["current_version_id"] == ""
    assert event["current_version_name"] == ""
    assert event["status"] == 1


def test_build_snapshot_event_omits_blank_name_and_returns_none_when_no_optional_field():
    event = build_snapshot_event(
        workflow_id=TEST_WORKFLOW_ID,
        actor_sub=TEST_ACTOR_SUB,
        include_name=True,
        name="   ",
    )
    assert event is None


def test_client_hmac_signature_and_202_receipt_verification():
    captured = {}

    class _Opener:
        def open(self, request, timeout=10):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["headers"] = dict(request.header_items())
            captured["body"] = request.data
            return _FakeHttpResponse(
                202,
                json.dumps({"event_id": "evt-001", "status": "ACCEPTED"}).encode("utf-8"),
                headers={"X-Request-ID": "req-resp-123"},
            )

    cfg = SnapshotCallbackConfig(url=TEST_URL, key_id=TEST_KEY_ID, secret_hex=TEST_SECRET_HEX)
    client = KunlianSnapshotCallbackClient(cfg, clock=lambda: 1794906000, opener=_Opener())
    payload_json = serialize_snapshot_event(
        build_snapshot_event(
            workflow_id=TEST_WORKFLOW_ID,
            actor_sub=TEST_ACTOR_SUB,
            event_id="evt-001",
            include_status=True,
            status=1,
        )
    )

    result = client.send(event_id="evt-001", payload_json=payload_json)
    assert result.outcome == "delivered"
    assert result.status_code == 202
    assert result.request_id == "req-resp-123"
    assert captured["url"] == TEST_URL
    assert captured["method"] == "POST"
    assert captured["headers"]["X-workflow-key-id"] == TEST_KEY_ID
    assert captured["headers"]["X-workflow-timestamp"] == "1794906000"

    expected_sig = hmac.new(
        bytes.fromhex(TEST_SECRET_HEX),
        b"1794906000." + payload_json.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    assert captured["headers"]["X-workflow-signature"] == expected_sig


@pytest.mark.parametrize(
    ("code", "expected_outcome"),
    [
        (429, "retry"),
        (500, "retry"),
        (503, "retry"),
        (302, "failed"),
        (400, "failed"),
        (401, "failed"),
        (403, "failed"),
        (404, "failed"),
        (409, "failed"),
        (413, "failed"),
    ],
)
def test_client_http_error_classification(code, expected_outcome):
    class _ErrorOpener:
        def open(self, request, timeout=10):
            raise urllib.error.HTTPError(
                request.full_url,
                code,
                "err",
                hdrs={"X-Request-ID": f"req-{code}"},
                fp=io.BytesIO(b"plain text error"),
            )

    cfg = SnapshotCallbackConfig(url=TEST_URL, key_id=TEST_KEY_ID, secret_hex=TEST_SECRET_HEX)
    client = KunlianSnapshotCallbackClient(cfg, clock=lambda: 1794906000, opener=_ErrorOpener())
    res = client.send(event_id="evt-err", payload_json='{"event_id":"evt-err"}')
    assert res.outcome == expected_outcome
    assert res.status_code == code
    assert res.request_id == f"req-{code}"


async def test_service_enqueue_retry_keeps_event_id_and_resigns_with_new_timestamp():
    now = [1794906000]
    repo = _InMemoryOutboxRepository(clock=lambda: now[0])
    dispatched: list[tuple[int, str]] = []
    sent_requests: list[tuple[str, str, bytes]] = []

    responses = [
        urllib.error.HTTPError(TEST_URL, 503, "unavailable", hdrs={"X-Request-ID": "req-503"}, fp=io.BytesIO(b"busy")),
        "ok",
    ]

    class _SequenceOpener:
        def open(self, request, timeout=10):
            headers = dict(request.header_items())
            sent_requests.append((headers["X-workflow-timestamp"], headers["X-workflow-signature"], request.data))
            action = responses.pop(0)
            if isinstance(action, Exception):
                raise action
            body_obj = json.loads(request.data.decode("utf-8"))
            return _FakeHttpResponse(
                202,
                json.dumps({"event_id": body_obj["event_id"], "status": "ACCEPTED"}).encode("utf-8"),
                headers={"X-Request-ID": "req-202"},
            )

    cfg = SnapshotCallbackConfig(url=TEST_URL, key_id=TEST_KEY_ID, secret_hex=TEST_SECRET_HEX)
    service = KunlianWorkflowSnapshotSyncService(
        repository=repo,
        config_loader=lambda: cfg,
        client_factory=lambda c: KunlianSnapshotCallbackClient(c, clock=lambda: now[0], opener=_SequenceOpener()),
        actor_sub_resolver=AsyncMock(return_value=TEST_ACTOR_SUB),
        dispatcher=lambda tenant_id, event_id: dispatched.append((tenant_id, event_id)),
    )

    event_id = await service.enqueue_snapshot(
        tenant_id=2,
        user_id=10,
        workflow_id=TEST_WORKFLOW_ID,
        include_name=True,
        name="新名称",
    )
    assert event_id is not None
    assert dispatched == [(2, event_id)]

    # 第一次投递遇 503 -> RETRYING，退避 1 秒
    outcome_1 = await service.deliver_event(2, event_id)
    assert outcome_1 == "retry"
    assert repo.rows[event_id]["status"] == STATUS_RETRYING
    assert repo.rows[event_id]["next_retry_at"] == 1794906000 + compute_retry_delay(0)

    # 未到重试时间，reconcile 不派发
    assert await service.reconcile_due_events() == 0

    # 推进时间到退避到期，reconcile 派发并二次投递成功
    now[0] += 5
    assert await service.reconcile_due_events() == 1
    outcome_2 = await service.deliver_event(2, event_id)
    assert outcome_2 == "delivered"
    assert repo.rows[event_id]["status"] == STATUS_DELIVERED
    assert repo.rows[event_id]["last_request_id"] == "req-202"

    # 校验两次发送：正文原始字节完全相同（含 event_id），时间戳与签名均重新生成
    assert len(sent_requests) == 2
    assert sent_requests[0][2] == sent_requests[1][2]
    assert sent_requests[0][0] != sent_requests[1][0]
    assert sent_requests[0][1] != sent_requests[1][1]


async def test_service_skips_when_unconfigured_or_non_kunlian_user():
    repo = _InMemoryOutboxRepository(clock=lambda: 1794906000)
    service_unconfigured = KunlianWorkflowSnapshotSyncService(
        repository=repo,
        config_loader=lambda: None,
        actor_sub_resolver=AsyncMock(return_value=TEST_ACTOR_SUB),
    )
    assert (
        await service_unconfigured.enqueue_snapshot(
            tenant_id=2, user_id=10, workflow_id=TEST_WORKFLOW_ID, include_status=True, status=1
        )
        is None
    )

    cfg = SnapshotCallbackConfig(url=TEST_URL, key_id=TEST_KEY_ID, secret_hex=TEST_SECRET_HEX)
    service_no_sub = KunlianWorkflowSnapshotSyncService(
        repository=repo,
        config_loader=lambda: cfg,
        actor_sub_resolver=AsyncMock(return_value=None),
    )
    assert (
        await service_no_sub.enqueue_snapshot(
            tenant_id=2, user_id=10, workflow_id=TEST_WORKFLOW_ID, include_status=True, status=1
        )
        is None
    )
    assert repo.rows == {}


async def test_update_flow_triggers_snapshot_on_name_description_change(monkeypatch):
    notify_mock = AsyncMock(return_value="evt-1")
    monkeypatch.setattr(
        "bisheng.workflow.application.kunlian_snapshot_sync.notify_kunlian_workflow_snapshot_safe",
        notify_mock,
    )
    db_flow = SimpleNamespace(
        id=TEST_WORKFLOW_ID,
        tenant_id=2,
        name="旧名称",
        description="旧描述",
        status=FlowStatus.OFFLINE.value,
        logo="logo.png",
        flow_type=FlowType.WORKFLOW.value,
    )
    monkeypatch.setattr(workflow_api.FlowDao, "aget_flow_by_id", AsyncMock(return_value=db_flow))
    monkeypatch.setattr(workflow_api.FlowDao, "aupdate_flow", AsyncMock(side_effect=lambda f: f))
    monkeypatch.setattr(workflow_api, "check_business_action", AsyncMock(return_value=True))
    monkeypatch.setattr(workflow_api.telemetry_service, "log_event", AsyncMock())
    monkeypatch.setattr(workflow_api.FlowService, "update_flow_hook", AsyncMock(return_value=True))
    monkeypatch.setattr("bisheng.workflow.application.kunlian_workflow_management.workflow_scope", lambda *a, **kw: None)

    user = SimpleNamespace(user_id=10, tenant_id=2)
    req = SimpleNamespace(headers={})
    await workflow_api.update_flow(
        request=req,
        flow_id=TEST_WORKFLOW_ID,
        flow=FlowUpdate(name="新名称", description="新描述"),
        login_user=user,
    )

    notify_mock.assert_awaited_once_with(
        tenant_id=2,
        user_id=10,
        workflow_id=TEST_WORKFLOW_ID,
        include_name=True,
        name="新名称",
        include_description=True,
        description="新描述",
        include_status=False,
        status=FlowStatus.OFFLINE.value,
    )


async def test_change_current_version_triggers_snapshot(monkeypatch):
    notify_mock = AsyncMock(return_value="evt-2")
    monkeypatch.setattr(
        "bisheng.workflow.application.kunlian_snapshot_sync.notify_kunlian_workflow_snapshot_safe",
        notify_mock,
    )
    flow_info = SimpleNamespace(
        id=TEST_WORKFLOW_ID,
        tenant_id=2,
        status=FlowStatus.OFFLINE.value,
        data={},
    )
    version_info = SimpleNamespace(id=12, flow_id=TEST_WORKFLOW_ID, name="v1.2", is_current=0, data={})

    monkeypatch.setattr("bisheng.api.services.flow.telemetry_service.log_event", AsyncMock())
    monkeypatch.setattr(FlowService, "judge_flow_write_permission", AsyncMock(return_value=flow_info))
    monkeypatch.setattr("bisheng.api.services.flow.FlowVersionDao.aget_version_by_id", AsyncMock(return_value=version_info))
    monkeypatch.setattr("bisheng.api.services.flow.FlowVersionDao.change_current_version", AsyncMock(return_value=True))
    monkeypatch.setattr(FlowService, "update_flow_hook", AsyncMock(return_value=True))
    monkeypatch.setattr("bisheng.workflow.application.kunlian_workflow_management.workflow_scope", lambda *a, **kw: None)
    monkeypatch.setattr("bisheng.workflow.application.platform_node_publication.uses_platform_nodes", lambda *a: False)

    user = SimpleNamespace(user_id=10, tenant_id=2)
    req = SimpleNamespace(headers={})
    await FlowService.change_current_version(req, user, TEST_WORKFLOW_ID, 12)

    notify_mock.assert_awaited_once_with(
        tenant_id=2,
        user_id=10,
        workflow_id=TEST_WORKFLOW_ID,
        include_version=True,
        current_version_id=12,
        current_version_name="v1.2",
    )


async def test_update_version_info_triggers_only_when_current_version_name_changes(monkeypatch):
    notify_mock = AsyncMock(return_value="evt-3")
    monkeypatch.setattr(
        "bisheng.workflow.application.kunlian_snapshot_sync.notify_kunlian_workflow_snapshot_safe",
        notify_mock,
    )
    flow_info = SimpleNamespace(id=TEST_WORKFLOW_ID, tenant_id=2, status=FlowStatus.OFFLINE.value, data={})
    version_info = SimpleNamespace(
        id=12, flow_id=TEST_WORKFLOW_ID, name="v1.1", description="", is_current=1, data={}, is_delete=0
    )

    monkeypatch.setattr("bisheng.api.services.flow.telemetry_service.log_event", AsyncMock())
    monkeypatch.setattr("bisheng.api.services.flow.FlowVersionDao.aget_version_by_id", AsyncMock(return_value=version_info))
    monkeypatch.setattr("bisheng.api.services.flow.FlowVersionDao.aupdate_version", AsyncMock(side_effect=lambda v: v))
    monkeypatch.setattr(FlowService, "judge_flow_write_permission", AsyncMock(return_value=flow_info))
    monkeypatch.setattr(FlowService, "update_flow_hook", AsyncMock(return_value=True))
    monkeypatch.setattr("bisheng.workflow.application.kunlian_workflow_management.workflow_scope", lambda *a, **kw: None)
    monkeypatch.setattr("bisheng.workflow.application.platform_node_publication.uses_platform_nodes", lambda *a: False)

    user = SimpleNamespace(user_id=10, tenant_id=2)
    req = SimpleNamespace(headers={})
    await FlowService.update_version_info(req, user, 12, FlowVersionCreate(name="v1.2"))

    notify_mock.assert_awaited_once_with(
        tenant_id=2,
        user_id=10,
        workflow_id=TEST_WORKFLOW_ID,
        include_version=True,
        current_version_id=12,
        current_version_name="v1.2",
    )


async def test_update_flow_status_triggers_online_and_offline_snapshots(monkeypatch):
    notify_mock = AsyncMock(return_value="evt-4")
    monkeypatch.setattr(
        "bisheng.workflow.application.kunlian_snapshot_sync.notify_kunlian_workflow_snapshot_safe",
        notify_mock,
    )
    db_flow = SimpleNamespace(id=TEST_WORKFLOW_ID, tenant_id=2, name="W1", status=FlowStatus.OFFLINE.value, data={})
    version_info = SimpleNamespace(id=12, flow_id=TEST_WORKFLOW_ID, name="v1.1", data={})

    monkeypatch.setattr("bisheng.api.services.workflow.FlowDao.aget_flow_by_id", AsyncMock(return_value=db_flow))
    monkeypatch.setattr("bisheng.api.services.workflow.FlowDao.aupdate_flow", AsyncMock(return_value=db_flow))
    monkeypatch.setattr("bisheng.api.services.workflow.FlowVersionDao.aget_version_by_id", AsyncMock(return_value=version_info))
    monkeypatch.setattr("bisheng.api.services.workflow.FlowVersionDao.change_current_version", AsyncMock(return_value=True))
    monkeypatch.setattr("bisheng.api.services.workflow.require_business_action", AsyncMock())
    monkeypatch.setattr("bisheng.api.services.workflow.telemetry_service.log_event", AsyncMock())
    monkeypatch.setattr("bisheng.api.services.workflow.check_memory_nodes_for_publish", lambda *a: None)
    monkeypatch.setattr("bisheng.api.services.workflow.Workflow", MagicMock())
    monkeypatch.setattr("bisheng.workflow.application.kunlian_workflow_management.workflow_scope", lambda *a, **kw: None)
    monkeypatch.setattr("bisheng.workflow.domain.schemas.platform_knowledge.uses_platform_knowledge", lambda *a: False)
    monkeypatch.setattr("bisheng.workflow.domain.schemas.platform_agent.uses_platform_agent", lambda *a: False)

    user = SimpleNamespace(user_id=10, tenant_id=2)

    await WorkFlowService.update_flow_status(user, TEST_WORKFLOW_ID, 12, FlowStatus.ONLINE.value)
    await WorkFlowService.update_flow_status(user, TEST_WORKFLOW_ID, 12, FlowStatus.OFFLINE.value)

    assert notify_mock.await_count == 2
    assert notify_mock.await_args_list[0].kwargs == {
        "tenant_id": 2,
        "user_id": 10,
        "workflow_id": TEST_WORKFLOW_ID,
        "include_status": True,
        "status": FlowStatus.ONLINE.value,
        "include_version": True,
        "current_version_id": 12,
        "current_version_name": "v1.1",
    }
    assert notify_mock.await_args_list[1].kwargs == {
        "tenant_id": 2,
        "user_id": 10,
        "workflow_id": TEST_WORKFLOW_ID,
        "include_status": True,
        "status": FlowStatus.OFFLINE.value,
        "include_version": False,
        "current_version_id": None,
        "current_version_name": None,
    }
