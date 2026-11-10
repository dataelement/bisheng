import pytest
from httpx import ASGITransport, AsyncClient

from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import RunSubject
from test.workflow.test_kunlian_workflow_interaction_e2e import OWNER, _start
from test.workflow.test_kunlian_workflow_interaction_e2e import environment as environment
from test.workflow.test_kunlian_workflow_run_control_api import control_api as control_api


@pytest.mark.parametrize("reason", ["tenant", "user", "connection", "revoked", "inactive", "unknown"])
async def test_denied_access_never_exposes_or_mutates_run(control_api, reason):
    app, _, service, _, state = control_api
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as client:
        session_id, path = await _start(client)
        before = service.repository.load(7, session_id).model_dump()
        state.subject = {
            "tenant": RunSubject(8, "mock", 12),
            "user": RunSubject(7, "mock", 13),
            "connection": RunSubject(7, "MOCK", 12),
        }.get(reason, OWNER)
        state.grant = reason != "revoked"
        state.active = reason != "inactive"
        if reason == "unknown":
            state.operations.update(dict.fromkeys(("cancel", "status", "result", "events", "trace")))
        expected = (503, "UNAVAILABLE") if reason == "unknown" else (404, "SESSION_NOT_FOUND")
        for method, url in (
            ("POST", path + "/cancel"),
            ("GET", path + "?view=status"),
            ("GET", path + "?view=result"),
            ("GET", path + "/events"),
            ("GET", path + "?view=trace"),
        ):
            response = await client.request(method, url)
            envelope = response.json()
            assert (response.status_code, envelope["status_message"]) == expected
            assert envelope["data"] is None and response.headers["Cache-Control"] == "no-store"
        assert service.repository.load(7, session_id).model_dump() == before


async def test_status_event_result_and_trace_have_independent_projections(control_api):
    app, _, service, _, state = control_api
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as client:
        session_id, path = await _start(client)
        assert (await client.get(path + "?view=result")).json()["status_message"] == "RESULT_NOT_AVAILABLE"
        claim = service.repository.claim(7, session_id)
        assert service.repository.finish(7, session_id, claim, output={"result": "authorized result"})
        state.operations.update(dict.fromkeys(("result", "trace", "events"), False))
        status = (await client.get(path + "?view=status")).json()["data"]
        assert status["status"] == "SUCCEEDED" and not {"output", "trace_id", "resume_after"} & status.keys()
        assert (await client.get(path + "/events")).status_code == 404
        assert (await client.get(path + "?view=trace")).status_code == 404
        assert (await client.get(path + "?view=result")).status_code == 404
        state.operations["result"] = None
        default = await client.get(path)
        assert default.status_code == 503 and default.json()["data"] is None

        state.operations.update(status=False, result=True, trace=True, events=True)
        assert (await client.get(path + "?view=status")).status_code == 404
        assert (await client.get(path + "/events")).status_code == 200
        trace = (await client.get(path + "?view=trace")).json()["data"]
        assert set(trace) == {"session_id", "trace_id"} and trace["session_id"] == session_id
        assert (await client.get(path + "?view=trace")).json()["data"] == trace
        result = (await client.get(path + "?view=result")).json()["data"]
        assert result["output"] == {"result": "authorized result"} and "trace_id" not in result


async def test_default_query_rechecks_expiration_after_result_authorization(control_api):
    app, _, service, now, state = control_api
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as client:
        session_id, path = await _start(client)
        claim = service.repository.claim(7, session_id)
        assert service.repository.finish(7, session_id, claim, output={"result": "expired result"})
        expires_at = service.repository.load(7, session_id).expires_at

        def expire_during_authorization(operation):
            if operation == "result":
                now[0] = expires_at

        state.on_operation = expire_during_authorization
        response = await client.get(path)
        assert response.status_code == 404 and response.json()["data"] is None
