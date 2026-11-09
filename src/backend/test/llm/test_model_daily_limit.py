"""Provider daily call limits must expire at midnight, not after Redis' default hour."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from bisheng.llm.domain import utils as llm_utils
from bisheng.llm.domain.utils import LlmProviderDailyLimitExceededError


class FakeRedis:
    """Counts calls and records the TTL requested for each one."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int | None]] = []
        self.count = 0

    async def aincr(self, key: str, expiration: int | None = None) -> int:
        self.calls.append((key, expiration))
        self.count += 1
        return self.count

    def incr(self, key: str, expiration: int | None = None) -> int:
        self.calls.append((key, expiration))
        self.count += 1
        return self.count


def _model(limit: int = 2) -> SimpleNamespace:
    return SimpleNamespace(
        server_info=SimpleNamespace(limit_flag=True, id=7, name='provider', limit=limit),
        model_info=SimpleNamespace(model_name='model'),
    )


def test_seconds_until_day_end_matches_midnight() -> None:
    now = datetime.now()
    midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())

    seconds = llm_utils._seconds_until_day_end(now)

    assert 1 <= seconds <= 86400
    assert abs(seconds - (midnight - now).total_seconds()) <= 1


@pytest.mark.asyncio
async def test_async_counter_lives_until_midnight(monkeypatch) -> None:
    fake = FakeRedis()

    async def get_client() -> FakeRedis:
        return fake

    monkeypatch.setattr(llm_utils, 'get_redis_client', get_client)
    await llm_utils.bisheng_model_limit_check(_model())

    key, expiration = fake.calls[0]
    assert key == f'model_limit:{datetime.now():%Y-%m-%d}:7'
    assert expiration == llm_utils._seconds_until_day_end()


@pytest.mark.asyncio
async def test_async_counter_rejects_requests_over_the_limit(monkeypatch) -> None:
    fake = FakeRedis()

    async def get_client() -> FakeRedis:
        return fake

    monkeypatch.setattr(llm_utils, 'get_redis_client', get_client)
    model = _model(limit=2)
    await llm_utils.bisheng_model_limit_check(model)
    await llm_utils.bisheng_model_limit_check(model)

    with pytest.raises(LlmProviderDailyLimitExceededError):
        await llm_utils.bisheng_model_limit_check(model)

    assert fake.count == 3
    assert all(expiration for _, expiration in fake.calls)


def test_sync_counter_lives_until_midnight(monkeypatch) -> None:
    fake = FakeRedis()
    monkeypatch.setattr(llm_utils, 'get_redis_client_sync', lambda: fake)

    llm_utils.sync_bisheng_model_limit_check(_model())

    key, expiration = fake.calls[0]
    assert key == f'model_limit:{datetime.now():%Y-%m-%d}:7'
    assert expiration == llm_utils._seconds_until_day_end()
