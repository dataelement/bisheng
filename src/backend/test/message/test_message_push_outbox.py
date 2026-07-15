from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.message.domain.models.message_push_outbox import (
    MessagePushOutbox,
    MessagePushOutboxStatus,
)
from bisheng.message.domain.repositories.implementations.message_push_outbox_repository_impl import (
    MessagePushOutboxRepositoryImpl,
)
from bisheng.notification.external.shougang_madp_client import ShougangMADPClient
from bisheng.notification.external.shougang_wechat_payload import render_body, resolve_action_code
from bisheng.notification.shougang_wechat_forwarder import maybe_push_shougang_wechat_message

# ---- Repository tests ----


@pytest.mark.asyncio
async def test_find_pending_ready(async_db_session):
    repo = MessagePushOutboxRepositoryImpl(async_db_session)

    now = datetime.now()
    ready = MessagePushOutbox(
        action_code="qa_expert_invited",
        body="ready",
        status=MessagePushOutboxStatus.PENDING,
        next_retry_at=None,
    )
    future = MessagePushOutbox(
        action_code="qa_expert_invited",
        body="future",
        status=MessagePushOutboxStatus.PENDING,
        next_retry_at=now + timedelta(hours=1),
    )
    sent = MessagePushOutbox(
        action_code="qa_expert_invited",
        body="sent",
        status=MessagePushOutboxStatus.SENT,
    )
    await repo.save(ready)
    await repo.save(future)
    await repo.save(sent)

    results = await repo.find_pending_ready(before=now, limit=10)
    assert len(results) == 1
    assert results[0].body == "ready"


@pytest.mark.asyncio
async def test_mark_sent(async_db_session):
    repo = MessagePushOutboxRepositoryImpl(async_db_session)
    record = MessagePushOutbox(
        action_code="qa_expert_invited",
        body="x",
        status=MessagePushOutboxStatus.PENDING,
    )
    saved = await repo.save(record)

    sent_at = datetime.now()
    updated = await repo.mark_sent(saved.id, sent_at)
    assert updated.status == MessagePushOutboxStatus.SENT
    assert updated.sent_at is not None
    assert updated.failure_reason is None


@pytest.mark.asyncio
async def test_mark_pending_retry(async_db_session):
    repo = MessagePushOutboxRepositoryImpl(async_db_session)
    record = MessagePushOutbox(action_code="qa_expert_invited", body="x")
    saved = await repo.save(record)

    next_retry = datetime.now() + timedelta(minutes=5)
    updated = await repo.mark_pending_retry(saved.id, 1, next_retry, "timeout")
    assert updated.status == MessagePushOutboxStatus.PENDING
    assert updated.retry_count == 1
    assert updated.next_retry_at == next_retry
    assert updated.failure_reason == "timeout"


@pytest.mark.asyncio
async def test_mark_failed(async_db_session):
    repo = MessagePushOutboxRepositoryImpl(async_db_session)
    record = MessagePushOutbox(action_code="qa_expert_invited", body="x")
    saved = await repo.save(record)

    updated = await repo.mark_failed(saved.id, 3, "max retries")
    assert updated.status == MessagePushOutboxStatus.FAILED
    assert updated.retry_count == 3
    assert updated.failure_reason == "max retries"


# ---- Payload rendering tests ----


@pytest.fixture
def mock_conf():
    conf = MagicMock()
    conf.templates.qa_expert_invited = "{applicant} 邀请你回答「{resource}」\n{preview}"
    conf.templates.qa_expert_answered = "{applicant} 回答了「{resource}」\n{preview}"
    conf.templates.qa_answer_commented = "{applicant} 评论了「{resource}」\n{preview}"
    conf.templates.qa_answer_accepted = "你的回答「{resource}」被 {applicant} 采纳\n{preview}"
    return conf


def _make_content(applicant="张三", resource="问题标题", preview="预览文本"):
    return [
        {"type": "user", "content": f"@{applicant}", "metadata": {"user_id": 1}},
        {"type": "system_text", "content": "qa_expert_invited"},
        {"type": "business_url", "content": f"--{resource}", "metadata": {"business_type": "qa_question"}},
        {"type": "tooltip_text", "content": preview},
    ]


def test_render_body_all_variables(mock_conf):
    body = render_body(action_code="qa_expert_invited", content=_make_content(), conf=mock_conf)
    assert "张三" in body
    assert "问题标题" in body
    assert "预览文本" in body


def test_render_body_missing_preview(mock_conf):
    content = [
        {"type": "user", "content": "@李四"},
        {"type": "business_url", "content": "--标题"},
    ]
    body = render_body(action_code="qa_expert_answered", content=content, conf=mock_conf)
    assert "李四" in body
    assert "标题" in body


def test_resolve_action_code_prefers_model_field():
    msg = MagicMock()
    msg.action_code = "qa_answer_accepted"
    msg.content = [{"type": "system_text", "content": "qa_expert_invited"}]
    assert resolve_action_code(msg) == "qa_answer_accepted"


def test_resolve_action_code_falls_back_to_system_text():
    msg = MagicMock()
    msg.action_code = None
    msg.content = [{"type": "system_text", "content": "qa_answer_commented"}]
    assert resolve_action_code(msg) == "qa_answer_commented"


# ---- HTTP Client tests ----


@pytest.fixture
def mock_wechat_settings():
    with patch("bisheng.notification.external.shougang_madp_client.settings") as m:
        conf = MagicMock()
        conf.api_url = "https://mobms.sggf.com.cn:30201/madp-app/madp/qywxPush-api/pushMessage"
        conf.id = ""
        conf.agentid = "1000053"
        conf.key = "secret-key"
        conf.sys_id = "1"
        conf.msg_type = "text"
        conf.timeout_seconds = 5.0
        m.get_shougang_wechat_message_push_conf.return_value = conf
        yield m


@pytest.mark.usefixtures("mock_wechat_settings")
@pytest.mark.asyncio
async def test_push_text_message_success(caplog):
    import logging

    caplog.set_level(logging.INFO)
    client = ShougangMADPClient()
    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch("bisheng.notification.external.shougang_madp_client.httpx.AsyncClient") as ACli:
        ACli.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
        success, error = await client.push_text_message(outbox_id=1, user_ids=["u1", "u2"], body="hello")

    assert success is True
    assert error is None
    assert "wechat_push.attempt" in caplog.text
    assert "wechat_push.result" in caplog.text


@pytest.mark.usefixtures("mock_wechat_settings")
@pytest.mark.asyncio
async def test_push_text_message_http_error():
    client = ShougangMADPClient()
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "server error"

    with patch("bisheng.notification.external.shougang_madp_client.httpx.AsyncClient") as ACli:
        ACli.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
        success, error = await client.push_text_message(outbox_id=2, user_ids=["u1"], body="hello")

    assert success is False
    assert "http_status_500" in error


@pytest.mark.usefixtures("mock_wechat_settings")
@pytest.mark.asyncio
async def test_push_text_message_timeout():
    import httpx

    client = ShougangMADPClient()

    with patch("bisheng.notification.external.shougang_madp_client.httpx.AsyncClient") as ACli:
        ACli.return_value.__aenter__.return_value.post = AsyncMock(side_effect=httpx.ConnectTimeout("timeout"))
        success, error = await client.push_text_message(outbox_id=3, user_ids=["u1"], body="hello")

    assert success is False
    assert error == "timeout"


@pytest.mark.usefixtures("mock_wechat_settings")
@pytest.mark.asyncio
async def test_push_text_message_empty_users():
    client = ShougangMADPClient()
    with patch("bisheng.notification.external.shougang_madp_client.httpx.AsyncClient") as ACli:
        post = AsyncMock()
        ACli.return_value.__aenter__.return_value.post = post
        success, error = await client.push_text_message(outbox_id=4, user_ids=[], body="hello")
        post.assert_not_called()
    assert success is False
    assert error == "empty_user_ids"


@pytest.mark.usefixtures("mock_wechat_settings")
@pytest.mark.asyncio
async def test_push_text_message_request_shape():
    import json

    client = ShougangMADPClient()
    mock_response = MagicMock()
    mock_response.status_code = 200
    captured = {}

    async def fake_post(url, content=None, headers=None):
        captured["url"] = url
        captured["content"] = content
        captured["headers"] = headers
        return mock_response

    with patch("bisheng.notification.external.shougang_madp_client.httpx.AsyncClient") as ACli:
        ACli.return_value.__aenter__.return_value.post = AsyncMock(side_effect=fake_post)
        await client.push_text_message(outbox_id=5, user_ids=["u1"], body="body-text")

    assert captured["url"] == "https://mobms.sggf.com.cn:30201/madp-app/madp/qywxPush-api/pushMessage"
    body = json.loads(captured["content"].decode("utf-8"))
    assert body["agentid"] == "1000053"
    assert body["sysId"] == "1"
    assert body["msgType"] == "text"
    assert body["users"] == ["u1"]
    assert body["body"] == {"content": "body-text"}


# ---- Hooker tests ----


@pytest.fixture
def mock_wechat_conf():
    conf = MagicMock()
    conf.enabled = True
    conf.max_retries = 3
    conf.templates.qa_expert_invited = "{applicant} 邀请你回答「{resource}」\n{preview}"
    return conf


@pytest.mark.asyncio
async def test_hook_skipped_when_disabled(mock_wechat_conf):
    mock_wechat_conf.enabled = False
    with patch("bisheng.notification.shougang_wechat_forwarder.settings") as m:
        m.get_shougang_wechat_message_push_conf.return_value = mock_wechat_conf
        msg = MagicMock()
        msg.id = 1
        msg.receiver = [10]
        msg.action_code = "qa_expert_invited"
        msg.content = _make_content()

        with patch("bisheng.notification.shougang_wechat_forwarder.get_async_db_session") as session_mock:
            await maybe_push_shougang_wechat_message(msg)
            session_mock.assert_not_called()


@pytest.mark.asyncio
async def test_hook_skipped_for_non_pushable_action_code(mock_wechat_conf):
    with patch("bisheng.notification.shougang_wechat_forwarder.settings") as m:
        m.get_shougang_wechat_message_push_conf.return_value = mock_wechat_conf
        msg = MagicMock()
        msg.id = 1
        msg.receiver = [10]
        msg.action_code = "request_channel"
        msg.content = []

        with patch("bisheng.notification.shougang_wechat_forwarder.get_async_db_session") as session_mock:
            await maybe_push_shougang_wechat_message(msg)
            session_mock.assert_not_called()


@pytest.mark.asyncio
async def test_hook_skipped_when_no_wechat_user_id(mock_wechat_conf):
    with patch("bisheng.notification.shougang_wechat_forwarder.settings") as m:
        m.get_shougang_wechat_message_push_conf.return_value = mock_wechat_conf
        with patch("bisheng.notification.shougang_wechat_forwarder.UserDao") as UserDao:
            UserDao.aget_user_by_ids = AsyncMock(return_value=[MagicMock(wechat_user_id=None)])
            msg = MagicMock()
            msg.id = 1
            msg.receiver = [10]
            msg.action_code = "qa_expert_invited"
            msg.content = _make_content()

            with patch("bisheng.notification.shougang_wechat_forwarder.get_async_db_session") as session_mock:
                await maybe_push_shougang_wechat_message(msg)
                session_mock.assert_not_called()


@pytest.mark.asyncio
async def test_hook_creates_outbox(mock_wechat_conf):
    with patch("bisheng.notification.shougang_wechat_forwarder.settings") as m:
        m.get_shougang_wechat_message_push_conf.return_value = mock_wechat_conf
        with patch("bisheng.notification.shougang_wechat_forwarder.UserDao") as UserDao:
            user = MagicMock(wechat_user_id="wx123")
            UserDao.aget_user_by_ids = AsyncMock(return_value=[user])

            fake_session = MagicMock()
            fake_repo = MagicMock()
            saved = MagicMock()
            saved.id = 42
            fake_repo.save = AsyncMock(return_value=saved)
            fake_session.__aenter__ = AsyncMock(return_value=fake_session)
            fake_session.__aexit__ = AsyncMock(return_value=False)

            with patch(
                "bisheng.notification.shougang_wechat_forwarder.MessagePushOutboxRepositoryImpl",
                return_value=fake_repo,
            ):
                with patch(
                    "bisheng.notification.shougang_wechat_forwarder.get_async_db_session",
                    return_value=fake_session,
                ):
                    msg = MagicMock()
                    msg.id = 1
                    msg.receiver = [10]
                    msg.action_code = "qa_expert_invited"
                    msg.content = _make_content()

                    await maybe_push_shougang_wechat_message(msg)

            fake_repo.save.assert_called_once()
            call_args = fake_repo.save.call_args[0][0]
            assert call_args.action_code == "qa_expert_invited"
            assert call_args.wechat_user_ids == ["wx123"]
            assert "张三" in call_args.body
