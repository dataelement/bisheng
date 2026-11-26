"""Desktop message ratings stay on the audit conversation and never enter model history."""

import json
from contextlib import contextmanager

import pytest
from sqlalchemy.exc import SQLAlchemyError

from bisheng.dsh.api.endpoints.model_audit_feedback import feedback_service, router
from bisheng.dsh.domain.models.model_audit_feedback import DshModelAuditMessageFeedback as Feedback
from bisheng.dsh.domain.repositories.model_audit_feedback import DshModelAuditFeedbackRepository
from bisheng.dsh.domain.repositories.model_audit_queries import DshModelAuditQueryRepository as Query
from bisheng.dsh.domain.services.model_audit_feedback import DshModelAuditFeedbackService
from test.dsh.test_model_audit_flow import USER, call, fixture
from test.dsh.test_model_audit_tree import finish

PATH = "/api/v1/dsh/audit/message-feedback"
UPDATE = {
    "conversation_id": "e2e-feedback-main",
    "message_id": "msg-1",
    "event_seq": 12,
    "op": "put",
    "rating": "positive",
    "category": "task-result",
    "note": "e2e-feedback-note",
}


def install(harness):
    service = DshModelAuditFeedbackService(harness.modes, lambda: harness.scope(DshModelAuditFeedbackRepository))
    harness.app.include_router(router, prefix="/api/v1")
    harness.app.dependency_overrides[feedback_service] = lambda: service
    return service


async def test_feedback_storage_failure_is_generic():
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
        assert "sensitive" not in response.text and UPDATE["note"] not in response.text
        assert harness.calls == 0


async def test_feedback_orders_retraction_and_counts():
    async with fixture("METADATA") as (harness, client, _objects):
        install(harness)
        assert (await client.post(PATH, headers=USER, json=UPDATE)).json() == {"status": "NOT_READY"}
        await call(client, audit_context={"conversation_id": UPDATE["conversation_id"]})
        await harness.drain()
        created = await client.post(PATH, headers=USER, json=UPDATE)
        assert created.status_code == 200
        assert created.json() == {"status": "UPDATED", "event_seq": 12}
        second = {key: value for key, value in UPDATE.items() if key != "note"} | {
            "message_id": "msg-2",
            "event_seq": 21,
            "rating": "negative",
            "category": "other",
        }
        assert (await client.post(PATH, headers=USER, json=second)).json() == {
            "status": "UPDATED",
            "event_seq": 21,
        }
        with harness.scope(Query) as repository:
            finish(repository)
            item = repository.group_page()["items"][0]
            assert item["like_count"] == 1
            assert item["dislike_count"] == 1
            listed = repository.feedback_for(item["conversation_key"], item["user_id"], item["conversation_id"])
            assert {(row["message_id"], row["rating"], row["note"]) for row in listed} == {
                ("msg-1", "positive", "e2e-feedback-note"),
                ("msg-2", "negative", None),
            }
        again = await client.post(PATH, headers=USER, json=UPDATE)
        assert again.json()["status"] == "UNCHANGED"
        stale = await client.post(PATH, headers=USER, json={**UPDATE, "event_seq": 11})
        assert stale.json()["status"] == "STALE"
        conflict = await client.post(PATH, headers=USER, json={**UPDATE, "rating": "negative"})
        assert conflict.json()["status"] == "CONFLICT"
        revised = await client.post(
            PATH, headers=USER, json={**UPDATE, "event_seq": 13, "rating": "negative", "category": "other"}
        )
        assert revised.json() == {"status": "UPDATED", "event_seq": 13}
        removed = await client.post(
            PATH,
            headers=USER,
            json={
                "conversation_id": UPDATE["conversation_id"],
                "message_id": UPDATE["message_id"],
                "event_seq": 14,
                "op": "delete",
            },
        )
        assert removed.json() == {"status": "UPDATED", "event_seq": 14}
        absent = await client.post(
            PATH,
            headers=USER,
            json={
                "conversation_id": UPDATE["conversation_id"],
                "message_id": UPDATE["message_id"],
                "event_seq": 14,
                "op": "delete",
            },
        )
        assert absent.json()["status"] == "UNCHANGED"
        cleared = await client.post(
            PATH,
            headers=USER,
            json={
                "conversation_id": UPDATE["conversation_id"],
                "message_id": "msg-2",
                "event_seq": 22,
                "op": "delete",
            },
        )
        assert cleared.json() == {"status": "UPDATED", "event_seq": 22}
        assert harness.calls == 1
        with harness.scope(Query) as repository:
            finish(repository)
            page = repository.group_page()
            assert page["items"][0]["like_count"] == 0
            assert page["items"][0]["dislike_count"] == 0
            assert repository.session.exec(select_feedback(repository)).all() == []


def select_feedback(repository):
    from sqlmodel import select

    return select(Feedback)


@pytest.mark.parametrize("put_first", [False, True])
async def test_retraction_watermark_rejects_replayed_feedback_and_allows_newer_rating(put_first):
    """Retraction order survives transactions, including delete-before-put delivery."""
    async with fixture("METADATA") as (harness, client, _objects):
        install(harness)
        await call(client, audit_context={"conversation_id": UPDATE["conversation_id"]})
        await harness.drain()
        if put_first:
            assert (await client.post(PATH, headers=USER, json=UPDATE)).json()["status"] == "UPDATED"
        deletion = {
            "conversation_id": UPDATE["conversation_id"],
            "message_id": UPDATE["message_id"],
            "event_seq": 14,
            "op": "delete",
        }
        assert (await client.post(PATH, headers=USER, json=deletion)).json() == {
            "status": "UPDATED" if put_first else "UNCHANGED",
            "event_seq": 14,
        }
        assert (await client.post(PATH, headers=USER, json=deletion)).json() == {
            "status": "UNCHANGED",
            "event_seq": 14,
        }
        for seq, expected in [(12, "STALE"), (14, "CONFLICT")]:
            assert (await client.post(PATH, headers=USER, json={**UPDATE, "event_seq": seq})).json() == {
                "status": expected,
                "event_seq": 14,
            }
        # Inspect a fresh transaction: neither counts nor detail may expose a retraction.
        with harness.scope(Query) as repository:
            finish(repository)
            item = repository.group_page()["items"][0]
            assert (item["like_count"], item["dislike_count"]) == (0, 0)
            assert repository.feedback_for(item["conversation_key"], item["user_id"], item["conversation_id"]) == []
            assert repository.session.exec(select_feedback(repository)).all() == []
        newer = {**UPDATE, "event_seq": 15, "rating": "negative"}
        assert (await client.post(PATH, headers=USER, json=newer)).json() == {"status": "UPDATED", "event_seq": 15}
        assert (await client.post(PATH, headers=USER, json=deletion)).json() == {"status": "STALE", "event_seq": 15}
        assert (await client.post(PATH, headers=USER, json=newer)).json()["status"] == "UNCHANGED"
        with harness.scope(Query) as repository:
            finish(repository)
            item = repository.group_page()["items"][0]
            assert (item["like_count"], item["dislike_count"]) == (0, 1)
        assert harness.calls == 1


@pytest.mark.parametrize(
    "change",
    [
        {"rating": "maybe"},
        {"category": "unknown"},
        {"note": " "},
        {"note": "x" * 8193},
        {"op": "delete", "rating": "positive"},
        {"event_seq": -1},
        {"message_id": ""},
        {"conversation_id": "x" * 257},
        {"op": "put", "rating": None},
    ],
)
async def test_invalid_feedback_does_not_touch_model(change):
    async with fixture() as (harness, client, _objects):
        install(harness)
        body = {**UPDATE, **change}
        if change.get("op") == "delete":
            body = {
                key: value
                for key, value in body.items()
                if key in {"conversation_id", "message_id", "event_seq", "op", "rating"}
            }
        response = await client.post(
            PATH, headers={**USER, "content-type": "application/json"}, content=json.dumps(body)
        )
        assert response.status_code == 400 and response.json()["error"]["code"] == "invalid_request"
        assert harness.calls == 0
