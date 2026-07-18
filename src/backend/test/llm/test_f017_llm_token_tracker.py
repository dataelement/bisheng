"""F017 unit tests — LLMTokenTracker + ModelCallLogger (T16/T17).

Both services obey INV-T13: tenant_id = user leaf (ContextVar), raising
19504 when unset. Mock DAO.acreate to avoid hitting MySQL.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.tenant_sharing import TenantContextMissingError
from bisheng.core.context.tenant import current_tenant_id
from bisheng.llm.domain.services.call_logger import ModelCallLogger
from bisheng.llm.domain.services.token_tracker import LLMTokenTracker


# ── LLMTokenTracker ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_usage_stamps_leaf_tenant_and_sums_total():
    captured = {}

    async def _fake_acreate(log):
        captured['log'] = log
        return log

    token = current_tenant_id.set(5)
    try:
        with patch(
            'bisheng.llm.domain.services.token_tracker.LLMTokenLogDao.acreate',
            side_effect=_fake_acreate,
        ):
            await LLMTokenTracker.record_usage(
                user_id=100, prompt_tokens=30, completion_tokens=12,
                model_id=7, server_id=3, session_id='sess-x',
            )
    finally:
        current_tenant_id.reset(token)

    log = captured['log']
    assert log.tenant_id == 5
    assert log.user_id == 100
    assert log.prompt_tokens == 30
    assert log.completion_tokens == 12
    assert log.total_tokens == 42  # sum when not supplied
    assert log.model_id == 7
    assert log.session_id == 'sess-x'


@pytest.mark.asyncio
async def test_record_usage_raises_on_missing_context():
    with pytest.raises(TenantContextMissingError):
        await LLMTokenTracker.record_usage(
            user_id=100, prompt_tokens=1, completion_tokens=1,
        )


@pytest.mark.asyncio
async def test_record_usage_accepts_explicit_total_override():
    captured = {}

    async def _fake_acreate(log):
        captured['log'] = log
        return log

    token = current_tenant_id.set(5)
    try:
        with patch(
            'bisheng.llm.domain.services.token_tracker.LLMTokenLogDao.acreate',
            side_effect=_fake_acreate,
        ):
            await LLMTokenTracker.record_usage(
                user_id=1, prompt_tokens=10, completion_tokens=5, total_tokens=99,
            )
    finally:
        current_tenant_id.reset(token)

    # When caller supplies total_tokens we trust it (OpenAI returns it
    # explicitly and may disagree with prompt+completion for non-text).
    assert captured['log'].total_tokens == 99


# ── ModelCallLogger ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_log_success_stamps_leaf_tenant():
    captured = {}

    async def _fake_acreate(log):
        captured['log'] = log
        return log

    token = current_tenant_id.set(5)
    try:
        with patch(
            'bisheng.llm.domain.services.call_logger.LLMCallLogDao.acreate',
            side_effect=_fake_acreate,
        ):
            await ModelCallLogger.log_success(
                user_id=100, model_id=7, server_id=3,
                endpoint='https://api.openai.com/v1/chat/completions',
                latency_ms=340,
            )
    finally:
        current_tenant_id.reset(token)

    log = captured['log']
    assert log.tenant_id == 5
    assert log.status == 'success'
    assert log.latency_ms == 340
    assert log.error_msg is None


@pytest.mark.asyncio
async def test_log_error_truncates_long_messages():
    captured = {}

    async def _fake_acreate(log):
        captured['log'] = log
        return log

    long_err = 'x' * 2000

    token = current_tenant_id.set(5)
    try:
        with patch(
            'bisheng.llm.domain.services.call_logger.LLMCallLogDao.acreate',
            side_effect=_fake_acreate,
        ):
            await ModelCallLogger.log_error(user_id=100, error_msg=long_err)
    finally:
        current_tenant_id.reset(token)

    assert captured['log'].status == 'error'
    assert captured['log'].error_msg == 'x' * 500
    assert len(captured['log'].error_msg) == 500


@pytest.mark.asyncio
async def test_log_raises_on_missing_context():
    with pytest.raises(TenantContextMissingError):
        await ModelCallLogger.log_success(user_id=100)
