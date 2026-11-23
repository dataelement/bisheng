"""History recipe paging retains original identity and validates every tail."""

import copy
import hashlib
import json

import pytest

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application import unification_history_materials as pages
from bisheng.knowledge.application.unification_artifacts import UnificationArtifactStore
from bisheng.knowledge.application.unification_upgrade_materials import canonical, envelope

RUN = "history-pages"


class Storage:
    bucket, tmp_bucket = "private", None

    def __init__(self):
        self.objects, self.gets = {}, []

    async def object_exists(self, *, object_name, **_):
        return object_name in self.objects

    async def put_object(self, *, object_name, file, **_):
        assert len(file) <= 16 * 1024 * 1024
        self.objects[object_name] = file

    async def get_object(self, *, object_name, **_):
        self.gets.append(object_name)
        return self.objects[object_name]


def semantic(count):
    values = []
    for ident in range(count):
        fact = {
            "id": ident + 1,
            "tenant_id": 101,
            "operation_id": ident + 1,
            "phase": "COMMIT",
            "sequence": 0,
            "action": "DELETE",
            "fga_user": "user:*",
            "relation": "permission_enabled",
            "fga_object": f"knowledge_file:{ident + 1}",
            "tuple_fingerprint": "c" * 64,
            "inverse_action": "WRITE",
        }
        values.append(
            {
                "table": "permission_projection_tuple",
                "id": ident + 1,
                "before": hashlib.sha256(b"null").hexdigest(),
                "after": pages._digest(fact),
                "ignore_fields": [],
                "after_fact": fact,
                "before_scope": {},
            }
        )
    return {
        "schema": 1,
        "rows": values,
        "graph_writes": [],
        "graph_deletes": [],
        "logical_ids": [],
        "projection_plans": [],
        "run_id": RUN,
        "writer_contract_version": "f118-v1",
        "environment": "test",
        "planned_at": "2026-11-20T10:00:00",
        "history_sha256": "a" * 64,
        "operator_binding": "fixed",
        "operator_id": 7,
    }


async def test_record_over_sixteen_mib_uses_bounded_verified_pages():
    record, storage = semantic(32000), Storage()
    assert len(canonical(record)) > 16 * 1024 * 1024
    store = UnificationArtifactStore(storage)
    ref = await pages.aput_history_record(store, run_id=RUN, kind="verification", record=record)
    assert await pages.aload_history_record(store, ref, run_id=RUN, kind="verification") == record
    assert all(len(content) <= pages._PAGE_BYTES for content in storage.objects.values())
    assert set(storage.objects) <= set(storage.gets)  # every actual put read back


@pytest.mark.parametrize("damage", ["tail_duplicate", "missing_tail", "reordered", "duplicate_ref"])
async def test_rehashed_page_graph_still_rejects_tail_damage(monkeypatch, damage):
    monkeypatch.setattr(pages, "_LIMIT", 100)
    storage, record = Storage(), semantic(401)
    store = UnificationArtifactStore(storage)
    ref = await pages.aput_history_record(store, run_id=RUN, kind="verification", record=record)
    root = json.loads(storage.objects[ref["object_key"]])["records"][0]
    directory = root["body"]["rows"]
    if damage == "tail_duplicate":
        tail = directory["pages"][-1]
        value = json.loads(storage.objects[tail["ref"]["object_key"]])["records"][0]
        value["items"][0]["id"] = 1
        value["items_sha256"] = pages._digest(value["items"])
        tail["ref"] = await store.aput_canonical(
            run_id=RUN, kind="verification", content=canonical(envelope(RUN, "verification", [value]))
        )
    elif damage == "missing_tail":
        directory["pages"].pop()
    elif damage == "reordered":
        directory["pages"][0], directory["pages"][1] = directory["pages"][1], directory["pages"][0]
    else:
        directory["pages"][1]["ref"] = directory["pages"][0]["ref"]
    changed = await store.aput_canonical(
        run_id=RUN, kind="verification", content=canonical(envelope(RUN, "verification", [root]))
    )
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await pages.aload_history_record(store, changed, run_id=RUN, kind="verification")


async def test_nested_replay_and_receipt_keep_their_original_bodies(monkeypatch):
    monkeypatch.setattr(pages, "_LIMIT", 100)
    store = UnificationArtifactStore(Storage())
    recipe = {
        "schema_version": 1,
        "history_sha256": "a" * 64,
        "executable": True,
        "plan": {
            "purges": [
                {
                    "mode": {"id": 1},
                    "sql": {"permission_grant": []},
                    "objects": ["knowledge_file:1"],
                    "tuples": [
                        {"user": f"user:{index}", "relation": "viewer", "object": "knowledge_file:1"}
                        for index in range(401)
                    ],
                    "incoming": [],
                }
            ],
            "parents": [{"mode": {"id": 2}, "correct": ["folder:1", "parent", "folder:2"], "deletes": []}],
        },
        "replay_sha256": "b" * 64,
    }
    receipt = {
        "schema_version": 1,
        "history_sha256": "a" * 64,
        "semantic_sha256": "b" * 64,
        "verified_fact_count": 401,
        "logical_id_map": [],
        "native_operation_ids": list(range(401)),
        "complete": True,
    }
    for kind, body in (("history_replay", recipe), ("verification", receipt)):
        before = copy.deepcopy(body)
        ref = await pages.aput_history_record(store, run_id=RUN, kind=kind, record=body)
        assert body == before
        assert await pages.aload_history_record(store, ref, run_id=RUN, kind=kind) == before


async def test_unknown_or_oversized_atomic_values_are_not_pretended_pageable(monkeypatch):
    monkeypatch.setattr(pages, "_LIMIT", 100)
    monkeypatch.setattr(pages, "_PAGE_BYTES", 4000)
    store = UnificationArtifactStore(Storage())
    record = semantic(1)
    record["rows"][0]["after_fact"]["unknown_payload"] = "x" * 5000
    with pytest.raises(KnowledgeOperationPlanConflictError) as error:
        await pages.aput_history_record(store, run_id=RUN, kind="verification", record=record)
    assert error.value.kwargs["not_evaluated"] is True
