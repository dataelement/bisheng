import pytest
from httpx import ASGITransport, AsyncClient

from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import RunSubject
from test.workflow.test_kunlian_workflow_interaction_e2e import OWNER, _start
from test.workflow.test_kunlian_workflow_interaction_e2e import environment as environment


@pytest.fixture
def control_api(environment, monkeypatch):
    app, service, _, now, state = environment
    state.operations = {}
    state.active = True
    state.on_operation = None

    async def resolve(subject):
        return await service.resolve_user(subject) if state.active else None

    async def authorize_operation(subject, workflow_id, operation):
        assert subject == OWNER
        if state.on_operation is not None:
            state.on_operation(operation)
        return state.operations.get(operation, True)

    configured = type(service)(service.repository, resolve, service.dispatch, authorize_operation=authorize_operation)
    from bisheng.open_endpoints.api.endpoints import kunlian_workflow_runs as api

    monkeypatch.setitem(app.dependency_overrides, api.run_service, lambda: configured)
    return app, service, configured, now, state


async def test_cancel_endpoint_is_idempotent_and_checks_current_owner(control_api):
    app, _, service, _, state = control_api
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as client:
        session_id, path = await _start(client)
        claim = service.repository.claim(7, session_id)
        assert claim
        state.subject = RunSubject(7, "different", 12)
        assert (await client.post(path + "/cancel")).status_code == 404
        state.subject = OWNER
        state.grant = False
        assert (await client.post(path + "/cancel")).status_code == 404
        assert service.repository.load(7, session_id).status == "RUNNING"
        state.grant = True
        for _ in range(2):
            accepted = await client.post(path + "/cancel")
            assert accepted.status_code == 202 and accepted.headers["Cache-Control"] == "no-store"
            assert accepted.json()["data"]["cancel_state"] == "ACCEPTED"
        status = (await client.get(path, params={"view": "status"})).json()["data"]
        assert status["status"] == "CANCEL_REQUESTED" and status["cancel_state"] == "ACCEPTED"
        assert not {"form", "output", "material"} & status.keys()
        service.repository.finish(7, session_id, claim, output={"result": "late"})
        confirmed = await client.post(path + "/cancel")
        assert confirmed.status_code == 200 and confirmed.json()["data"]["cancel_state"] == "CONFIRMED"


async def test_old_run_remains_readable_and_cannot_opt_in_by_replaying(control_api):
    from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import RunRequest
    from test.workflow.test_kunlian_workflow_interaction_e2e import BODY, PATH, START_KEY

    app, old, service, _, _ = control_api
    row, _ = await old.submit(OWNER, START_KEY["Idempotency-Key"], RunRequest.model_validate(BODY))
    path = f"{PATH}/{row.session_id}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as client:
        replay = await client.post(PATH, json=BODY, headers=START_KEY)
        assert replay.status_code == 200 and replay.json()["data"]["session_id"] == row.session_id
        assert (await client.get(path)).json()["data"]["status"] == "QUEUED"
        for candidate in (await client.post(path + "/cancel"), await client.get(path, params={"view": "status"})):
            assert candidate.status_code == 409 and candidate.json()["status_message"] == "CONTROL_UNAVAILABLE"
    assert "run_control" not in service.repository.load(7, row.session_id).material
