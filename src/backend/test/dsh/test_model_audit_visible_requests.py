"""AC-75: filter auxiliary calls only inside a conversation, before pagination."""

from datetime import timedelta

import pytest

from bisheng.dsh.domain.repositories.model_audit_queries import DshModelAuditQueryRepository
from bisheng.dsh.infrastructure.model_audit_codec import conversation_key
from test.dsh.model_audit_fixtures import NOW, audit_session
from test.dsh.test_model_audit_flow import BASE, LOCAL_ADMIN, fixture
from test.dsh.test_model_audit_groups import row


async def test_conversation_requests_hide_auxiliary_without_empty_pages_or_data_loss():
    async with fixture() as (harness, client, objects):
        harness.queries.now = lambda: NOW + timedelta(seconds=1)
        kinds = ["session-title", "compaction", "chat", "session-title", None, "chat"]
        with audit_session(harness.engine) as session, session.begin():
            for index, kind in enumerate(kinds):
                session.add(row(f"visible-{index}", conversation="visible-session", request_kind=kind))
            session.flush()
            repository = DshModelAuditQueryRepository(session)
            for request_id in repository.projection_candidates():
                repository.project_request(request_id, now=NOW)
        key = conversation_key(2, 20, "visible-session")
        path = BASE + f"/conversation-groups/{key}/requests"
        first = (await client.get(path, headers=LOCAL_ADMIN, params={"limit": 2})).json()["data"]
        assert [item["request_id"] for item in first["items"]] == ["visible-2", "visible-4"]
        assert first["next_cursor"]
        second = (
            await client.get(path, headers=LOCAL_ADMIN, params={"limit": 2, "cursor": first["next_cursor"]})
        ).json()["data"]
        assert [item["request_id"] for item in second["items"]] == ["visible-5"]
        assert second["next_cursor"] is None
        hidden = (await client.get(path, headers=LOCAL_ADMIN, params={"request_id": "visible-0"})).json()["data"]
        assert hidden["items"] == [] and hidden["next_cursor"] is None
        # Outer directories, all-request diagnostics and raw stored facts retain their contract.
        groups = (await client.get(BASE + "/conversation-groups", headers=LOCAL_ADMIN)).json()["data"]
        assert len(groups["items"]) == 1
        assert groups["items"][0]["request_count"] == len(kinds)
        with audit_session(harness.engine) as session:
            repository = DshModelAuditQueryRepository(session)
            assert len(repository.page(limit=20)["items"]) == len(kinds)
            with pytest.raises(ValueError, match="Invalid audit cursor"):
                repository.page(cursor=first["next_cursor"], limit=2, user_id=20, conversation_id="visible-session")
            assert [repository.request(f"visible-{i}").request_kind for i in range(len(kinds))] == kinds
        assert not objects.data
