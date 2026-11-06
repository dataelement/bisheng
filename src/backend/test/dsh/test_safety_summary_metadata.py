"""Safety-only labels/titles without originals: real ASGI/SQL, synthetic identity/catalog.

Coverage AC: AC-60, AC-67, AC-T04, AC-T05.
SQLite verifies behavior, not MySQL/DM8 deployment or concurrency.
"""

import asyncio
from hashlib import sha256
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlmodel import Session, select

from bisheng.dsh.domain.models.model_audit_content import DshModelAuditContent, DshModelAuditOccurrence
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditManifest
from bisheng.dsh.domain.models.model_audit_request import DshModelAuditRequest as Request
from bisheng.dsh.domain.models.model_audit_title import DshModelAuditConversationTitle as Title
from bisheng.dsh.domain.repositories.model_audit_queries import DshModelAuditQueryRepository as Query
from bisheng.dsh.domain.services.content_safety_ingest import ContentSafetyIngestService, VerifiedSource
from test.dsh.content_safety_fixtures import SafetyIdentity
from test.dsh.test_model_audit_flow import ADMIN, BASE, USER, call, fixture
from test.dsh.test_model_audit_title import PATH, UPDATE, install


async def ingest(harness, factory, *, reader=None, **changes):
    raw = factory(
        identity=SafetyIdentity(2, 20, 42), conversation={"conversation_id": UPDATE["conversation_id"]}, **changes
    )
    service = ContentSafetyIngestService(lambda: Session(harness.engine), model_name_reader=reader)
    return await service.ingest(raw, VerifiedSource(raw["source_id"], 2))


def assert_no_originals(harness, objects):
    assert objects.data == {}
    with harness.scope(Query) as repo:
        for model in (DshModelAuditContent, DshModelAuditOccurrence, DshModelAuditManifest):
            assert repo.session.exec(select(model)).all() == []


@pytest.mark.parametrize("forwarded", [False, True])
async def test_safety_only_keeps_name_title_without_bodies(content_safety_event, forwarded):
    async with fixture("OFF") as (harness, client, objects):
        install(harness)
        assert (await client.post(PATH, headers=USER, json=UPDATE)).json() == {"status": "NOT_READY"}
        changes = {}
        if forwarded:
            request_id = str(uuid4())
            changes = {
                "forwarded": True,
                "backend_request_id": request_id,
                "gateway_request_id": request_id,
                "stage_results": {"input": "PASSED", "output": "PASSED"},
                "hit_count": 0,
                "rule_refs": [],
            }
            assert (await call(client, audit_context={"conversation_id": UPDATE["conversation_id"]})).status_code == 200
            await harness.drain()
        receipt = await ingest(
            harness, content_safety_event, reader=AsyncMock(return_value="Synthetic / safety-only-model"), **changes
        )
        assert (await client.post(PATH, headers=USER, json=UPDATE)).json() == {
            "status": "UPDATED",
            "title_event_seq": 12,
        }
        assert (await client.post(PATH, headers=USER, json=UPDATE)).json()["status"] == "UNCHANGED"
        assert (await client.post(PATH, headers=USER, json={**UPDATE, "title_event_seq": 11})).json()[
            "status"
        ] == "STALE"
        detail = (await client.get(BASE + "/requests/" + receipt.audit_request_id, headers=ADMIN)).json()["data"]
        assert detail["model_name"] == "Synthetic / safety-only-model"
        assert detail["record_origin"] == "EXTERNAL_SAFETY" and detail["effective_mode"] is None
        assert detail["content_status"] == "NOT_CAPTURED"
        with harness.scope(Query) as repo:
            row = repo.session.exec(select(Request)).one()
            assert row.model_name_digest == sha256(detail["model_name"].encode()).hexdigest()
            assert repo.session.exec(select(Title)).one().title == UPDATE["title"]
            enriched = repo.with_titles(
                [
                    {
                        "conversation_key": row.conversation_key,
                        "conversation_id": row.conversation_id,
                        "user_id": row.user_id,
                    }
                ]
            )
            assert enriched[0]["conversation_title"] == UPDATE["title"]
        assert_no_originals(harness, objects)
        assert harness.calls == int(forwarded)


async def test_both_off_does_not_create_summary_or_title():
    async with fixture("OFF") as (harness, client, objects):
        install(harness)
        await call(client, audit_context={"conversation_id": UPDATE["conversation_id"]})
        await harness.drain()
        assert (await client.post(PATH, headers=USER, json=UPDATE)).json() == {"status": "NOT_READY"}
        with harness.scope(Query) as repo:
            assert repo.session.exec(select(Request)).all() == []
            assert repo.session.exec(select(Title)).all() == []
        assert_no_originals(harness, objects)


async def test_safety_title_scoped_and_mode_failure_closed(content_safety_event):
    async with fixture("OFF") as (harness, client, objects):
        titles = install(harness)
        await ingest(harness, content_safety_event, reader=AsyncMock(return_value="Synthetic / model"))
        harness.tokens["fixture-user-two"] = 21
        for token in ("fixture-other", "fixture-user-two"):
            response = await client.post(PATH, headers={"Authorization": "Bearer " + token}, json=UPDATE)
            assert response.json() == {"status": "NOT_READY"}
        assert (await client.post(PATH, json=UPDATE)).status_code == 401
        titles.modes.read_snapshot = AsyncMock(side_effect=TimeoutError("synthetic"))
        assert (await client.post(PATH, headers=USER, json=UPDATE)).json() == {"status": "DISABLED"}
        with harness.scope(Query) as repo:
            assert repo.session.exec(select(Title)).all() == []
        assert_no_originals(harness, objects)


@pytest.mark.parametrize("failure", ["error", "timeout", "invalid"])
async def test_label_failure_does_not_lose_safety_fact(content_safety_event, failure):
    async def reader(_model_id):
        if failure == "timeout":
            await asyncio.sleep(10)
        if failure == "invalid":
            return "x" * 2049
        raise RuntimeError("synthetic catalog unavailable")

    async with fixture("OFF") as (harness, _client, objects):
        async with asyncio.timeout(1):
            receipt = await ingest(harness, content_safety_event, reader=reader)
        assert receipt.receipt == "COMMITTED"
        with harness.scope(Query) as repo:
            row = repo.session.exec(select(Request)).one()
            assert row.model_name == "" and row.has_sensitive_hit
        assert_no_originals(harness, objects)


async def test_later_callback_fills_missing_label_without_renaming_snapshot(content_safety_event):
    async with fixture("OFF") as (harness, _client, objects):
        raw = content_safety_event(identity=SafetyIdentity(2, 20, 42))
        reader = AsyncMock(side_effect=[RuntimeError("synthetic"), "Synthetic / original", "Synthetic / renamed"])
        service = ContentSafetyIngestService(lambda: Session(harness.engine), model_name_reader=reader)
        for attempt in range(3):
            receipt = await service.ingest(raw, VerifiedSource(raw["source_id"], 2))
            assert receipt.duplicate is (attempt > 0)
        with harness.scope(Query) as repo:
            row = repo.session.exec(select(Request)).one()
            assert row.model_name == "Synthetic / original"
            assert row.model_name_digest == sha256(row.model_name.encode()).hexdigest()
        assert_no_originals(harness, objects)


async def test_production_name_reader_reuses_governed_metadata_and_tenant_scope(monkeypatch):
    from types import SimpleNamespace

    from bisheng.core.context.tenant import get_current_tenant_id
    from bisheng.dsh.content_safety_runtime import get_content_safety_service
    from bisheng.dsh.domain.services.profile import profile_scope
    from bisheng.llm.domain.services.llm import LLMService

    async def metadata(model_id):
        assert get_current_tenant_id() == 202 and model_id == 42
        return SimpleNamespace(model_name="synthetic-model", name="fallback"), SimpleNamespace(
            name="Synthetic", type="openai"
        )

    loader = AsyncMock(side_effect=metadata)
    monkeypatch.setattr(LLMService, "get_dsh_model_metadata_snapshot", loader)
    service = get_content_safety_service(session_factory=lambda: None)
    with profile_scope(202):
        assert await service.model_name_reader(42) == "Synthetic / synthetic-model"
    loader.assert_awaited_once_with(42)


async def test_disabled_safety_states_do_not_authorize_titles(content_safety_event):
    async with fixture("OFF") as (harness, client, objects):
        install(harness)
        request_id = str(uuid4())
        await ingest(
            harness,
            content_safety_event,
            reader=AsyncMock(return_value="Synthetic / model"),
            gateway_request_id=request_id,
            backend_request_id=request_id,
            forwarded=True,
            event_kind="FINAL",
            stage_results={"input": "DISABLED", "output": "DISABLED"},
            hit_count=0,
            rule_refs=[],
        )
        assert (await client.post(PATH, headers=USER, json=UPDATE)).json() == {"status": "DISABLED"}
        with harness.scope(Query) as repo:
            assert repo.session.exec(select(Title)).all() == []
        assert_no_originals(harness, objects)


async def test_safety_label_never_overwrites_native_audit_name(content_safety_event):
    async with fixture("METADATA") as (harness, client, objects):
        response = await call(client, audit_context={"conversation_id": UPDATE["conversation_id"]})
        await harness.drain()
        request_id = response.headers["x-request-id"]
        with harness.scope(Query) as repo:
            original = repo.session.exec(select(Request)).one().model_name
            manifests_before = [item.model_dump() for item in repo.session.exec(select(DshModelAuditManifest)).all()]
        await ingest(
            harness,
            content_safety_event,
            reader=AsyncMock(return_value="Synthetic / later-name"),
            gateway_request_id=request_id,
            backend_request_id=request_id,
            forwarded=True,
            stage_results={"input": "PASSED", "output": "PASSED"},
            hit_count=0,
            rule_refs=[],
        )
        with harness.scope(Query) as repo:
            row = repo.session.exec(select(Request)).one()
            assert row.record_origin == "MODEL" and row.model_name == original
            assert [
                item.model_dump() for item in repo.session.exec(select(DshModelAuditManifest)).all()
            ] == manifests_before
            for model in (DshModelAuditContent, DshModelAuditOccurrence):
                assert repo.session.exec(select(model)).all() == []
        assert objects.data == {}
