"""Run against the current branch with pre-provisioned real users and answers."""

import json
import os

import httpx
import pytest


@pytest.fixture
def scenario():
    raw = os.getenv("BISHENG_CORRECTION_SCENARIO")
    if not raw:
        pytest.skip("Set BISHENG_CORRECTION_SCENARIO for the live environment")
    config = json.loads(raw)
    with httpx.Client(base_url=config["url"].rstrip("/") + "/api/v1/answer-corrections/") as client:
        def call(actor, method, path="", **kwargs):
            return client.request(method, path, headers=config["actors"][actor], **kwargs)
        yield call, config


def data(response):
    response.raise_for_status()
    body = response.json()
    assert body["status_code"] == 200
    return body["data"]


def rejected(response):
    assert 400 <= response.status_code < 500 or (
        response.is_success and response.json()["status_code"] != 200
    )


def test_feedback_lifecycle(scenario):
    call, config = scenario
    payload = {
        "answer_id": config["answer_id"],
        "quote": config["quote"],
        "correction": "Corrected statement",
        "evidence": "Source https://example.org/reference",
    }

    # FLOW-119-01 and FLOW-119-07
    rejected(call("user", "POST", json={**payload, "evidence": ""}))
    rejected(call("user", "POST", json={**payload, "quote": ""}))
    for key in ("unsupported_answer_id", "shared_answer_id"):
        answer_id = config[key]
        rejected(call("user", "POST", json={**payload, "answer_id": answer_id}))
        assert not data(call("user", "GET", f"eligibility/{answer_id}"))["eligible"]
    feedback = data(call("user", "POST", json=payload))
    path = str(feedback["id"])

    # FLOW-119-02
    queue = data(call("owner", "GET", params={"view": "owner"}))
    item = next(item for item in queue["items"] if item["id"] == feedback["id"])
    assert item["state"] == "pending_assignment"
    assert all(item[key] == payload[key] for key in ("quote", "correction", "evidence"))
    rejected(call("outsider", "GET", path, params={"view": "owner"}))

    # FLOW-119-03
    assignment = {"knowledge_id": config["knowledge_id"], "assignee_id": config["assignee_id"]}
    rejected(call("owner", "POST", f"{path}/assignment", json={
        **assignment, "knowledge_id": config["unrelated_knowledge_id"],
    }))
    assert data(call("owner", "GET", path, params={"view": "owner"}))["state"] == "pending_assignment"
    data(call("owner", "POST", f"{path}/assignment", json=assignment))
    assigned = data(call("maintainer", "GET", path, params={"view": "assigned"}))
    assert assigned["state"] == "pending_processing"
    assert all(assigned[key] == payload[key] for key in ("quote", "correction", "evidence"))

    # FLOW-119-04 and FLOW-119-05
    rejected(call("owner", "POST", f"{path}/reply", json={"reply": "Too early"}))
    result = {"result": "Corrected the source document"}
    rejected(call("other_maintainer", "POST", f"{path}/result", json=result))
    assert data(call("owner", "GET", path, params={"view": "owner"}))["state"] == "pending_processing"
    data(call("maintainer", "POST", f"{path}/result", json=result))
    processed = data(call("owner", "GET", path, params={"view": "owner"}))
    assert processed["state"] == "pending_reply"
    assert processed["result"] == result["result"]
    reply = {"reply": "Thank you. We corrected the source."}
    data(call("owner", "POST", f"{path}/reply", json=reply))

    # FLOW-119-06
    visible = data(call("user", "GET", path, params={"view": "mine"}))
    assert visible["state"] == "replied"
    assert visible["quote"] == payload["quote"]
    assert visible["reply"] == reply["reply"]
    rejected(call("outsider", "GET", path, params={"view": "mine"}))
    rejected(call("other_tenant", "GET", path, params={"view": "mine"}))
