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
from bisheng.worker.message.outbox_processor import wechatOutboxProcessor
from bisheng.worker.message.tasks import (
    push_single_wechat_message,
    scan_wechat_message_push_outbox,
)


@pytest.fixture
def mock_wechat_conf():
    conf = MagicMock()
    conf.enabled = True
    conf.batch_size = 10
    conf.max_retries = 3
    conf.retry_base_seconds = 60
    conf.retry_max_seconds = 3600
    return conf


@pytest.fixture
def pending_record_factory(async_db_session):
    async def _make(action_code="qa_expert_invited", next_retry_at=None):
        repo = MessagePushOutboxRepositoryImpl(async_db_session)
        record = MessagePushOutbox(
            action_code=action_code,
            body="test body",
            status=MessagePushOutboxStatus.PENDING,
            next_retry_at=next_retry_at,
            wechat_user_ids=["wx001"],
        )
        saved = await repo.save(record)
        return saved

    return _make


# ---- wechatOutboxProcessor.scan_and_dispatch tests ----


@pytest.mark.asyncio
async def test_processor_scan_disabled(mock_wechat_conf):
    with patch("bisheng.worker.message.outbox_processor.settings") as m:
        m.get_shougang_wechat_message_push_conf.return_value = mock_wechat_conf
        mock_wechat_conf.enabled = False
        with patch("bisheng.worker.message.outbox_processor.get_async_db_session") as session_mock:
            processor = wechatOutboxProcessor()
            result = await processor.scan_and_dispatch()
            assert result == 0
            session_mock.assert_not_called()


@pytest.mark.asyncio
async def test_processor_scan_no_pending_records(async_db_session, mock_wechat_conf):
    with patch("bisheng.worker.message.outbox_processor.settings") as m:
        m.get_shougang_wechat_message_push_conf.return_value = mock_wechat_conf
        with patch(
            "bisheng.worker.message.outbox_processor.get_async_db_session",
            return_value=async_db_session,
        ):
            with patch("bisheng.worker.message.tasks.push_single_wechat_message.delay") as delay_mock:
                processor = wechatOutboxProcessor()
                result = await processor.scan_and_dispatch()
                assert result == 0
                delay_mock.assert_not_called()


@pytest.mark.asyncio
async def test_processor_scan_dispatches_pending_records(async_db_session, mock_wechat_conf, pending_record_factory):
    record1 = await pending_record_factory()
    record2 = await pending_record_factory(action_code="qa_expert_answered")

    with patch("bisheng.worker.message.outbox_processor.settings") as m:
        m.get_shougang_wechat_message_push_conf.return_value = mock_wechat_conf
        with patch(
            "bisheng.worker.message.outbox_processor.get_async_db_session",
            return_value=async_db_session,
        ):
            with patch("bisheng.worker.message.tasks.push_single_wechat_message.delay") as delay_mock:
                processor = wechatOutboxProcessor()
                result = await processor.scan_and_dispatch()
                assert result == 2
                delay_mock.assert_any_call(record1.id)
                delay_mock.assert_any_call(record2.id)


@pytest.mark.asyncio
async def test_processor_scan_respects_batch_size(async_db_session, mock_wechat_conf, pending_record_factory):
    for _ in range(5):
        await pending_record_factory()

    mock_wechat_conf.batch_size = 2
    with patch("bisheng.worker.message.outbox_processor.settings") as m:
        m.get_shougang_wechat_message_push_conf.return_value = mock_wechat_conf
        with patch(
            "bisheng.worker.message.outbox_processor.get_async_db_session",
            return_value=async_db_session,
        ):
            with patch("bisheng.worker.message.tasks.push_single_wechat_message.delay") as delay_mock:
                processor = wechatOutboxProcessor()
                result = await processor.scan_and_dispatch()
                assert result == 2
                assert delay_mock.call_count == 2


@pytest.mark.asyncio
async def test_processor_scan_skips_future_retry_records(async_db_session, mock_wechat_conf, pending_record_factory):
    future = datetime.now() + timedelta(hours=1)
    ready_record = await pending_record_factory(next_retry_at=None)
    await pending_record_factory(next_retry_at=future)

    with patch("bisheng.worker.message.outbox_processor.settings") as m:
        m.get_shougang_wechat_message_push_conf.return_value = mock_wechat_conf
        with patch(
            "bisheng.worker.message.outbox_processor.get_async_db_session",
            return_value=async_db_session,
        ):
            with patch("bisheng.worker.message.tasks.push_single_wechat_message.delay") as delay_mock:
                processor = wechatOutboxProcessor()
                result = await processor.scan_and_dispatch()
                assert result == 1
                delay_mock.assert_called_once_with(ready_record.id)


# ---- wechatOutboxProcessor.push_one tests ----


@pytest.mark.asyncio
async def test_processor_push_one_disabled(mock_wechat_conf):
    mock_wechat_conf.enabled = False
    with patch("bisheng.worker.message.outbox_processor.settings") as m:
        m.get_shougang_wechat_message_push_conf.return_value = mock_wechat_conf
        processor = wechatOutboxProcessor()
        result = await processor.push_one(1)
        assert result is False


@pytest.mark.asyncio
async def test_processor_push_one_record_not_found(async_db_session, mock_wechat_conf):
    with patch("bisheng.worker.message.outbox_processor.settings") as m:
        m.get_shougang_wechat_message_push_conf.return_value = mock_wechat_conf
        with patch(
            "bisheng.worker.message.outbox_processor.get_async_db_session",
            return_value=async_db_session,
        ):
            processor = wechatOutboxProcessor()
            result = await processor.push_one(999999)
            assert result is False


@pytest.mark.asyncio
async def test_processor_push_one_non_pending_status(async_db_session, mock_wechat_conf, pending_record_factory):
    record = await pending_record_factory()
    repo = MessagePushOutboxRepositoryImpl(async_db_session)
    await repo.mark_sent(record.id, datetime.now())

    with patch("bisheng.worker.message.outbox_processor.settings") as m:
        m.get_shougang_wechat_message_push_conf.return_value = mock_wechat_conf
        with patch(
            "bisheng.worker.message.outbox_processor.get_async_db_session",
            return_value=async_db_session,
        ):
            processor = wechatOutboxProcessor()
            result = await processor.push_one(record.id)
            assert result is False


@pytest.mark.asyncio
async def test_processor_push_one_success(async_db_session, mock_wechat_conf, pending_record_factory):
    record = await pending_record_factory()

    with patch("bisheng.worker.message.outbox_processor.settings") as m:
        m.get_shougang_wechat_message_push_conf.return_value = mock_wechat_conf
        with patch(
            "bisheng.worker.message.outbox_processor.get_async_db_session",
            return_value=async_db_session,
        ):
            with patch("bisheng.worker.message.outbox_processor.ShougangMADPClient") as client_cls:
                client = MagicMock()
                client.push_text_message = AsyncMock(return_value=(True, None))
                client_cls.return_value = client

                processor = wechatOutboxProcessor()
                result = await processor.push_one(record.id)
                assert result is True

                client.push_text_message.assert_awaited_once()
                call_kwargs = client.push_text_message.call_args.kwargs
                assert call_kwargs["outbox_id"] == record.id
                assert call_kwargs["user_ids"] == ["wx001"]
                assert call_kwargs["body"] == "test body"

                repo = MessagePushOutboxRepositoryImpl(async_db_session)
                updated = await repo.find_by_id(record.id)
                assert updated.status == MessagePushOutboxStatus.SENT
                assert updated.sent_at is not None
                assert updated.failure_reason is None


@pytest.mark.asyncio
async def test_processor_push_one_retry_then_fail(async_db_session, mock_wechat_conf, pending_record_factory):
    record = await pending_record_factory()
    mock_wechat_conf.max_retries = 1

    with patch("bisheng.worker.message.outbox_processor.settings") as m:
        m.get_shougang_wechat_message_push_conf.return_value = mock_wechat_conf
        with patch(
            "bisheng.worker.message.outbox_processor.get_async_db_session",
            return_value=async_db_session,
        ):
            with patch("bisheng.worker.message.outbox_processor.ShougangMADPClient") as client_cls:
                client = MagicMock()
                client.push_text_message = AsyncMock(return_value=(False, "timeout"))
                client_cls.return_value = client

                processor = wechatOutboxProcessor()
                result = await processor.push_one(record.id)
                assert result is True

                repo = MessagePushOutboxRepositoryImpl(async_db_session)
                updated = await repo.find_by_id(record.id)
                assert updated.status == MessagePushOutboxStatus.FAILED
                assert updated.retry_count == 1
                assert updated.failure_reason == "timeout"


@pytest.mark.asyncio
async def test_processor_push_one_pending_retry(async_db_session, mock_wechat_conf, pending_record_factory):
    record = await pending_record_factory()
    mock_wechat_conf.max_retries = 3

    with patch("bisheng.worker.message.outbox_processor.settings") as m:
        m.get_shougang_wechat_message_push_conf.return_value = mock_wechat_conf
        with patch(
            "bisheng.worker.message.outbox_processor.get_async_db_session",
            return_value=async_db_session,
        ):
            with patch("bisheng.worker.message.outbox_processor.ShougangMADPClient") as client_cls:
                client = MagicMock()
                client.push_text_message = AsyncMock(return_value=(False, "http_status_500"))
                client_cls.return_value = client

                processor = wechatOutboxProcessor()
                result = await processor.push_one(record.id)
                assert result is False

                repo = MessagePushOutboxRepositoryImpl(async_db_session)
                updated = await repo.find_by_id(record.id)
                assert updated.status == MessagePushOutboxStatus.PENDING
                assert updated.retry_count == 1
                assert updated.failure_reason == "http_status_500"
                assert updated.next_retry_at is not None


# ---- Celery task wrapper tests ----


@pytest.fixture
def mock_redis_lock():
    redis = MagicMock()
    redis.setNx.return_value = True
    redis.delete.return_value = True
    return redis


def test_scan_task_releases_lock_on_success(mock_redis_lock):
    with patch("bisheng.worker.message.tasks._get_redis", return_value=mock_redis_lock):
        with patch("bisheng.worker.message.tasks.run_async_task", return_value=5):
            result = scan_wechat_message_push_outbox()
            assert result == 5
            mock_redis_lock.setNx.assert_called_once()
            mock_redis_lock.delete.assert_called_once()


def test_scan_task_releases_lock_on_exception(mock_redis_lock):
    with patch("bisheng.worker.message.tasks._get_redis", return_value=mock_redis_lock):
        with patch("bisheng.worker.message.tasks.run_async_task", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                scan_wechat_message_push_outbox()
            mock_redis_lock.delete.assert_called_once()


def test_scan_task_skips_when_lock_held(mock_redis_lock):
    mock_redis_lock.setNx.return_value = False
    with patch("bisheng.worker.message.tasks._get_redis", return_value=mock_redis_lock):
        with patch("bisheng.worker.message.tasks.run_async_task") as run_mock:
            result = scan_wechat_message_push_outbox()
            assert result == 0
            run_mock.assert_not_called()
            mock_redis_lock.delete.assert_not_called()


def test_scan_task_runs_without_redis():
    with patch("bisheng.worker.message.tasks._get_redis", return_value=None):
        with patch("bisheng.worker.message.tasks.run_async_task", return_value=3):
            result = scan_wechat_message_push_outbox()
            assert result == 3


def test_push_single_task_delegates_to_processor():
    with patch("bisheng.worker.message.tasks.run_async_task", return_value=True) as run_mock:
        result = push_single_wechat_message(42)
        assert result is True
        run_mock.assert_called_once()
