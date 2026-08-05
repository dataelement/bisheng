"""F044: probing a model must write the verdict either way.

Before this feature the probe only wrote to the DB when it failed, so a model
that was once abnormal stayed red forever no matter how many times you checked
it -- which would make the new "update status" button useless (AC-03).

See features/v3.0.0-beta1/044-model-status-manual-verify/design.md §3 decision 3.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.llm.domain.const import LLMModelType
from bisheng.llm.domain.models.llm_server import LLMModel
from bisheng.llm.domain.services.llm import LLMService

STATUS_NORMAL = 0
STATUS_ABNORMAL = 1


def _model(model_type=LLMModelType.LLM.value):
    return LLMModel(id=7, server_id=1, model_name="gpt-x", model_type=model_type)


def _login_user():
    user = MagicMock()
    user.user_id = 1
    return user


@pytest.fixture
def status_writes():
    """Capture (model_id, status, remark) instead of touching a DB."""
    with patch("bisheng.llm.domain.services.llm.LLMDao.update_model_status") as write:
        yield write


class TestProbeWritesStatus:
    async def test_success_marks_model_normal(self, status_writes):
        # AC-03 — the whole point: a recovered model must be able to go green.
        llm = AsyncMock()
        with patch.object(LLMService, "get_bisheng_llm", AsyncMock(return_value=llm)):
            await LLMService.test_model_status(_model(), _login_user())

        status_writes.assert_called_once()
        model_id, status, remark = status_writes.call_args[0]
        assert (model_id, status) == (7, STATUS_NORMAL)
        assert remark == ""  # stale failure reason must be cleared

    async def test_failure_marks_model_abnormal_with_reason(self, status_writes):
        # AC-04 — the reason is what the list tooltip shows.
        with patch.object(LLMService, "get_bisheng_llm", AsyncMock(side_effect=RuntimeError("bad api key"))):
            await LLMService.test_model_status(_model(), _login_user())

        model_id, status, remark = status_writes.call_args[0]
        assert (model_id, status) == (7, STATUS_ABNORMAL)
        assert "bad api key" in remark

    async def test_timeout_marks_model_abnormal(self, status_writes):
        # AC-04 — a model that never answers is unusable in practice, so it
        # must not hang the request either; the probe gives up and says so.
        # The real cap is 30s; shrink it here so the suite stays fast.
        async def never_answers(*args, **kwargs):
            await asyncio.sleep(5)

        llm = AsyncMock()
        llm.ainvoke = never_answers
        with (
            patch("bisheng.llm.domain.services.llm.MODEL_TEST_TIMEOUT", 0.05),
            patch.object(LLMService, "get_bisheng_llm", AsyncMock(return_value=llm)),
        ):
            await LLMService.test_model_status(_model(), _login_user())

        model_id, status, remark = status_writes.call_args[0]
        assert (model_id, status) == (7, STATUS_ABNORMAL)
        assert "timeout" in remark.lower()

    async def test_embedding_success_also_writes_normal(self, status_writes):
        # Every model type shares the write-back, not just chat models.
        embed = AsyncMock()
        with patch.object(LLMService, "get_bisheng_embedding", AsyncMock(return_value=embed)):
            await LLMService.test_model_status(_model(LLMModelType.EMBEDDING.value), _login_user())

        _, status, _ = status_writes.call_args[0]
        assert status == STATUS_NORMAL


class TestVerifyDefeatsTheInfoCache:
    """An on-demand check must not answer from a minute-old snapshot.

    `LLM_CACHE` is a 60s in-process TTL cache with no write-through, and the
    probe resolves the model through it (`get_model_server_info(..., cache=True)`).
    Renaming a model and immediately pressing "check" therefore probed the OLD
    name and reported `model_not_found`; it only started working once the entry
    aged out. Verify evicts the entry first.
    """

    async def test_verify_evicts_the_cached_model_and_server(self):
        from bisheng.llm.domain.const import LLM_CACHE
        from bisheng.llm.domain.utils import _scoped_cache_key

        model = _model()
        model_key = _scoped_cache_key("llm:model:", model.id)
        server_key = _scoped_cache_key("llm:server:", model.server_id)
        LLM_CACHE[model_key] = "row carrying the pre-rename model_name"
        LLM_CACHE[server_key] = "row carrying the pre-rename server config"

        with (
            patch(
                "bisheng.llm.domain.services.llm.LLMDao.aget_model_by_id",
                AsyncMock(return_value=model),
            ),
            patch.object(LLMService, "test_model_status", AsyncMock()),
        ):
            await LLMService.verify_model_status(model.id, _login_user())

        assert LLM_CACHE.get(model_key) is None
        assert LLM_CACHE.get(server_key) is None

    async def test_eviction_happens_before_the_probe_runs(self):
        # Ordering is the whole fix: evicting after the probe would still have
        # let the probe build its client from the stale row.
        from bisheng.llm.domain.const import LLM_CACHE
        from bisheng.llm.domain.utils import _scoped_cache_key

        model = _model()
        model_key = _scoped_cache_key("llm:model:", model.id)
        LLM_CACHE[model_key] = "stale"
        seen = {}

        async def record_cache_state(*args, **kwargs):
            seen["cached_at_probe_time"] = LLM_CACHE.get(model_key)

        with (
            patch(
                "bisheng.llm.domain.services.llm.LLMDao.aget_model_by_id",
                AsyncMock(return_value=model),
            ),
            patch.object(LLMService, "test_model_status", record_cache_state),
        ):
            await LLMService.verify_model_status(model.id, _login_user())

        assert seen["cached_at_probe_time"] is None
