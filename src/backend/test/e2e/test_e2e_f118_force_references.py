"""Opt-in force deletion and manual business repair; collection never writes.

Uses the same explicit readiness/private-file contract as F118's ordinary suite,
with a separate prefixed Child. These tests do not manufacture File bindings:
AS/WF selectors bind a whole space, not metadata document-ID expressions.
"""

import os
from copy import deepcopy

import pytest

from test.e2e.helpers.f118_force_references import (
    create_sources,
    knowledge_graph,
    save_assistant,
    wait_deletion,
)
from test.e2e.helpers.f118_force_references import (
    force_target as force_target,
)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.skipif(os.environ.get("F118_E2E") != "1", reason="requires upgraded isolated F118 and explicit opt-in"),
]


async def test_ac28_ac68_force_space_preserves_invalid_sources_and_original_business_save_repairs(force_target):
    """AC-28/29/68/87/88/94: real AS/WF sources survive force and repair through their original saves."""
    target = force_target
    sid = (await target.space("force-source"))["id"]
    replacement = (await target.space("force-repaired"))["id"]
    file = await target.upload(sid, "bound-space.txt", b"e2e-f118 real source space content\n")
    assistant_id, workflow_id, version_id = await create_sources(target, sid)
    original = await target.ok("GET", f"/workflow/versions/{version_id}")
    assert original["flow_id"] == workflow_id and original["data"] == knowledge_graph(sid)
    references = await target.ok("GET", f"/knowledge/space/{sid}/references")
    assert references["check_complete"] is True and references["blocked"] is True
    assert references["source_counts"]["assistant"] == references["source_counts"]["workflow_version"] == 1
    file_refs = await target.ok(
        "POST", f"/knowledge/space/{sid}/files/references", json={"items": [{"id": file["id"], "type": "file"}]}
    )
    assert file_refs["check_complete"] is True and file_refs["blocked"] is False
    ordinary = await target.ok("POST", f"/knowledge/space/{sid}/delete/precheck", json={})
    assert ordinary["check_complete"] is True and ordinary["can_execute"] is False
    await target.error("POST", f"/knowledge/space/{sid}/deletion/confirm", 10995, json=target.confirmation(ordinary))
    assert (await target.file(sid, file["id"]))["status"] == 2
    forced = await target.ok("POST", f"/knowledge/space/{sid}/delete/precheck", json={"force": True})
    assert forced["check_complete"] is True and forced["can_execute"] is True
    command = target.confirmation(forced)
    await wait_deletion(target, sid, command)
    await target.error("GET", f"/knowledge/space/{sid}/info", 18000)
    invalid = await target.ok("GET", f"/assistant/info/{assistant_id}")
    assert invalid["id"] == assistant_id and invalid["knowledge_ids"] == [sid]
    slot = next(row for row in invalid["reference_states"] if row["target_type"] == "knowledge_space")
    assert slot["target_id"] == str(sid) and slot["state"] == "invalid_deleted" and slot["is_valid"] is False
    saved = await target.ok("GET", f"/workflow/versions/{version_id}")
    assert saved["id"] == version_id and saved["flow_id"] == workflow_id and saved["data"] == original["data"]
    await target.error(
        "POST",
        "/workflow/run_once",
        10996,
        json={"workflow_id": workflow_id, "node_data": saved["data"]["nodes"][0], "node_input": {}},
    )
    await save_assistant(target, assistant_id, replacement)
    await target.ok(
        "PUT", f"/workflow/versions/{version_id}", json={"data": knowledge_graph(replacement), "flow_type": 10}
    )
    repaired = await target.ok("GET", f"/assistant/info/{assistant_id}")
    assert repaired["id"] == assistant_id and repaired["knowledge_ids"] == [replacement]
    slots = [row for row in repaired["reference_states"] if row["target_type"] == "knowledge_space"]
    assert len(slots) == 1 and slots[0]["target_id"] == str(replacement) and slots[0]["state"] == "valid"
    updated = await target.ok("GET", f"/workflow/versions/{version_id}")
    assert updated["id"] == version_id and updated["flow_id"] == workflow_id
    assert updated["data"] == knowledge_graph(replacement)
    new_refs = await target.ok("GET", f"/knowledge/space/{replacement}/references")
    assert new_refs["source_counts"]["assistant"] == new_refs["source_counts"]["workflow_version"] == 1
    replay = await target.ok("POST", f"/knowledge/space/{sid}/deletion/confirm", json=command)
    assert replay["state"] == "succeeded" and replay["reused"] is True


async def test_ac70_force_one_embedding_keeps_space_binding_until_explicit_rebuild(force_target):
    """AC-70/71/72/73/75/76: remove one isolated model, preserve business IDs and manually rebuild to a valid model."""
    target = force_target
    original_provider = await target.ok("GET", "/llm/info", params={"server_id": target.server_id})
    payload = deepcopy(target.model_fixture["server"])
    payload.update(name=target.prefix + "unused-provider", share_to_children=False)
    for index, model in enumerate(payload["models"]):
        model["name"] = target.prefix + f"force-model-{index}"
    provider = await target.ok("POST", "/llm", json=payload)
    facts = await target.ok("GET", "/llm/info", params={"server_id": provider["id"]})
    assert facts["tenant_id"] == target.tenant_id and facts["user_id"] == target.owner_id
    actual = {model["model_name"]: model for model in facts["models"]}
    victim = actual[target.model_fixture["embedding_model_names"][0]]["id"]
    await target.ok("POST", "/llm/verify", json={"model_id": victim})
    sid = (await target.space("model-repair", embedding_model_id=victim))["id"]
    file = await target.upload(sid, "repair.txt", b"e2e-f118 explicit repair retains this document\n")
    before = await target.ok("GET", f"/knowledge/space/file/{file['id']}/versions")
    anchor = await target.ok("GET", f"/knowledge/space/{sid}/files/{file['id']}/processing-target")
    change = deepcopy(payload)
    change["id"] = provider["id"]
    change["models"] = [
        {**model, "id": actual[model["model_name"]]["id"]}
        for model in payload["models"]
        if actual[model["model_name"]]["id"] != victim
    ]
    plan = await target.ok("POST", "/llm/removal-plan", json=change)
    assert plan["inspection"]["check_complete"] is True and plan["inspection"]["blocked"] is True
    confirmation = {key: plan["confirmation"][key] for key in ("confirmation_id", "plan_digest")}
    await target.error("PUT", "/llm", 10995, json=change, params={**confirmation, "force": False})
    assert {
        model["id"] for model in (await target.ok("GET", "/llm/info", params={"server_id": provider["id"]}))["models"]
    } == {model["id"] for model in facts["models"]}
    await target.ok("PUT", "/llm", json=change, params={**confirmation, "force": True})
    remaining = await target.ok("GET", "/llm/info", params={"server_id": provider["id"]})
    assert {model["id"] for model in remaining["models"]} == {model["id"] for model in facts["models"]} - {victim}
    broken = await target.info(sid)
    assert broken["id"] == sid and str(broken["model"]) == str(victim)
    assert (await target.ok("GET", f"/knowledge/space/file/{file['id']}/versions")) == before
    await target.error(
        "POST",
        f"/knowledge/space/{sid}/processing-jobs/precheck",
        10996,
        json={"kind": "file_resplit", "targets": [anchor], "parameters": {}},
    )
    await target.processing(sid, "embedding_rebuild", {"embedding_model_id": target.embedding(0)["id"]})
    repaired = await target.info(sid)
    assert repaired["id"] == sid and str(repaired["model"]) == str(target.embedding(0)["id"])
    after = await target.ok("GET", f"/knowledge/space/file/{file['id']}/versions")
    assert after["document_id"] == before["document_id"]
    assert [(row["version_id"], row["knowledge_file_id"]) for row in after["versions"]] == [
        (row["version_id"], row["knowledge_file_id"]) for row in before["versions"]
    ]
    assert (await target.file(sid, file["id"]))["status"] == 2
    assert (
        await target.ok("GET", "/knowledge/chunk", params={"knowledge_id": sid, "file_ids": [file["id"]], "limit": 200})
    )["total"] > 0
    untouched = await target.ok("GET", "/llm/info", params={"server_id": target.server_id})
    assert {model["id"] for model in untouched["models"]} == {model["id"] for model in original_provider["models"]}
