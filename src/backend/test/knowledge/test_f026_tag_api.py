"""T053 bridge: actual local ref persistence + recorded WeKnora v1 wire shapes; no deployment."""

from contextlib import asynccontextmanager
from dataclasses import replace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
from bisheng.knowledge.api.endpoints.provider_tags import ManualTagEdit
from bisheng.knowledge.application import provider_tag_reads as bridge
from bisheng.knowledge.domain.repositories.provider_retrieval_repository import Route
from test.knowledge.test_f026_tag import store  # noqa: F401 (real scoped Ref repository fixture)

ROUTE = Route(7, 8, "weknora", 1, 4, "7", "remote-kb", 2, 1)
FILE = ("remote-doc", 22, 122, 3, 1, 1, "local", 2)
VOCAB = "knowledge-bases/remote-kb/tags"
MANUAL = "knowledge-bases/remote-kb/documents/remote-doc/manual-tags-v1"


def ok(data):
    return httpx.Response(200, json={"success": True, "data": data})


def selection(ids, revision=6, **fields):
    return ok(
        dict(
            {
                "contract": "manual-tags-v1",
                "tenant_id": 7,
                "knowledge_base_id": "remote-kb",
                "knowledge_id": "remote-doc",
                "tag_ids": ids,
                "revision": revision,
            },
            **fields,
        )
    )


@pytest.fixture
async def env(store, monkeypatch):  # noqa: F811
    client, service = AsyncMock(), AsyncMock()

    @asynccontextmanager
    async def bound(route):
        assert route == ROUTE
        yield client

    resolve = AsyncMock(return_value=ROUTE)
    monkeypatch.setattr(bridge, "instance_client", bound)
    monkeypatch.setattr(bridge, "resolve_space_route", resolve)
    mapping = AsyncMock()
    mapping.load_candidates.return_value = ([FILE], [])

    def request(file_id=None, write=False):
        app = bridge.TagRequest(service, 8, 1, file_id, write=write)
        app.repo, app.mapping = store[0], mapping
        return app

    return request, client, service, resolve, mapping


async def test_page_550_and_save_refs_across_pages(env):
    request, client, _, _, _ = env

    async def get(path, params=None):
        if path == MANUAL:
            return selection(["remote-0"])
        assert path == VOCAB and params["page_size"] == 50
        start = (params["page"] - 1) * 50
        tags = [
            {
                "id": f"remote-{i}",
                "knowledge_base_id": "remote-kb",
                "tenant_id": 7,
                "name": f"word {i}",
                "knowledge_count": 871,
                "seq_id": i,
                "chunk_count": 900,
            }
            for i in range(start, start + 50)
        ]
        return ok({"data": tags, "total": 550, "page": params["page"], "page_size": 50})

    client.get.side_effect = get
    first = await request().page(1, 50)
    last = await request().page(11, 50)
    assert last["total"] == 550 and last["generation"] == 1 and last["data"][-1]["name"] == "word 549"
    assert set(last["data"][-1]) == {"tag_ref_id", "name"}
    refs = [first["data"][0]["tag_ref_id"], last["data"][-1]["tag_ref_id"]]
    before = await request(22).file_selection()
    assert before["tag_ref_ids"] == refs[:1]
    assert (
        set(before) == {"generation", "tag_ref_ids", "edit_contract", "revision"}
        and before["edit_contract"] == "manual-tags-v1"
    )
    client.put.return_value = selection(["remote-549", "remote-0"], revision=7)
    after = await request(22, True).file_selection(
        ManualTagEdit(generation=1, mode="replace", tag_ref_ids=refs, expected_revision=before["revision"])
    )
    assert after["tag_ref_ids"] == refs and after["revision"] != before["revision"]
    client.put.assert_awaited_once_with(
        MANUAL, json={"mode": "replace", "tag_ids": ["remote-0", "remote-549"], "expected_revision": 6}
    )


async def test_cas_conflict_never_replays_releases_slot_and_clear_is_explicit(env):
    request, client, _, _, _ = env
    client.get.return_value = selection(["remote-0"])
    before = await request(22).file_selection()
    clear = ManualTagEdit(generation=1, mode="clear", tag_ref_ids=[], expected_revision=before["revision"])
    client.put.return_value = httpx.Response(409)
    with pytest.raises(bridge.KnowledgeOperationPlanConflictError) as exc:
        await request(22, True).file_selection(clear)
    assert exc.value.Code == 10998
    client.put.assert_awaited_once_with(MANUAL, json={"mode": "clear", "tag_ids": [], "expected_revision": 6})
    client.get.return_value = selection(["remote-0"], revision=7)
    with pytest.raises(bridge.KnowledgeOperationPlanConflictError):
        await request(22, True).file_selection(clear)
    assert client.put.await_count == 1
    clear.expected_revision = (await request(22).file_selection())["revision"]
    client.put.return_value = selection([], revision=8)
    after = await request(22, True).file_selection(clear)
    assert after["tag_ref_ids"] == []
    client.get.return_value = selection([], revision=8)
    assert after == await request(22).file_selection()


@pytest.mark.parametrize(
    "bad",
    [
        selection(None),
        selection([], knowledge_id="wrong"),
        selection([], contract="legacy"),
        selection([], tenant_id=70),
        selection([], revision=True),
    ],
)
async def test_unproven_contract_is_never_a_write_or_empty(bad, env):
    request, client, _, _, _ = env
    client.get.return_value = bad
    for write in (False, True):
        with pytest.raises(bridge.ProviderFeatureUnavailable) as exc:
            await request(22, write).file_selection(
                ManualTagEdit(generation=1, mode="clear", tag_ref_ids=[], expected_revision=0) if write else None
            )
        assert exc.value.Code == 18089
    assert all(call.args == (MANUAL,) for call in client.get.await_args_list)
    client.put.assert_not_awaited()


async def test_absent_route_falls_back_but_never_invents_an_empty_selection(env):
    """A 404 alone is not proof of 'no tags': the fallback must read a real list first."""
    request, client, _, _, _ = env
    client.get.return_value = httpx.Response(404)
    for write in (False, True):
        with pytest.raises(bridge.ProviderFeatureUnavailable) as exc:
            await request(22, write).file_selection(
                ManualTagEdit(generation=1, mode="clear", tag_ref_ids=[], expected_revision=0) if write else None
            )
        assert exc.value.Code == 18089
    assert all(call.args == (MANUAL,) or call.args == ("knowledge/remote-doc",) for call in client.get.await_args_list)
    client.put.assert_not_awaited()


async def test_permission_generation_and_file_version_rechecked(env):
    request, client, service, resolve, mapping = env
    client.get.return_value = selection([])
    before = await request(22).file_selection()
    service._require_file_action.assert_awaited_with(22, "visible", space_id=8)
    clear = ManualTagEdit(generation=1, mode="clear", tag_ref_ids=[], expected_revision=before["revision"])
    service._require_file_action.side_effect = SpacePermissionDeniedError()
    client.get.reset_mock()
    with pytest.raises(SpacePermissionDeniedError):
        await request(22, True).file_selection(clear)
    service._require_file_action.assert_awaited_with(22, "rename", space_id=8)
    client.get.assert_not_awaited()
    service._require_file_action.side_effect = None
    resolve.return_value = replace(ROUTE, generation=2)
    with pytest.raises(bridge.KnowledgeOperationPlanConflictError):
        await request(22, True).file_selection(clear)
    client.get.assert_not_awaited()
    resolve.return_value = ROUTE
    # Same remote revision after a local version change: stale prior UI selection must not write.
    newer = (*FILE[:2], 812, *FILE[3:])
    mapping.load_candidates.return_value = ([newer], [])
    with pytest.raises(bridge.KnowledgeOperationPlanConflictError):
        await request(22, True).file_selection(clear)
    # An epoch change specifically inside the occupied write slot is a proved non-send.
    mapping.load_candidates.side_effect = [([FILE], [])] * 3 + [([newer], [])]
    with pytest.raises(bridge.KnowledgeOperationPlanConflictError):
        await request(22, True).file_selection(clear)
    client.put.assert_not_awaited()
    mapping.load_candidates.side_effect = None
    mapping.load_candidates.return_value = ([FILE], [])
    client.put.return_value = selection([])
    assert (await request(22, True).file_selection(clear))["revision"] == before["revision"]


async def test_whole_set_fallback_reads_writes_and_confirms_without_manual_route(env):
    """An upstream without `manual-tags-v1` still supports add/edit through its whole-set route."""
    request, client, _, _, _ = env
    tags = [
        {"id": "remote-a", "knowledge_base_id": "remote-kb", "tenant_id": 7, "name": "A"},
        {"id": "remote-b", "knowledge_base_id": "remote-kb", "tenant_id": 7, "name": "B"},
    ]
    state = {"ids": ["remote-a"]}

    def detail(ids):
        return {
            "id": "remote-doc",
            "knowledge_base_id": "remote-kb",
            "tenant_id": 7,
            "tags": [tag for tag in tags if tag["id"] in ids],
        }

    async def get(path, params=None):
        if path == MANUAL:
            return httpx.Response(404)
        assert path == "knowledge/remote-doc"
        return ok(detail(state["ids"]))

    async def put(path, json=None):
        assert path == "knowledge/tags"
        assert (json["kb_id"], list(json["updates"])) == ("remote-kb", ["remote-doc"])
        state["ids"] = json["updates"]["remote-doc"]
        return httpx.Response(200, json={"success": True})

    client.get.side_effect = get
    client.put.side_effect = put
    before = await request(22).file_selection()
    assert before["edit_contract"] == "whole-tags-v1" and len(before["tag_ref_ids"]) == 1
    client.put.assert_not_awaited()

    state["ids"] = ["remote-a", "remote-b"]  # remote moved on after the read
    with pytest.raises(bridge.KnowledgeOperationPlanConflictError) as stale:
        await request(22, True).file_selection(
            ManualTagEdit(generation=1, mode="clear", tag_ref_ids=[], expected_revision=before["revision"])
        )
    assert stale.value.Code == 10998
    client.put.assert_not_awaited()

    fresh = await request(22).file_selection()
    assert len(fresh["tag_ref_ids"]) == 2
    after = await request(22, True).file_selection(
        ManualTagEdit(
            generation=1, mode="replace", tag_ref_ids=fresh["tag_ref_ids"], expected_revision=fresh["revision"]
        )
    )
    assert after["edit_contract"] == "whole-tags-v1"
    assert sorted(state["ids"]) == ["remote-a", "remote-b"]
    assert after["tag_ref_ids"] == fresh["tag_ref_ids"]
    # Clear is explicit and lands as an empty whole set, confirmed by a re-read.
    cleared = await request(22, True).file_selection(
        ManualTagEdit(generation=1, mode="clear", tag_ref_ids=[], expected_revision=after["revision"])
    )
    assert cleared["tag_ref_ids"] == [] and state["ids"] == []


@pytest.mark.parametrize("tags", [{"missing": True}, "not-a-list"])
async def test_whole_set_fallback_refuses_an_unproven_tag_list(tags, env):
    request, client, _, _, _ = env
    detail = {"id": "remote-doc", "knowledge_base_id": "remote-kb", "tenant_id": 7}
    if tags != {"missing": True}:
        detail["tags"] = tags
    client.get.side_effect = lambda path, params=None: httpx.Response(404) if path == MANUAL else ok(detail)
    with pytest.raises(bridge.ProviderFeatureUnavailable) as exc:
        await request(22).file_selection()
    assert exc.value.Code == 18089
    client.put.assert_not_awaited()


async def test_whole_set_fallback_lets_an_untagged_document_receive_its_first_tag(env):
    """v0.9.0 marshals a nil relation slice as null; that is its 'no tags', not a missing proof."""
    request, client, _, _, _ = env
    state = {"ids": None}

    async def get(path, params=None):
        if path == MANUAL:
            return httpx.Response(404)
        if path == VOCAB:
            return ok(
                {
                    "data": [{"id": "remote-a", "knowledge_base_id": "remote-kb", "tenant_id": 7, "name": "A"}],
                    "total": 1,
                    "page": 1,
                    "page_size": 50,
                }
            )
        tags = (
            None
            if state["ids"] is None
            else [{"id": tag, "knowledge_base_id": "remote-kb", "tenant_id": 7} for tag in state["ids"]]
        )
        return ok({"id": "remote-doc", "knowledge_base_id": "remote-kb", "tenant_id": 7, "tags": tags})

    async def put(path, json=None):
        assert path == "knowledge/tags"
        state["ids"] = json["updates"]["remote-doc"]
        return httpx.Response(200, json={"success": True})

    client.get.side_effect = get
    client.put.side_effect = put
    ref = (await request().page(1, 50))["data"][0]["tag_ref_id"]
    before = await request(22).file_selection()
    assert before["edit_contract"] == "whole-tags-v1" and before["tag_ref_ids"] == []
    after = await request(22, True).file_selection(
        ManualTagEdit(generation=1, mode="replace", tag_ref_ids=[ref], expected_revision=before["revision"])
    )
    assert state["ids"] == ["remote-a"] and after["tag_ref_ids"] == [ref]


async def test_labels_read_the_document_detail_once_and_never_require_the_manual_route(env):
    """The file list shows names from the document detail; it must not need the edit contract."""
    request, client, _, _, _ = env
    client.get.return_value = ok(
        {
            "id": "remote-doc",
            "knowledge_base_id": "remote-kb",
            "tenant_id": 7,
            "tags": [
                {"id": "remote-a", "knowledge_base_id": "remote-kb", "tenant_id": 7, "name": "测试"},
                {"id": "remote-b", "knowledge_base_id": "remote-kb", "tenant_id": 7, "name": "测试2"},
            ],
        }
    )
    assert await request(22).file_labels() == {"names": ["测试", "测试2"], "generation": 1}
    # One remote read, and the edit-only route is never touched.
    assert [call.args for call in client.get.await_args_list] == [("knowledge/remote-doc",)]
    client.put.assert_not_awaited()


@pytest.mark.parametrize(
    "detail",
    [
        {"id": "remote-doc", "knowledge_base_id": "remote-kb", "tenant_id": 7},
        {"id": "remote-doc", "knowledge_base_id": "remote-kb", "tenant_id": 7, "tags": "x"},
        {"id": "remote-doc", "knowledge_base_id": "other-kb", "tenant_id": 7, "tags": []},
        {
            "id": "remote-doc",
            "knowledge_base_id": "remote-kb",
            "tenant_id": 7,
            "tags": [{"id": "remote-a", "knowledge_base_id": "remote-kb", "tenant_id": 7}],
        },
    ],
)
async def test_labels_fail_closed_on_an_unproven_details_payload(detail, env):
    request, client, _, _, _ = env
    client.get.return_value = ok(detail)
    with pytest.raises(bridge.ProviderFeatureUnavailable) as exc:
        await request(22).file_labels()
    assert exc.value.Code == 18089
    client.put.assert_not_awaited()


async def test_uncertain_write_keeps_slot_and_never_returns_invented_success(env):
    request, client, _, _, _ = env
    client.get.return_value = selection([])
    before = await request(22).file_selection()
    clear = ManualTagEdit(generation=1, mode="clear", tag_ref_ids=[], expected_revision=before["revision"])
    client.put.return_value = selection(["not-requested"])
    with pytest.raises(bridge.ProviderFeatureUnavailable):
        await request(22, True).file_selection(clear)
    with pytest.raises(bridge.KnowledgeOperationPlanConflictError):
        await request(22, True).file_selection(clear)
    assert client.put.await_count == 1


@pytest.mark.parametrize(
    "patch",
    [
        {"mode": "append"},
        {"tag_ref_ids": [1]},
        {"mode": "replace"},
        {"mode": "replace", "tag_ref_ids": [True]},
        {"generation": True},
        {"expected_revision": -1},
        {"remote_id": "x"},
        {"tag_ref_ids": list(range(1, 52)), "mode": "replace"},
    ],
)
def test_no_implicit_clear_or_remote_id_input(patch):
    with pytest.raises(ValidationError):
        ManualTagEdit(**dict({"generation": 1, "expected_revision": 0, "mode": "clear", "tag_ref_ids": []}, **patch))


async def test_registered_routes_and_envelope(env, monkeypatch):
    from fastapi import FastAPI

    from bisheng.knowledge.api.endpoints import provider_tags as endpoint
    from bisheng.knowledge.api.router import knowledge_space_router

    request, client, service, _, _ = env
    app = FastAPI()
    app.include_router(knowledge_space_router, prefix="/api/v1")
    app.dependency_overrides[endpoint.get_knowledge_space_service] = lambda: service

    def scoped(svc, space, gen, file=None, write=False):
        assert (svc, space, gen) == (service, 8, 1)
        return request(file, write)

    monkeypatch.setattr(endpoint, "TagRequest", scoped)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as browser:
        base = "/api/v1/knowledge/space/8"
        file = base + "/files/22/provider-tags"
        assert (await browser.get(file)).status_code == 422
        assert (
            await browser.get(base + "/provider-tags", params={"generation": 1, "page_size": 201})
        ).status_code == 422
        client.get.return_value = ok({"page": 1, "page_size": 50, "total": 0, "data": []})
        page = (await browser.get(base + "/provider-tags", params={"generation": 1})).json()
        assert page["status_code"] == 200 and page["data"] == {"total": 0, "data": [], "generation": 1}
        client.get.return_value = selection([])
        state = (await browser.get(file, params={"generation": 1})).json()["data"]
        command = {"generation": 1, "expected_revision": state["revision"], "mode": "clear", "tag_ref_ids": []}
        client.put.return_value = selection([])
        assert (await browser.put(file, json=command)).json()["data"] == state
        assert (await browser.put(file, json={**command, "remote_id": "x"})).status_code == 422
        client.post.return_value = ok(
            {"id": "remote-word", "knowledge_base_id": "remote-kb", "tenant_id": 7, "name": "检修"}
        )
        created = (await browser.post(base + "/provider-tags", json={"generation": 1, "name": "  检修  "})).json()
        assert created["status_code"] == 200
        assert created["data"]["name"] == "检修" and type(created["data"]["tag_ref_id"]) is int
        assert (await browser.post(base + "/provider-tags", json={"generation": 1, "name": "   "})).status_code == 422
        assert (
            await browser.post(base + "/provider-tags", json={"generation": 1, "name": "x", "remote_id": "y"})
        ).status_code == 422
        assert (await browser.post(base + "/provider-tags", json={"generation": 0, "name": "x"})).status_code == 422


async def test_vocab_mismatched_scope_no_ref_issued(env):
    request, client, service, _, _ = env
    client.get.return_value = ok(
        {
            "page": 1,
            "page_size": 50,
            "total": 1,
            "data": [{"knowledge_base_id": "elsewhere", "tenant_id": 7, "id": "x", "name": "wrong"}],
        }
    )
    with pytest.raises(bridge.ProviderFeatureUnavailable):
        await request().page(1, 50)
    service._require_action.assert_awaited_with("knowledge_space", 8, "visible")
    service._require_action.side_effect = SpacePermissionDeniedError()
    client.get.reset_mock()
    with pytest.raises(SpacePermissionDeniedError):
        await request().page(1, 50)
    client.get.assert_not_awaited()


def word(name="检修", remote="remote-word", **fields):
    return ok(dict({"id": remote, "knowledge_base_id": "remote-kb", "tenant_id": 7, "name": name}, **fields))


async def test_create_word_requires_space_management_and_returns_a_local_ref(env):
    request, client, service, _, _ = env
    client.post.return_value = word()
    created = await request().create_word("检修")
    service._require_action.assert_any_await("knowledge_space", 8, "edit")
    client.post.assert_awaited_once_with(VOCAB, json={"name": "检修"})
    assert created["name"] == "检修" and created["generation"] == 1
    # Browser gets a local safe integer, never the remote tag identity.
    assert type(created["tag_ref_id"]) is int and 0 < created["tag_ref_id"] < 2**53
    assert created["tag_ref_id"] != "remote-word"
    service._require_action.side_effect = SpacePermissionDeniedError()
    client.post.reset_mock()
    with pytest.raises(SpacePermissionDeniedError):
        await request().create_word("检修")
    client.post.assert_not_awaited()


async def test_duplicate_word_reuses_the_existing_identity(env):
    request, client, _, _, _ = env
    client.post.return_value = httpx.Response(409)
    client.get.return_value = ok(
        {
            "page": 1,
            "page_size": 200,
            "total": 1,
            "data": [{"knowledge_base_id": "remote-kb", "tenant_id": 7, "id": "remote-old", "name": "检修"}],
        }
    )
    created = await request().create_word("检修")
    client.get.assert_awaited_once_with(VOCAB, params={"page": 1, "page_size": 200, "keyword": "检修"})
    assert created["name"] == "检修" and created["tag_ref_id"] > 0
    # Same name, same local reference: one tag per name.
    assert created == await request().create_word("检修")


@pytest.mark.parametrize(
    "bad",
    [
        word(name="别的"),
        word(remote="bad id!"),
        word(tenant_id=70),
        word(knowledge_base_id="other"),
        httpx.Response(200),
    ],
)
async def test_unproven_word_creation_is_never_a_ref(bad, env):
    request, client, _, _, _ = env
    client.post.return_value = bad
    with pytest.raises(bridge.ProviderFeatureUnavailable) as exc:
        await request().create_word("检修")
    assert exc.value.Code == 18089


async def test_word_creation_rejects_an_incompatible_generation(env):
    request, client, _, resolve, _ = env
    resolve.return_value = replace(ROUTE, generation=2)
    with pytest.raises(bridge.KnowledgeOperationPlanConflictError):
        await request().create_word("检修")
    client.post.assert_not_awaited()
