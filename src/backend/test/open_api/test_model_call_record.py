"""F051 T017: the per-call usage record — what lands, what never does.

Two boundaries are asserted here rather than described:

* a call refused **before** model resolution produces an audit row and no usage
  row, while one refused at resolution produces both — that is the line AC-20
  draws, and it is invisible in the code without a test;
* AC-25's "no aggregation, no quota" is a SHALL NOT, which only stays true if
  something fails when someone adds a ``/usage`` endpoint next year.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.config.open_platform import OpenApiConf
from bisheng.open_api.domain.models.model_call_record import ModelCallRecord
from bisheng.open_api.domain.repositories.model_call_record_repository import ModelCallRecordRepository
from bisheng.open_api.domain.services.model_call_record_writer import ModelCallRecordWriter
from test.open_api.model_gateway_fixtures import (
    FakeBishengLLM,
    build_model_face_app,
    capture_records,
    install_catalog,
    install_fake_llm,
    model_row,
    server_row,
    service_account_principal,
)

CHAT_PATH = "/api/v2/model/v1/chat/completions"
MODELS_PATH = "/api/v2/model/v1/models"
BODY = {"model": "gpt-4o", "messages": [{"role": "user", "content": "the quick brown fox"}]}


@pytest.fixture
def records(monkeypatch):
    monkeypatch.setattr(
        "bisheng.open_api.api.dependencies.validate_bearer",
        AsyncMock(return_value=service_account_principal()),
    )
    install_catalog(monkeypatch, [server_row(1, "azure-openai")], [model_row(10, 1, "gpt-4o")])
    return capture_records(monkeypatch)


@pytest.fixture
async def record_db(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(ModelCallRecord.__table__.create)

    @asynccontextmanager
    async def session_factory():
        session = AsyncSession(engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    import bisheng.open_api.domain.repositories.model_call_record_repository as repository_module

    monkeypatch.setattr(repository_module, "get_async_db_session", session_factory)
    yield session_factory
    await engine.dispose()


async def _post(payload: dict):
    app = build_model_face_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(CHAT_PATH, json=payload)


async def test_a_successful_call_records_every_traceable_dimension(monkeypatch, records):
    install_fake_llm(
        monkeypatch,
        FakeBishengLLM(
            invoke_result=AIMessage(
                content="hi",
                usage_metadata={"input_tokens": 9, "output_tokens": 2, "total_tokens": 11},
            )
        ),
    )

    response = await _post(BODY)

    row = records[0]
    assert (row.tenant_id, row.credential_id) == (9, 7)
    assert (row.actor_kind, row.actor_id, row.actor_name) == ("service_account", 31, "local-dev")
    assert row.resource_owner_user_id == 12
    assert row.subject_kind == "service_account"
    assert (row.requested_model, row.model_id, row.model_name) == ("gpt-4o", 10, "gpt-4o")
    assert (row.server_id, row.server_name, row.server_type) == (1, "azure-openai", "openai")
    assert row.result == "success"
    assert row.latency_ms is not None and row.latency_ms >= 0
    assert row.request_id == response.json()["id"]


async def test_a_call_refused_at_model_resolution_still_gets_a_row(monkeypatch, records):
    install_fake_llm(monkeypatch, FakeBishengLLM())

    await _post({**BODY, "model": "never-configured"})

    row = records[0]
    assert row.result == "model_unavailable"
    assert row.error_code == 26211
    assert row.model_id is None
    # The name the caller actually wrote is what makes the row diagnosable.
    assert row.requested_model == "never-configured"


async def test_a_call_refused_before_model_resolution_gets_no_usage_row(monkeypatch):
    from bisheng.common.errcode.open_api import OpenApiScopeMissingError

    monkeypatch.setattr(
        "bisheng.open_api.api.dependencies.validate_bearer",
        AsyncMock(side_effect=OpenApiScopeMissingError(required="model:invoke")),
    )
    rows = capture_records(monkeypatch)

    response = await _post(BODY)

    # Such calls are not lost — the /api/v2 audit middleware writes one
    # ``open_api.call`` row for every request including this one. They simply do
    # not belong in the usage ledger, having consumed nothing.
    assert response.status_code == 403
    assert rows == []


async def test_listing_models_is_not_a_model_call(monkeypatch, records):
    install_fake_llm(monkeypatch, FakeBishengLLM())
    app = build_model_face_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(MODELS_PATH)

    assert response.status_code == 200
    assert records == []


async def test_no_message_body_or_credential_plaintext_reaches_the_row(monkeypatch, records):
    install_fake_llm(monkeypatch, FakeBishengLLM(invoke_result=AIMessage(content="secret answer")))

    await _post(BODY)

    serialized = records[0].model_dump_json()
    assert "the quick brown fox" not in serialized
    assert "secret answer" not in serialized
    assert "bs-sak-" not in serialized
    assert "Authorization" not in serialized


async def test_rows_are_written_in_batches_and_flushed_on_stop(record_db):
    writer = ModelCallRecordWriter(batch_size=10, flush_interval_seconds=0.05)
    writer.enqueue(_row(requested_model="a", credential_mask="bs-sak-********aaaa"))
    writer.enqueue(_row(requested_model="b", credential_mask="bs-sak-********bbbb"))
    writer.start()
    await asyncio.sleep(0.15)
    await writer.stop()

    rows, _cursor = await ModelCallRecordRepository.alist(9)
    assert {row.requested_model for row in rows} == {"a", "b"}


async def test_the_credential_mask_is_hydrated_per_batch_not_per_call(monkeypatch, record_db):
    from types import SimpleNamespace

    import bisheng.open_api.domain.repositories.credential_repository as credential_module

    lookups: list = []

    async def get_by_ids(ids):
        lookups.append(list(ids))
        return [SimpleNamespace(id=7, key_mask="bs-sak-********7777")]

    monkeypatch.setattr(credential_module.CredentialRepository, "get_by_ids", staticmethod(get_by_ids))

    writer = ModelCallRecordWriter(flush_interval_seconds=0.05)
    writer.enqueue(_row(requested_model="a"))
    writer.enqueue(_row(requested_model="b"))
    await writer.flush_now()

    rows, _cursor = await ModelCallRecordRepository.alist(9)
    assert {row.credential_mask for row in rows} == {"bs-sak-********7777"}
    # One query per batch, not one per call: the mask is cosmetic and must not
    # cost the request path a database read.
    assert lookups == [[7]]


def test_a_full_queue_is_reported_rather_than_silently_dropped(monkeypatch):
    import bisheng.open_api.domain.services.model_call_record_writer as writer_module

    emitted: list = []
    monkeypatch.setattr(writer_module, "emit_metric", lambda domain, **fields: emitted.append((domain, fields)))
    writer = ModelCallRecordWriter(max_queue_size=1)

    assert writer.enqueue(_row()) is True
    assert writer.enqueue(_row()) is False

    # Write-behind is best-effort by design, but a lost row that nobody can see
    # is indistinguishable from a call that never happened.
    assert emitted == [("model_call_record", {"status": "dropped", "batch_size": 1})]


async def test_paging_is_stable_when_rows_share_a_second(record_db):
    stamp = datetime(2026, 9, 16, 10, 0, 0)
    rows = [_row(requested_model=f"m{index}", create_time=stamp) for index in range(20)]
    await ModelCallRecordRepository.ainsert_batch(rows)

    first, cursor = await ModelCallRecordRepository.alist(9, limit=10)
    second, _ = await ModelCallRecordRepository.alist(9, limit=10, cursor=cursor)
    whole, _ = await ModelCallRecordRepository.alist(9, limit=100)

    # create_time is second-precision: without the id tiebreaker the page
    # boundary is non-deterministic and rows duplicate across pages.
    assert [row.id for row in first + second] == [row.id for row in whole]
    assert len({row.id for row in first + second}) == 20


async def test_the_three_promised_filters_narrow_the_listing(record_db):
    stamp = datetime(2026, 9, 16, 10, 0, 0)
    await ModelCallRecordRepository.ainsert_batch(
        [
            _row(requested_model="by-key", credential_id=7, create_time=stamp),
            _row(requested_model="other-key", credential_id=8, create_time=stamp),
            _row(requested_model="by-app", credential_id=8, app_id="survey-app", create_time=stamp),
            _row(requested_model="old", credential_id=8, create_time=stamp - timedelta(days=2)),
        ]
    )

    by_key, _ = await ModelCallRecordRepository.alist(9, credential_id=7)
    by_app, _ = await ModelCallRecordRepository.alist(9, app_id="survey-app")
    by_time, _ = await ModelCallRecordRepository.alist(9, time_from=stamp - timedelta(hours=1))

    assert {row.requested_model for row in by_key} == {"by-key"}
    assert {row.requested_model for row in by_app} == {"by-app"}
    assert "old" not in {row.requested_model for row in by_time}


async def test_another_tenants_rows_are_not_listed(record_db):
    await ModelCallRecordRepository.ainsert_batch(
        [_row(tenant_id=9, requested_model="mine"), _row(tenant_id=10, requested_model="theirs")]
    )

    rows, _ = await ModelCallRecordRepository.alist(9)

    assert {row.requested_model for row in rows} == {"mine"}


async def test_export_walks_every_page(record_db):
    await ModelCallRecordRepository.ainsert_batch([_row(requested_model=f"m{index}") for index in range(7)])

    exported = [row.requested_model async for row in ModelCallRecordRepository.aiter_export(9, page_size=3)]

    assert len(exported) == 7
    assert len(set(exported)) == 7


def test_no_aggregation_or_quota_surface_exists():
    from bisheng.open_api.api.endpoints.model_gateway import router

    paths = {route.path for route in router.routes}
    assert paths == {"/model/v1/chat/completions", "/model/v1/models", "/model/v1/{rest:path}"}

    public_methods = {name for name in vars(ModelCallRecordRepository) if not name.startswith("_")}
    # This release meters per call and does nothing else. Leaving that as a
    # sentence in a design document is how a /usage endpoint appears later with
    # nothing turning red.
    assert public_methods == {"ainsert_batch", "alist", "aiter_export"}
    assert not [name for name in OpenApiConf.model_fields if name.endswith(("_limit", "_quota"))]


def _row(**overrides) -> ModelCallRecord:
    payload = {
        "tenant_id": 9,
        "credential_id": 7,
        "actor_kind": "service_account",
        "actor_id": 31,
        "requested_model": "gpt-4o",
        "result": "success",
        "create_time": datetime(2026, 9, 16, 10, 0, 0),
    }
    payload.update(overrides)
    return ModelCallRecord(**payload)
