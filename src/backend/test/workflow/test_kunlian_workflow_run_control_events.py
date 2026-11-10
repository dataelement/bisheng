from httpx import ASGITransport, AsyncClient

from test.workflow.test_kunlian_workflow_interaction_e2e import _start
from test.workflow.test_kunlian_workflow_interaction_e2e import environment as environment
from test.workflow.test_kunlian_workflow_run_control_api import control_api as control_api


async def test_events_page_repeats_and_expired_cursor_recovers_from_status(control_api):
    app, _, service, now, _ = control_api
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as client:
        session_id, path = await _start(client)
        claim = service.repository.claim(7, session_id)
        assert claim and (await client.post(path + "/cancel")).status_code == 202
        service.repository.finish(7, session_id, claim, output={"result": "not committed"})

        async def page(after):
            response = await client.get(path + "/events", params={"after": after, "limit": 1})
            assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
            return response.json()["data"]

        pages = [await page(after) for after in range(4)]
        assert await page(0) == pages[0]
        assert [item["next_after"] for item in pages] == [1, 2, 3, 4]
        assert [item["has_more"] for item in pages] == [True, True, True, False]
        assert [item["events"][0]["kind"] for item in pages] == ["ACCEPTED", "STARTED", "CANCEL_ACCEPTED", "CANCELLED"]
        assert all(set(item["events"][0]) == {"seq", "kind", "status", "occurred_at"} for item in pages)
        assert (await page(4))["events"] == []
        ahead = await client.get(path + "/events", params={"after": 5})
        assert (ahead.status_code, ahead.json()["status_message"]) == (422, "INVALID_INPUT")
        now[0] += 900
        expired = await client.get(path + "/events")
        assert (expired.status_code, expired.json()["status_message"]) == (409, "EVENT_CURSOR_EXPIRED")
        status = (await client.get(path, params={"view": "status"})).json()["data"]
        assert status["status"] == pages[-1]["events"][0]["status"] and status["resume_after"] == 4
        assert (await page(status["resume_after"]))["next_after"] == 4


def test_bounded_log_preserves_monotonic_sequence_and_time():
    from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import RunControl

    control = RunControl(trace_id="a" * 32)
    for i in range(35):
        control.append(100 - i, "STARTED", "RUNNING")
    assert control.last_seq == 35 and control.pruned_through == 3
    assert [event.seq for event in control.events] == list(range(4, 36))
    assert {event.occurred_at for event in control.events} == {100}
