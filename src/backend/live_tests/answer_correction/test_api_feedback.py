"""HTTP contract checks for F119 using the live scenario accounts."""

from test_scenario_feedback import data, rejected, scenario  # noqa: F401


def test_assignment_options_and_reply_contract(scenario):
    """API-119-01, API-119-02 and API-119-03."""
    call, config = scenario
    created = data(call("user", "POST", json={
        "answer_id": config["answer_id"],
        "quote": config["quote"],
        "correction": "Corrected statement",
        "evidence": "Source https://example.org/reference",
    }))
    path = str(created["id"])
    options = data(call("owner", "GET", f"{path}/knowledge-options"))["items"]
    assert config["knowledge_id"] in {option["id"] for option in options}
    assert config["unrelated_knowledge_id"] not in {option["id"] for option in options}
    rejected(call("outsider", "GET", f"{path}/knowledge-options"))

    assignment = {"knowledge_id": config["knowledge_id"], "assignee_id": config["assignee_id"]}
    candidates = data(call("owner", "GET", f"{path}/assignee-options", params={
        "knowledge_id": config["knowledge_id"], "page_size": 100,
    }))
    assert candidates["total"] >= len(candidates["items"])
    assert config["assignee_id"] in {candidate["id"] for candidate in candidates["items"]}
    rejected(call("owner", "GET", f"{path}/assignee-options", params={
        "knowledge_id": config["unrelated_knowledge_id"],
    }))
    data(call("owner", "POST", f"{path}/assignment", json=assignment))
    rejected(call("owner", "POST", f"{path}/assignment", json=assignment))
    data(call("maintainer", "POST", f"{path}/result", json={"result": "Internal processing details"}))
    data(call("owner", "POST", f"{path}/reply", json={"reply": "First reply"}))
    rejected(call("owner", "POST", f"{path}/reply", json={"reply": "Second reply"}))
    mine = data(call("user", "GET", path, params={"view": "mine"}))
    assert mine["reply"] == "First reply"
    assert {"result", "assignee_id", "knowledge_id"}.isdisjoint(mine)
