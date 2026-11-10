"""Opt-in F118 API journeys against the upgraded isolated f118-e2e deployment.

Run only after the operator verifies deployment/migration readiness. Read
helpers/f118_unification.py for explicit environment/private-file contracts.
Example local collection (no network or writes):
    pytest --confcutdir=test/e2e --collect-only test/e2e/test_e2e_f118_unification.py

Partial API coverage: AC-02/06/07/09/10/28-31/36/38-45/48-50/65/67/70-73/78/79/94.
The four native kinds are embedding_rebuild, file_reprocess, file_resplit and
metadata_schema_change; each must finish its real worker path and GET checks.
This is not the whole 140-case acceptance report. UI, migration/restore and
old application replay, hidden/force references, move/copy failure matrices,
failure injection,
large chunk sets, all resource-type consumers and scope/foreign-tenant matrices
remain separate. No DM8, share-link issuance or general worker-I/O race work.
"""

from __future__ import annotations

import json
import os
from copy import deepcopy

import httpx
import pytest
import pytest_asyncio

from test.e2e.helpers.f118_unification import F118Environment

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.skipif(os.environ.get("F118_E2E") != "1", reason="requires upgraded isolated F118 and explicit opt-in"),
]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def target():
    async with httpx.AsyncClient(timeout=45, trust_env=False, follow_redirects=False) as client:
        environment = F118Environment.from_environment(client)
        try:
            await environment.prepare()
            yield environment
        finally:
            await environment.cleanup()


async def test_ac02_ac65_old_zero_projects_the_same_real_space_and_qa_is_independent(target):
    """AC-02/65/67: old 0 DTO projects one real 3; QA stays 1 and retired 2 returns 10962."""
    native = await target.space("native")
    legacy = await target.space("legacy", legacy_type=0)
    qa = await target.space("qa", legacy_type=1)
    assert native["type"] == 3 and legacy["type"] == 0 and qa["type"] == 1
    assert (await target.info(legacy["id"]))["type"] == 3
    projected = await target.ok("GET", "/knowledge/info", params={"knowledge_id": native["id"]})
    assert len(projected) == 1 and projected[0]["id"] == native["id"] and projected[0]["type"] == 0
    folder = await target.ok(
        "POST", f"/knowledge/space/{legacy['id']}/folders", json={"name": target.prefix + "folder"}
    )
    assert any(row["id"] == folder["id"] for row in (await target.files(legacy["id"]))["data"])
    spaces = await target.ok("GET", "/knowledge/space/list", params={"keyword": target.prefix, "page_size": 200})
    assert {native["id"], legacy["id"]}.issubset({row["id"] for row in spaces["data"]})
    assert qa["id"] not in {row["id"] for row in spaces["data"]}
    qas = await target.ok("GET", "/knowledge", params={"type": 1, "name": target.name("qa"), "page_size": 200})
    assert any(row["id"] == qa["id"] and row["type"] == 1 for row in qas["data"])
    await target.error("POST", "/knowledge/create", 10962, json={"name": target.prefix + "retired", "type": 2})


async def test_ac06_embedding_default_only_initializes_new_spaces(target):
    """AC-06/07/44: change/clear this Child's Workbench default without rewriting an existing space."""
    creation = await target.ok("GET", "/knowledge/space/creation-settings")
    assert int(creation["embedding_model"]["id"]) == target.embedding(0)["id"]
    first = await target.space("default-a")
    original_jobs = await target.ok("GET", f"/knowledge/space/{first['id']}/processing-jobs")
    try:
        await target.set_workbench(target.embedding(1))
        second = await target.space("default-b")
        assert str((await target.info(first["id"]))["model"]) == str(target.embedding(0)["id"])
        assert str((await target.info(second["id"]))["model"]) == str(target.embedding(1)["id"])
        await target.set_workbench(None)
        assert str((await target.info(first["id"]))["model"]) == str(target.embedding(0)["id"])
        assert str((await target.info(second["id"]))["model"]) == str(target.embedding(1)["id"])
        jobs = await target.ok("GET", f"/knowledge/space/{first['id']}/processing-jobs")
        assert jobs == original_jobs
    finally:
        await target.set_workbench(target.embedding(0))


async def test_ac30_visible_reads_do_not_grant_rename_download_or_delete(target):
    """AC-30/31/36/78/79: real pure-visible Grant permits reads but preserves each original action gate."""
    space = await target.space("permissions")
    sid = space["id"]
    file = await target.upload(sid, "visible.txt", b"e2e-f118 permission boundary\n")
    folder = await target.ok("POST", f"/knowledge/space/{sid}/folders", json={"name": target.prefix + "private-folder"})
    catalog = await target.ok("GET", "/permissions/catalog", actor=target.root)
    assert all(action["code"] != "use" for action in catalog["actions"])
    assert all("use" not in model["action_codes"] for model in catalog["models"])
    models = await target.ok("GET", f"/permissions/resources/knowledge_space/{sid}/grantable-models")
    catalog_models = {model["key"]: model for model in catalog["models"]}
    resource_types = {"knowledge_space", "folder", "knowledge_file"}
    relevant_actions = {
        action["code"] for action in catalog["actions"] if resource_types.intersection(action["resource_types"])
    }
    candidates = [
        model
        for model in models
        if model["active"]
        and model["visibility_only"]
        and "knowledge_space" in catalog_models[model["key"]]["visibility_only_resource_types"]
        and not relevant_actions.intersection(catalog_models[model["key"]]["action_codes"])
    ]
    assert candidates, "The migrated real Catalog must supply a grantable pure-visible model"
    selected = catalog_models[candidates[0]["key"]]
    assert not relevant_actions.intersection(selected["action_codes"])
    context = await target.ok("GET", f"/permissions/resources/knowledge_space/{sid}/context")
    await target.ok(
        "POST",
        f"/permissions/resources/knowledge_space/{sid}/grants:mutate",
        json={
            "idempotency_key": target.prefix + "visible-grant",
            "expected_resource_version": context["resource_version"],
            "expected_catalog_release_id": context["catalog_release_id"],
            "changes": [
                {"op": "ADD", "model_key": selected["key"], "subject": {"type": "user", "id": str(target.reader_id)}}
            ],
        },
    )
    visible = await target.ok("GET", "/knowledge/space/list", actor=target.reader, params={"keyword": space["name"]})
    assert any(row["id"] == sid for row in visible["data"])
    assert (await target.info(sid, actor=target.reader))["id"] == sid
    children = await target.files(sid, actor=target.reader)
    assert {file["id"], folder["id"]}.issubset({row["id"] for row in children["data"]})
    await target.ok("GET", f"/knowledge/space/{sid}/files/{file['id']}/preview", actor=target.reader)
    actions = await target.ok(
        "GET", f"/permissions/resources/knowledge_file/{file['id']}/my-permissions", actor=target.reader
    )
    assert set(actions["actions"]) <= {"visible"}
    await target.error(
        "PUT", f"/knowledge/space/{sid}/files/{file['id']}", 18040, actor=target.reader, json={"name": "denied.txt"}
    )
    await target.error(
        "PUT",
        f"/knowledge/space/{sid}/folders/{folder['id']}",
        18040,
        actor=target.reader,
        json={"name": "denied-folder"},
    )
    await target.error("GET", f"/knowledge/space/{sid}/files/{file['id']}/download", 19000, actor=target.reader)
    review = await target.ok(
        "POST",
        f"/knowledge/space/{sid}/files/delete/precheck",
        actor={**target.reader, "X-Management-Tenant": str(target.tenant_id)},
        json={"items": [{"id": file["id"], "type": "file"}]},
    )
    assert review["can_execute"] is False and not review["valid_items"]
    assert review["invalid_items"] == [
        {"id": file["id"], "type": "file", "name": None, "reason": "no_permission", "error_code": None}
    ]
    assert (await target.file(sid, file["id"]))["file_name"] == file["file_name"]
    hidden = await target.ok("GET", "/knowledge/space/list", actor=target.outsider, params={"keyword": space["name"]})
    assert not any(row["id"] == sid for row in hidden["data"])
    download = await target.ok("GET", f"/knowledge/space/{sid}/files/{file['id']}/download")
    assert download["original_url"]
    await target.ok("PUT", f"/knowledge/space/{sid}/files/{file['id']}", json={"name": target.prefix + "renamed.txt"})
    assert (await target.file(sid, file["id"]))["file_name"] == target.prefix + "renamed.txt"
    await target.ok(
        "PUT", f"/knowledge/space/{sid}/folders/{folder['id']}", json={"name": target.prefix + "renamed-folder"}
    )
    assert any(
        row["id"] == folder["id"] and row["file_name"] == target.prefix + "renamed-folder"
        for row in (await target.files(sid))["data"]
    )


async def test_ac38_defaults_overrides_and_invalid_writes_preserve_saved_rules(target):
    """AC-38/40/41/42/43/44: document/table defaults, actual per-file snapshots and no implicit reprocessing."""
    sid = (await target.space("rules"))["id"]
    base = f"/knowledge/space/{sid}"
    before = await target.ok("GET", base + "/processing-settings")
    defaults = deepcopy(before["effective_defaults"])
    defaults["document"].update(chunk_size=512, chunk_overlap=32)
    defaults["table"].update(slice_length=7, header_start_row=1, header_end_row=1, append_header=1)
    saved = await target.ok(
        "PUT",
        base + "/processing-settings",
        json={"expected_config_version": before["config_version"], "defaults": defaults},
    )
    assert saved["saved_defaults"] == defaults and saved["config_version"] == before["config_version"] + 1
    normal = await target.upload(sid, "defaults.txt", b"e2e-f118 defaults\n" * 80)
    temporary = await target.upload(
        sid,
        "temporary.txt",
        b"e2e-f118 temporary\n" * 80,
        overrides={"document": {"chunk_size": 256, "chunk_overlap": 16}},
    )
    normal_rule = json.loads(normal["split_rule"])["_effective_processing"]
    temporary_rule = json.loads(temporary["split_rule"])["_effective_processing"]
    assert normal_rule["effective_rule"]["chunk_size"] == 512
    assert temporary_rule["effective_rule"]["chunk_size"] == 256
    assert normal_rule["space_config_version"] == temporary_rule["space_config_version"] == saved["config_version"]
    table = await target.upload(sid, "defaults.csv", b"name,value\nalpha,1\nbeta,2\n")
    table_override = await target.upload(
        sid,
        "temporary.csv",
        b"name,value\ngamma,3\ndelta,4\n",
        overrides={"table": {"slice_length": 3}},
    )
    table_rule = json.loads(table["split_rule"])["_effective_processing"]
    table_override_rule = json.loads(table_override["split_rule"])["_effective_processing"]
    assert table_rule["file_kind"] == table_override_rule["file_kind"] == "table"
    assert table_rule["effective_rule"]["slice_length"] == 7
    assert table_override_rule["effective_rule"]["slice_length"] == 3
    assert (await target.ok("GET", base + "/processing-settings")) == saved
    for group, fields in (
        ("document", {"chunk_size": 10, "chunk_overlap": 11}),
        ("table", {"header_start_row": 2, "header_end_row": 1}),
    ):
        invalid = deepcopy(defaults)
        invalid[group].update(fields)
        await target.error(
            "PUT",
            base + "/processing-settings",
            422,
            json={"expected_config_version": saved["config_version"], "defaults": invalid},
        )
        assert (await target.ok("GET", base + "/processing-settings")) == saved
    changed = deepcopy(defaults)
    changed["document"]["chunk_size"] = 768
    await target.ok(
        "PUT",
        base + "/processing-settings",
        json={"expected_config_version": saved["config_version"], "defaults": changed},
    )
    assert (await target.file(sid, normal["id"]))["split_rule"] == normal["split_rule"]
    assert not (await target.ok("GET", base + "/processing-jobs"))["data"]


async def test_ac45_four_native_kinds_finish_real_worker_and_index_work(target):
    """AC-45/48/49/50: all four actual native kinds poll to succeeded; GET verifies targets/model/schema/chunks."""
    sid = (await target.space("four-kinds"))["id"]
    file = await target.upload(sid, "processing.txt", b"e2e-f118 processing actual file\n" * 40)
    base = f"/knowledge/space/{sid}"
    anchor = await target.ok("GET", f"{base}/files/{file['id']}/processing-target")
    for kind in ("file_reprocess", "file_resplit"):
        await target.processing(
            sid, kind, {"overrides": {"document": {"chunk_size": 256, "chunk_overlap": 16}}}, [anchor]
        )
        assert (await target.wait_file(sid, file["id"]))["id"] == file["id"]
        assert (await target.ok("GET", f"{base}/files/{file['id']}/processing-target")) == anchor
    schema = await target.ok("GET", base + "/metadata-schema")
    await target.processing(
        sid,
        "metadata_schema_change",
        {
            "expected_schema_revision": schema["revision"],
            "changes": [{"operation": "add", "field_name": "e2e_f118_marker", "field_type": "string"}],
        },
    )
    changed = await target.ok("GET", base + "/metadata-schema")
    assert changed["revision"] == schema["revision"] + 1
    assert any(row["name"] == "e2e_f118_marker" for row in changed["fields"])
    await target.processing(sid, "embedding_rebuild", {"embedding_model_id": target.embedding(1)["id"]})
    assert str((await target.info(sid))["model"]) == str(target.embedding(1)["id"])
    chunks = await target.ok(
        "GET", "/knowledge/chunk", params={"knowledge_id": sid, "file_ids": [file["id"]], "limit": 200}
    )
    assert chunks["total"] > 0 and chunks["data"]
    assert {entry["kind"] for entry in target.events if entry["space_id"] == sid} == {
        "file_reprocess",
        "file_resplit",
        "metadata_schema_change",
        "embedding_rebuild",
    }


async def test_ac09_duplicate_overwrite_preserves_actual_file_document_and_version_ids(target):
    """AC-09/10: duplicate response is staged only; explicit legacy retry overwrites the existing real file."""
    sid = (await target.space("versions"))["id"]
    first = await target.upload(sid, "version-one.txt", b"e2e-f118 original version\n")
    chain = await target.ok("GET", f"/knowledge/space/file/{first['id']}/versions")
    duplicate = await target.upload(sid, "version-one.txt", b"e2e-f118 overwritten content\n", wait=False)
    assert duplicate["id"] == first["id"] and duplicate["status"] == 3
    assert (await target.file(sid, first["id"]))["md5"] == first["md5"]
    await target.ok("POST", "/knowledge/retry", json={"knowledge_id": sid, "file_objs": [duplicate]})
    overwritten = await target.wait_file(sid, first["id"])
    assert overwritten["id"] == first["id"]
    chunks = await target.ok(
        "GET", "/knowledge/chunk", params={"knowledge_id": sid, "file_ids": [first["id"]], "limit": 200}
    )
    assert chunks["total"] > 0
    indexed_content = json.dumps(chunks["data"], ensure_ascii=False)
    assert "overwritten content" in indexed_content and "original version" not in indexed_content
    after = await target.ok("GET", f"/knowledge/space/file/{first['id']}/versions")
    assert after["document_id"] == chain["document_id"]
    assert [row["version_id"] for row in after["versions"]] == [row["version_id"] for row in chain["versions"]]
    second = await target.upload(sid, "version-two.txt", b"e2e-f118 second version separate content\n")
    await target.ok(
        "POST",
        "/knowledge/space/document/link",
        json={"knowledge_file_id": second["id"], "target_document_id": chain["document_id"]},
    )
    linked = await target.ok("GET", f"/knowledge/space/file/{first['id']}/versions")
    assert linked["document_id"] == chain["document_id"] and len(linked["versions"]) == 2
    old_version = next(row for row in linked["versions"] if row["knowledge_file_id"] == first["id"])
    await target.ok("POST", f"/knowledge/space/version/{old_version['version_id']}/set-primary")
    verified = await target.ok("GET", f"/knowledge/space/file/{first['id']}/versions")
    assert next(row for row in verified["versions"] if row["is_primary"])["knowledge_file_id"] == first["id"]


async def test_ac28_ac94_original_deletion_plans_finalize_and_clear_preserves_space(target):
    """AC-28/29/94: no-reference file/folder deletion and clear use original immutable Plans, never force files."""
    sid = (await target.space("delete-files"))["id"]
    file = await target.upload(sid, "delete.txt", b"e2e-f118 delete only this file\n")
    folder = await target.ok("POST", f"/knowledge/space/{sid}/folders", json={"name": target.prefix + "delete-folder"})
    items = [{"id": file["id"], "type": "file"}, {"id": folder["id"], "type": "folder"}]
    await target.error(
        "POST", f"/knowledge/space/{sid}/files/delete/precheck", 422, json={"items": items, "force": True}
    )
    assert {file["id"], folder["id"]}.issubset({row["id"] for row in (await target.files(sid))["data"]})
    command = await target.delete(sid, items=items)
    assert not (await target.files(sid))["data"]
    replay = await target.ok("POST", f"/knowledge/space/{sid}/deletion/confirm", json=command)
    assert replay["state"] == "succeeded" and replay["reused"] is True
    clear_id = (await target.space("clear"))["id"]
    await target.upload(clear_id, "clear.txt", b"e2e-f118 clear content\n")
    settings = await target.ok("GET", f"/knowledge/space/{clear_id}/processing-settings")
    before = await target.info(clear_id)
    await target.delete(clear_id, clear=True)
    after = await target.info(clear_id)
    assert after["id"] == before["id"] and after["model"] == before["model"]
    assert not (await target.files(clear_id))["data"]
    assert (await target.ok("GET", f"/knowledge/space/{clear_id}/processing-settings")) == settings
    delete_id = (await target.space("delete-space"))["id"]
    await target.delete(delete_id)
    await target.error("GET", f"/knowledge/space/{delete_id}/info", 18000)


async def test_ac70_model_removal_prechecks_real_bindings_and_deletes_only_an_unused_fixture(target):
    """AC-70/71/72/73: bound provider is blocked; idle Child provider deletion uses its original confirmation."""
    bound = await target.ok("POST", "/llm/server-removal-plan", json={"server_id": target.server_id})
    assert bound["inspection"]["check_complete"] is True and bound["inspection"]["blocked"] is True
    assert bound["confirmation"]["confirmation_id"] and bound["confirmation"]["plan_digest"]
    payload = deepcopy(target.model_fixture["server"])
    payload.update(name=target.prefix + "unused-provider", share_to_children=False)
    for index, model in enumerate(payload["models"]):
        model["name"] = target.prefix + f"unused-model-{index}"
    idle = await target.ok("POST", "/llm", json=payload)
    facts = await target.ok("GET", "/llm/info", params={"server_id": idle["id"]})
    assert facts["tenant_id"] == target.tenant_id and facts["user_id"] == target.owner_id
    assert len(facts["models"]) == 3
    await target.error(
        "POST",
        "/llm/server-removal-plan",
        19801,
        actor={**target.reader, "X-Management-Tenant": str(target.tenant_id)},
        json={"server_id": idle["id"]},
    )
    await target.remove_exact_server(facts)


async def test_ac17_move_preserves_whole_history_and_same_confirmation(target):
    """AC-17/18/19/20/21/24: cross-space move preserves IDs, all versions and real destination chunks."""
    source = (await target.space("move-source"))["id"]
    destination = (await target.space("move-target", embedding_model_id=target.embedding(1)["id"]))["id"]
    first, second, before = await target.linked_history(source)
    base = f"/knowledge/space/{source}/files/move"
    change = {
        "items": [{"id": second["id"], "type": "file"}],
        "target_space_id": destination,
        "target_folder_id": None,
        "skip_invalid": False,
    }
    review = await target.ok("POST", base + "/precheck", json=change)
    assert review["can_execute"] and review["check_complete"] and not review["invalid_items"]
    command = target.confirmation(review)
    accepted = await target.ok("POST", base + "/confirm", json=command)
    await target.wait_native_job(destination, accepted, "move_index")
    replay = await target.ok("POST", base + "/confirm", json=command)
    assert replay["job_id"] == accepted["job_id"] and replay["reused"] is True
    assert not (await target.files(source))["data"]
    after = await target.ok("GET", f"/knowledge/space/file/{first['id']}/versions")
    assert after["document_id"] == before["document_id"] and after["knowledge_id"] == destination
    assert {row["version_id"] for row in after["versions"]} == {row["version_id"] for row in before["versions"]}
    assert {row["knowledge_file_id"] for row in after["versions"]} == {first["id"], second["id"]}
    actual = await target.file(destination, second["id"])
    assert actual["knowledge_id"] == destination and actual["tenant_id"] == target.tenant_id
    old = await target.ok(
        "GET",
        "/knowledge/chunk",
        params={"knowledge_id": source, "limit": 200},
    )
    new = await target.ok(
        "GET",
        "/knowledge/chunk",
        params={"knowledge_id": destination, "file_ids": [first["id"], second["id"]], "limit": 200},
    )
    assert old["total"] == 0 and new["total"] > 0


async def test_ac25_copy_is_creator_only_and_survives_ordinary_source_delete(target):
    """AC-25/26/27/28: copy creates independent IDs/content and cannot borrow a noncreator's editor Grant."""
    source = (await target.space("copy-source"))["id"]
    first, second, before = await target.linked_history(source)
    context = await target.ok("GET", f"/permissions/resources/knowledge_space/{source}/context")
    await target.ok(
        "POST",
        f"/permissions/resources/knowledge_space/{source}/grants:mutate",
        json={
            "idempotency_key": target.prefix + "copy-editor",
            "expected_resource_version": context["resource_version"],
            "expected_catalog_release_id": context["catalog_release_id"],
            "changes": [{"op": "ADD", "model_key": "editor", "subject": {"type": "user", "id": str(target.reader_id)}}],
        },
    )
    response = await target.request("GET", f"/knowledge/space/{source}/info", actor=target.reader)
    assert response.status_code == 200 and response.json()["status_code"] == 200
    pin = response.headers["x-management-tenant"]
    assert int(pin) == target.tenant_id
    reader = {**target.reader, "X-Management-Tenant": pin}
    change = {"name": target.name("copy-result")}
    await target.error("POST", f"/knowledge/space/{source}/copy/precheck", 19000, actor=reader, json=change)
    review = await target.ok("POST", f"/knowledge/space/{source}/copy/precheck", json=change)
    assert review["can_execute"] and review["check_complete"]
    command = target.confirmation(review)
    accepted = await target.ok("POST", f"/knowledge/space/{source}/copy/confirm", json=command)
    copied = accepted["knowledge"]["id"]
    assert copied != source and accepted["completed"] is False
    await target.wait_native_job(copied, accepted["processing_job"], "space_copy")
    replay = await target.ok("POST", f"/knowledge/space/{source}/copy/confirm", json=command)
    assert (
        replay["knowledge"]["id"] == copied
        and replay["processing_job"]["job_id"] == accepted["processing_job"]["job_id"]
    )
    rows = (await target.files(copied))["data"]
    assert rows and all(row["id"] not in {first["id"], second["id"]} for row in rows)
    chain = await target.ok("GET", f"/knowledge/space/file/{rows[0]['id']}/versions")
    assert chain["document_id"] != before["document_id"] and len(chain["versions"]) == 2
    assert {row["knowledge_file_id"] for row in chain["versions"]}.isdisjoint({first["id"], second["id"]})
    assert not {row["version_id"] for row in chain["versions"]}.intersection(
        row["version_id"] for row in before["versions"]
    )
    assert (await target.info(copied))["is_released"] is False
    await target.error("GET", f"/knowledge/space/{copied}/info", 18040, actor=target.reader)
    # No force: a real unexpected dependency must block this test/cleanup.
    await target.delete(source)
    await target.error("GET", f"/knowledge/space/{source}/info", 18000)
    chunks = await target.ok(
        "GET",
        "/knowledge/chunk",
        params={
            "knowledge_id": copied,
            "file_ids": [row["knowledge_file_id"] for row in chain["versions"]],
            "limit": 200,
        },
    )
    assert chunks["total"] > 0 and "immutable history" in json.dumps(chunks["data"])


async def test_ac43_unconsumed_processing_plan_cannot_apply_after_defaults_change(target):
    """AC-43/44/48/54: cancellation is read-only; a stale rules confirmation fails with exact 18087."""
    sid = (await target.space("stale-plan"))["id"]
    file = await target.upload(sid, "stale.txt", b"e2e-f118 unchanged accepted snapshot\n" * 40)
    base = f"/knowledge/space/{sid}"
    anchor = await target.ok("GET", f"{base}/files/{file['id']}/processing-target")
    jobs = await target.ok("GET", base + "/processing-jobs")
    review = await target.ok(
        "POST",
        base + "/processing-jobs/precheck",
        json={
            "kind": "file_resplit",
            "targets": [anchor],
            "parameters": {"overrides": {"document": {"chunk_size": 256, "chunk_overlap": 16}}},
        },
    )
    assert review["can_execute"] and review["check_complete"]
    assert (await target.file(sid, file["id"]))["split_rule"] == file["split_rule"]
    assert (await target.ok("GET", base + "/processing-jobs")) == jobs
    settings = await target.ok("GET", base + "/processing-settings")
    defaults = deepcopy(settings["effective_defaults"])
    defaults["document"]["chunk_size"] += 1
    await target.ok(
        "PUT",
        base + "/processing-settings",
        json={"expected_config_version": settings["config_version"], "defaults": defaults},
    )
    await target.error("POST", base + "/processing-jobs", 18087, json=target.confirmation(review))
    current = await target.file(sid, file["id"])
    assert current["split_rule"] == file["split_rule"] and current["md5"] == file["md5"] and current["status"] == 2
    assert (await target.ok("GET", base + "/processing-jobs")) == jobs
