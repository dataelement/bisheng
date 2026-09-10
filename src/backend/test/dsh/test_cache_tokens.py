"""Cache detail survives JSON/SSE and SQL projection without changing quota totals."""

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlmodel import Session

from bisheng.dsh.domain.models.model_call import DshModelCall
from bisheng.dsh.domain.models.monthly_usage import DshMonthlyUsage
from bisheng.dsh.domain.repositories.usage import DshUsageRepository
from bisheng.dsh.domain.schemas.chat import DshChatRequest
from bisheng.dsh.domain.schemas.usage import UsageEvent
from bisheng.dsh.infrastructure.chat_adapter import normalize_usage
from test.dsh.test_model_service import principal, service_setup  # noqa: F401
from test.dsh.test_quota_admission import quota as real_quota  # noqa: F401
from test.dsh.test_quota_admission import running
from test.dsh.test_usage_repository import event, usage_db  # noqa: F401


@pytest.mark.parametrize(
    "raw",
    [
        {"prompt_tokens_details": {"cached_tokens": 8, "cache_creation_tokens": 1}},
        {"cache_read_input_tokens": 8, "cache_creation_input_tokens": 1},
        {"prompt_cache_hit_tokens": 8, "cache_creation_input_tokens": 1},
    ],
)
def test_raw_provider_cache_details(raw):
    message = SimpleNamespace(
        usage_metadata=None,
        response_metadata={
            "token_usage": {
                "prompt_tokens": 10,
                "completion_tokens": 2,
                "total_tokens": 12,
                **raw,
            }
        },
    )
    usage = normalize_usage(message)
    assert (usage.cache_read_tokens, usage.cache_creation_tokens, usage.total_tokens) == (8, 1, 12)


@pytest.mark.parametrize("value,expected", [(0, 0), (None, None), (-1, None), (True, None), ("8", None), (2**63, None)])
def test_missing_and_invalid_cache_details_do_not_invalidate_total(value, expected):
    message = SimpleNamespace(
        usage_metadata={
            "input_tokens": 10,
            "output_tokens": 2,
            "total_tokens": 12,
            "input_token_details": {"cache_read": value},
        },
        response_metadata={},
    )
    usage = normalize_usage(message)
    assert usage.total_tokens == 12
    assert usage.cache_read_tokens == expected
    assert usage.cache_creation_tokens is None


def test_normalized_cache_zero_takes_precedence_over_raw_value():
    usage = normalize_usage(
        SimpleNamespace(
            usage_metadata={
                "input_tokens": 10,
                "output_tokens": 2,
                "total_tokens": 12,
                "input_token_details": {"cache_read": 0, "cache_creation": 1},
            },
            response_metadata={"token_usage": {"prompt_tokens_details": {"cached_tokens": 8}}},
        )
    )
    assert (usage.cache_read_tokens, usage.cache_creation_tokens) == (0, 1)


@pytest.mark.parametrize("stream", [False, True])
async def test_response_and_settlement_keep_cache_details(service_setup, stream):  # noqa: F811
    service, llm, ledger, _, _ = service_setup
    llm.measured = lambda: {
        "input_tokens": 10,
        "output_tokens": 2,
        "total_tokens": 12,
        "input_token_details": {"cache_read": 8, "cache_creation": 1},
    }
    llm.continue_stream.set()
    request = DshChatRequest(
        model="bisheng:42",
        messages=[{"role": "user", "content": "test"}],
        stream=stream,
        stream_options={"include_usage": True} if stream else None,
    )
    result = await service.complete(principal(), request)
    if stream:
        chunks = [chunk async for chunk in result]
        assert chunks[-1] == "data: [DONE]\n\n"
        objects = [json.loads(chunk[6:]) for chunk in chunks if chunk.startswith("data: {")]
        result = next(obj for obj in objects if "usage" in obj)
    assert result["usage"]["prompt_tokens_details"] == {"cached_tokens": 8, "cache_creation_tokens": 1}
    assert result["usage"]["total_tokens"] == 12
    restored = UsageEvent.model_validate_json(ledger.events[-1].model_dump_json())
    assert (restored.cache_read_tokens, restored.cache_creation_tokens) == (8, 1)
    assert ledger.used == 102


def test_cache_detail_persisted_and_idempotent_without_double_counting(usage_db):  # noqa: F811
    settled = event(
        status="SUCCEEDED",
        input_tokens=10,
        output_tokens=2,
        total_tokens=12,
        cache_read_tokens=8,
        cache_creation_tokens=1,
        usage_source="PROVIDER",
    )
    with Session(usage_db) as session, session.begin():
        repo = DshUsageRepository(session)
        assert repo.project_batch([settled]) == 1
        assert repo.project_batch([settled]) == 0
        row = session.get(DshModelCall, settled.request_id)
        assert (row.cache_read_tokens, row.cache_creation_tokens) == (8, 1)
        assert next(iter(session.scalars(select(DshMonthlyUsage)))).used_tokens == 12
        with pytest.raises(ValueError, match="Conflicting persisted"):
            repo.project_batch([settled.model_copy(update={"cache_read_tokens": 7})])


def test_legacy_event_missing_cache_fields_stays_unknown(usage_db):  # noqa: F811
    payload = event(
        status="SUCCEEDED", input_tokens=10, output_tokens=2, total_tokens=12, usage_source="PROVIDER"
    ).model_dump(exclude={"cache_read_tokens", "cache_creation_tokens"})
    legacy = UsageEvent.model_validate(payload)
    with Session(usage_db) as session, session.begin():
        DshUsageRepository(session).project_batch([legacy])
        row = session.get(DshModelCall, legacy.request_id)
        assert row.cache_read_tokens is None and row.cache_creation_tokens is None


async def test_real_redis_stream_projects_cache_details_to_sql(real_quota, usage_db):  # noqa: F811
    initial = running()
    await real_quota.check_and_start(initial)
    terminal = UsageEvent.model_validate(
        {
            **initial.model_dump(),
            "status": "SUCCEEDED",
            "event_version": 2,
            "input_tokens": 10,
            "output_tokens": 2,
            "total_tokens": 12,
            "cache_read_tokens": 8,
            "cache_creation_tokens": 1,
            "usage_source": "PROVIDER",
        }
    )
    await real_quota.record_usage(terminal, 1)
    entries = await real_quota.redis.xrange(real_quota.keys(initial)[5])
    events = [UsageEvent.model_validate_json(fields["event"]) for _, fields in entries]
    with Session(usage_db) as session, session.begin():
        repository = DshUsageRepository(session)
        repository.project_batch(events)
        repository.project_batch(events)
        row = session.get(DshModelCall, initial.request_id)
        assert (row.cache_read_tokens, row.cache_creation_tokens, row.total_tokens) == (8, 1, 12)
        assert next(iter(session.scalars(select(DshMonthlyUsage)))).used_tokens == 12
