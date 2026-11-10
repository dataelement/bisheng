"""AC-T01 through AC-T09: isolated real HTTP/SQL, synthetic authentication/model."""

from contextlib import contextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select

from bisheng.dsh.api.endpoints.model_audit_title import router, title_service
from bisheng.dsh.domain.models.model_audit_title import DshModelAuditConversationTitle as Title
from bisheng.dsh.domain.repositories.model_audit_queries import DshModelAuditQueryRepository as Query
from bisheng.dsh.domain.repositories.model_audit_title import DshModelAuditTitleRepository
from bisheng.dsh.domain.schemas.model_audit import AuditModeCommand
from bisheng.dsh.domain.services.model_audit_title import DshModelAuditTitleService
from test.dsh.test_model_audit_flow import ADMIN, BASE, USER, call, fixture
from test.dsh.test_model_audit_tree import finish

PATH = "/api/v1/dsh/audit/conversations/title"
UPDATE = {"conversation_id": "e2e-title-main", "title": "e2e-title-first", "title_event_seq": 12}


async def test_title_storage_failure_is_generic_and_independent():
    """AC-T06: the title endpoint fails safely without changing the model call lifecycle."""
    async with fixture("METADATA") as (harness, client, _objects):
        service = install(harness)

        @contextmanager
        def unavailable():
            raise SQLAlchemyError("synthetic sensitive SQL parameter")
            yield

        service.repository_scope = unavailable
        response = await client.post(PATH, headers=USER, json=UPDATE)
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "internal_error"
        assert "sensitive" not in response.text and UPDATE["title"] not in response.text
        assert response.headers["cache-control"] == "no-store"
        assert harness.calls == 0


def install(harness):
    service = DshModelAuditTitleService(harness.modes, lambda: harness.scope(DshModelAuditTitleRepository))
    harness.app.include_router(router, prefix="/api/v1")
    harness.app.dependency_overrides[title_service] = lambda: service
    return service


async def test_title_before_audit_then_rename_without_another_model_call():
    """AC-T01, AC-T02, AC-T03, AC-T06, AC-T08: idempotent ordered updates and batch reads."""
    async with fixture("METADATA") as (harness, client, _objects):
        install(harness)
        assert (await client.post(PATH, headers=USER, json=UPDATE)).json() == {"status": "NOT_READY"}
        await call(client, audit_context={"conversation_id": UPDATE["conversation_id"]})
        await harness.drain()
        for change, expected in [
            ({}, "UPDATED"),
            ({}, "UNCHANGED"),
            ({"title_event_seq": 11}, "STALE"),
            ({"title": "conflict"}, "CONFLICT"),
            ({"title_event_seq": 13, "title": "<script>e2e-title-rename</script>"}, "UPDATED"),
        ]:
            response = await client.post(PATH, headers=USER, json={**UPDATE, **change})
            assert response.status_code == 200
            assert response.json()["status"] == expected
            assert response.headers["cache-control"] == "no-store"
        assert harness.calls == 1
        with harness.scope(Query) as repository:
            finish(repository)
        page = (await client.get(BASE + "/conversation-tree", headers=ADMIN)).json()
        assert page["status_code"] == 200
        with harness.scope(Query) as repository:
            statements = []
            event.listen(
                harness.engine, "before_cursor_execute", lambda _c, _s, sql, _p, _ctx, _many: statements.append(sql)
            )
            roots = repository.tree_page()
            item = roots["items"][0]
            assert item["conversation_title"] == "<script>e2e-title-rename</script>"
            assert item["title_event_seq"] == 13
            assert sum("FROM dsh_model_audit_conversation_title" in sql for sql in statements) == 1
            assert (
                repository.tree_location(item["conversation_key"])["items"][0]["conversation_title"]
                == item["conversation_title"]
            )
            assert repository.group_page()["items"][0]["conversation_title"] == item["conversation_title"]


async def test_authentication_scope_and_mode_fail_closed_for_titles():
    """AC-T04, AC-T05: title never creates a fake audit or crosses user/tenant scope."""
    async with fixture() as (harness, client, _objects):
        service = install(harness)
        await harness.modes.change_admin(
            1, 3, AuditModeCommand(operation_id="e2e-title-other", expected_version=0, mode="METADATA")
        )
        await call(client, audit_context={"conversation_id": UPDATE["conversation_id"]})
        await harness.drain()
        assert (await client.post(PATH, json=UPDATE)).status_code == 401
        for token in ("fixture-other", "fixture-user-two"):
            harness.tokens["fixture-user-two"] = 21
            response = await client.post(PATH, headers={"Authorization": "Bearer " + token}, json=UPDATE)
            assert response.json() == {"status": "NOT_READY"}
        assert (await client.post(PATH, headers=USER, json={**UPDATE, "user_id": 21})).status_code == 400
        assert (await client.post(PATH, headers=USER, json=UPDATE)).json()["status"] == "UPDATED"
        await harness.modes.change_admin(
            1, 2, AuditModeCommand(operation_id="e2e-title-off", expected_version=1, mode="OFF")
        )
        assert (await client.post(PATH, headers=USER, json={**UPDATE, "title_event_seq": 100})).json() == {
            "status": "DISABLED"
        }
        service.modes.read_snapshot = AsyncMock(side_effect=TimeoutError("synthetic"))
        assert (await client.post(PATH, headers=USER, json=UPDATE)).json() == {"status": "DISABLED"}
        with harness.scope(Query) as repository:
            saved = repository.session.exec(select(Title)).one()
            assert saved.title == UPDATE["title"] and saved.title_event_seq == 12


@pytest.mark.parametrize(
    "change",
    [
        {"title": " "},
        {"title": "x" * 513},
        {"title": "x\n"},
        {"title": "\ud800"},
        {"title_event_seq": True},
        {"title_event_seq": -1},
        {"title_event_seq": 9007199254740992},
        {"conversation_id": "x" * 257},
        {"conversation_id": ""},
        {"title": None},
        {"title_event_seq": 1.5},
    ],
)
async def test_invalid_title_does_not_touch_model(change):
    """AC-T09: fixed input errors, including Unicode and safe-integer bounds."""
    import json

    async with fixture() as (harness, client, _objects):
        install(harness)
        response = await client.post(
            PATH, headers={**USER, "content-type": "application/json"}, content=json.dumps({**UPDATE, **change})
        )
        assert response.status_code == 400 and response.json()["error"]["code"] == "invalid_request"
        assert harness.calls == 0


async def test_body_stream_limit():
    """AC-T09: reject an oversized streamed request before persisting any text."""
    async with fixture() as (harness, client, _objects):
        install(harness)

        async def chunks():
            for _ in range(10):
                yield b" " * 1024

        response = await client.post(PATH, headers={**USER, "content-type": "application/json"}, content=chunks())
        assert response.status_code == 400 and response.json()["error"]["code"] == "invalid_request"
