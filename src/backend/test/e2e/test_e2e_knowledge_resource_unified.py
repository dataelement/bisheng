"""E2E: F030 — 知识资源统一对外 API (v2 filelib).

Runs against a live backend (default: http://localhost:7860). The v2 RPC surface
authenticates as the configured ``default_operator`` (no JWT), so these tests hit
the endpoints directly. Data isolation: all created resources use the
``e2e-f030-`` prefix and are removed in teardown; pre-existing data is untouched.

Covers the deterministic API-contract ACs (type dispatch, cursor shape, type
guards, KB lifecycle). Heavy async-pipeline ACs (real file parse/ingest, retrieval
recall, space cascade tuple cleanup) are validated via the manual checklist.
"""
import os

import httpx
import pytest

from test.e2e.helpers.api import assert_resp_200, assert_resp_error

HOST = os.environ.get("E2E_HOST", "http://localhost:7860")
V2 = f"{HOST}/api/v2/filelib"
PREFIX = "e2e-f030-"

TYPE_NORMAL, TYPE_QA, TYPE_PRIVATE, TYPE_SPACE = 0, 1, 2, 3
ERR_TYPE_UNSUPPORTED = 10962
ERR_INVALID_CURSOR = 10991


def _ok(resp: httpx.Response) -> dict:
    """Assert business success, tolerating HTTP 201 (create/update use status_code=201)."""
    assert resp.status_code in (200, 201), f"HTTP {resp.status_code}: {resp.text[:200]}"
    body = resp.json()
    assert body["status_code"] == 200, f"business error {body['status_code']}: {body.get('status_message')}"
    return body.get("data")


@pytest.fixture(scope="module")
def client():
    with httpx.Client(timeout=30) as c:
        yield c


def _discover_embedding_model(client) -> str | None:
    """Reuse an embedding model id from an existing knowledge base, if any."""
    resp = client.get(V2 + "/", params={"type": TYPE_NORMAL, "page_size": 20})
    data = assert_resp_200(resp)
    for item in data.get("data", []):
        if item.get("model"):
            return str(item["model"])
    return None


def _cleanup(client):
    """Delete any e2e-f030- prefixed resources across KB + space lists."""
    for ktype in (TYPE_NORMAL, TYPE_QA, TYPE_SPACE):
        cursor = None
        while True:
            params = {"type": ktype, "page_size": 50}
            if cursor:
                params["cursor"] = cursor
            body = client.get(V2 + "/", params=params).json()
            if body.get("status_code") != 200:
                break
            data = body["data"]
            for item in data.get("data", []):
                if str(item.get("name", "")).startswith(PREFIX):
                    client.delete(f"{V2}/{item['id']}")
            if data.get("has_more") and data.get("next_cursor"):
                cursor = data["next_cursor"]
            else:
                break


@pytest.fixture(scope="module", autouse=True)
def _isolation(client):
    _cleanup(client)        # clear leftovers from a previous run
    yield
    _cleanup(client)        # clear what this run created


# --------------------------------------------------------------------------- #
# List — cursor shape + type guards (AC-01, AC-02, AC-04, AC-05, AC-06b)
# --------------------------------------------------------------------------- #
def test_ac01_list_kb_cursor_shape(client):
    """AC-01: type=0 list returns PageInfiniteCursorData (no total, INV-6)."""
    data = assert_resp_200(client.get(V2 + "/", params={"type": TYPE_NORMAL, "page_size": 2}))
    assert set(["data", "page_size", "has_more", "next_cursor"]).issubset(data.keys())
    assert "total" not in data
    assert isinstance(data["has_more"], bool)


def test_ac02_list_space_cursor_shape(client):
    """AC-02: type=3 list (mine+joined) also returns cursor shape, no total."""
    data = assert_resp_200(client.get(V2 + "/", params={"type": TYPE_SPACE, "page_size": 2}))
    assert "total" not in data
    assert "has_more" in data and "next_cursor" in data


def test_ac04_list_type2_rejected(client):
    """AC-04: personal KB type=2 is not exposed via v2."""
    assert_resp_error(client.get(V2 + "/", params={"type": TYPE_PRIVATE}), ERR_TYPE_UNSUPPORTED)


def test_ac05_list_invalid_type_rejected(client):
    """AC-05: illegal type rejected with 10962."""
    assert_resp_error(client.get(V2 + "/", params={"type": 9}), ERR_TYPE_UNSUPPORTED)


def test_ac06b_invalid_cursor_rejected(client):
    """AC-06b: malformed cursor → 10991 (no silent fallback to first page)."""
    assert_resp_error(
        client.get(V2 + "/", params={"type": TYPE_NORMAL, "cursor": "not-a-valid-cursor"}),
        ERR_INVALID_CURSOR,
    )


# --------------------------------------------------------------------------- #
# Create — type guards (AC-04, AC-05)
# --------------------------------------------------------------------------- #
def test_ac04_create_type2_rejected(client):
    """AC-04: creating a personal KB (type=2) via v2 is rejected."""
    resp = client.post(V2 + "/", json={"name": PREFIX + "p", "type": TYPE_PRIVATE, "model": "1"})
    assert_resp_error(resp, ERR_TYPE_UNSUPPORTED)


def test_create_invalid_type_rejected(client):
    """AC-05: creating with an illegal type is rejected."""
    resp = client.post(V2 + "/", json={"name": PREFIX + "x", "type": 9, "model": "1"})
    assert_resp_error(resp, ERR_TYPE_UNSUPPORTED)


# --------------------------------------------------------------------------- #
# Update — missing resource (AC-16)
# --------------------------------------------------------------------------- #
def test_ac16_update_missing_resource(client):
    """AC-16: updating an unknown knowledge_id → NotFound (HTTP 404)."""
    resp = client.put(V2 + "/", json={"knowledge_id": 999999999, "name": PREFIX + "nope"})
    assert_resp_error(resp, 404)  # NotFoundError wrapped as body status_code=404


# --------------------------------------------------------------------------- #
# KB lifecycle — create → list → update → delete (AC-07, AC-12, AC-14, AC-30)
# --------------------------------------------------------------------------- #
def test_kb_lifecycle(client):
    """AC-07/12/14/30: create doc KB, see it in cursor list, update, delete."""
    model_id = _discover_embedding_model(client)
    if not model_id:
        pytest.skip("no embedding model available in this environment")

    # AC-07 + AC-12: create; auth_type/is_released ignored for KB.
    name = PREFIX + "kb"
    created = _ok(client.post(V2 + "/", json={
        "name": name, "type": TYPE_NORMAL, "model": model_id,
        "description": "d1", "auth_type": "approval", "is_released": True,
    }))
    kid = created["id"]
    try:
        assert created["type"] == TYPE_NORMAL
        assert created["is_released"] is False          # AC-12 ignored for KB
        assert created["auth_type"] == "public"

        # AC-14: update name + description.
        updated = _ok(client.put(V2 + "/", json={
            "knowledge_id": kid, "name": name + "-v2", "description": "d2",
        }))
        assert updated["name"] == name + "-v2"
        assert updated["description"] == "d2"
    finally:
        # AC-30: delete dispatch for KB.
        assert_resp_200(client.delete(f"{V2}/{kid}"))

    # Verify gone: it must not appear in the (small) list pages we scan.
    body = client.get(V2 + "/", params={"type": TYPE_NORMAL, "name": name, "page_size": 50}).json()
    names = [i.get("name") for i in body.get("data", {}).get("data", [])]
    assert (name + "-v2") not in names


def test_ac11_duplicate_name_rejected(client):
    """AC-11: creating a KB with a duplicate name → KnowledgeExistError (10900)."""
    model_id = _discover_embedding_model(client)
    if not model_id:
        pytest.skip("no embedding model available in this environment")
    name = PREFIX + "dup"
    first = _ok(client.post(V2 + "/", json={
        "name": name, "type": TYPE_NORMAL, "model": model_id}))
    try:
        assert_resp_error(
            client.post(V2 + "/", json={"name": name, "type": TYPE_NORMAL, "model": model_id}),
            10900,
        )
    finally:
        client.delete(f"{V2}/{first['id']}")


# --------------------------------------------------------------------------- #
# Space lifecycle — create → upload → file list (cursor) → keyword search → delete
# (AC-09, AC-22, AC-27, AC-30 + 偏差3 keyword search)
# --------------------------------------------------------------------------- #
def test_space_create_upload_list(client):
    """AC-09/22/27/30: create space (no model), upload a file, no-keyword cursor list, delete.

    Note: keyword search over this brand-new space is NOT asserted here — without a
    Celery worker the uploaded file isn't indexed into ES yet, so the keyword path
    is exercised separately against an already-populated space
    (``test_space_keyword_search_existing``).
    """
    resp = client.post(V2 + "/", json={"name": PREFIX + "space", "type": TYPE_SPACE})
    body = resp.json()
    if body.get("status_code") != 200:
        pytest.skip(f"space create unavailable: {body.get('status_code')} {body.get('status_message')}")
    sid = body["data"]["id"]
    try:
        # AC-22: upload a file to the space root (parent_id omitted).
        up = client.post(
            f"{V2}/file/{sid}",
            files={"file": (PREFIX + "searchdoc.txt", b"hello f030 e2e search content", "text/plain")},
        )
        assert up.json().get("status_code") == 200, f"upload failed: {up.text[:200]}"

        # AC-27: space file list (no keyword) → cursor shape + writeable, no total;
        # the uploaded file row is present immediately (status may be processing).
        data = assert_resp_200(client.get(f"{V2}/file/list", params={"knowledge_id": sid, "page_size": 20}))
        assert "has_more" in data and "next_cursor" in data and "writeable" in data
        assert "total" not in data
        names = [i.get("file_name") for i in data.get("data", [])]
        assert any("searchdoc" in (n or "") for n in names), f"uploaded file missing: {names}"
    finally:
        client.delete(f"{V2}/{sid}")  # AC-30: space delete dispatch (cascade)


def test_qa_add_then_clear_removes_pairs(client):
    """add_qa tenant-context fix + QA clear fix: add a QA pair, clear, verify gone.

    Exercises two F030 follow-up fixes end-to-end:
    - add_qa now seeds the tenant ContextVar (no more 20004 in multi-tenant)
    - clear on a QA KB now removes the QAKnowledge rows (not just files/vectors)
    """
    model_id = _discover_embedding_model(client)
    if not model_id:
        pytest.skip("no embedding model available")
    kb = _ok(client.post(V2 + "/", json={"name": PREFIX + "qa", "type": TYPE_QA, "model": model_id}))
    kid = kb["id"]
    try:
        added = assert_resp_200(client.post(V2 + "/add_qa", json={
            "knowledge_id": kid,
            "data": [{"question": PREFIX + "q", "answer": ["a1"]}],
        }))
        assert added and added[0].get("id"), f"add_qa returned no id: {added}"
        qa_id = added[0]["id"]

        # present before clear
        d1 = assert_resp_200(client.get(V2 + "/detail_qa", params={"id": qa_id}))
        assert d1 and d1.get("id") == qa_id

        # clear → QA pairs must be removed
        assert_resp_200(client.delete(f"{V2}/clear/{kid}"))
        d2 = client.get(V2 + "/detail_qa", params={"id": qa_id}).json()
        assert not d2.get("data"), f"QA pair still present after clear: {d2.get('data')}"
    finally:
        client.delete(f"{V2}/{kid}")


def test_retrieve_accepts_knowledge_base(client):
    """F030 fix: /retrieve must accept a knowledge base id (type 0/1), not only spaces.

    Previously a KB id returned 18000 (Knowledge Space does not exist). Now it
    dispatches to the KB retrieval path → 200 with the RetrieveResp shape
    (chunks list may be empty depending on indexed content).
    """
    kbs = assert_resp_200(client.get(V2 + "/", params={"type": TYPE_NORMAL, "page_size": 20}))
    # Find a KB whose retrieve no longer fails with the space-only 18000 guard.
    # (Empty KBs may 500 with ES index_not_found — a data-state issue, not the
    #  type-dispatch we're verifying — so iterate to a populated/indexed one.)
    verified = False
    for kb in kbs.get("data", []):
        resp = client.post(V2 + "/retrieve", json={
            "query": "测试", "knowledge_base_ids": [kb["id"]], "top_k": 3,
        })
        body = resp.json()
        assert body["status_code"] != 18000, "KB retrieve still hitting space-only guard (18000)"
        if body["status_code"] == 200:
            assert "chunks" in body["data"] and "total" in body["data"]
            assert isinstance(body["data"]["chunks"], list)
            verified = True
            break
    if not verified:
        pytest.skip("no indexed knowledge base available to confirm a 200 retrieve")


def test_clear_kb_keeps_index_queryable(client):
    """Option A: after clear, a KB stays queryable (retrieve 200, empty) — not 500 index_not_found.

    Create a fresh doc KB (creation builds the index), clear it (drops + recreates
    the empty index), then retrieve → must be 200 with an empty chunks list.
    """
    model_id = _discover_embedding_model(client)
    if not model_id:
        pytest.skip("no embedding model available")
    kb = _ok(client.post(V2 + "/", json={"name": PREFIX + "clearidx", "type": TYPE_NORMAL, "model": model_id}))
    kid = kb["id"]
    try:
        assert_resp_200(client.delete(f"{V2}/clear/{kid}"))
        data = assert_resp_200(client.post(V2 + "/retrieve", json={
            "query": "测试", "knowledge_base_ids": [kid], "top_k": 3,
        }))
        assert data["chunks"] == []  # queryable, empty — index exists, no index_not_found 500
    finally:
        client.delete(f"{V2}/{kid}")


def test_retrieve_rejects_qa_kb(client):
    """Option B: QA knowledge base retrieval is not yet supported → 10962.

    QA stores answer-oriented data with a different schema; routing it through the
    document path would return mismatched results, so it's explicitly rejected
    until a dedicated QA recall path lands.
    """
    model_id = _discover_embedding_model(client)
    if not model_id:
        pytest.skip("no embedding model available")
    qa = _ok(client.post(V2 + "/", json={"name": PREFIX + "qaret", "type": TYPE_QA, "model": model_id}))
    kid = qa["id"]
    try:
        resp = client.post(V2 + "/retrieve", json={
            "query": "测试", "knowledge_base_ids": [kid], "top_k": 3,
        })
        assert_resp_error(resp, ERR_TYPE_UNSUPPORTED)
    finally:
        client.delete(f"{V2}/{kid}")


def test_space_keyword_search_existing(client):
    """偏差3: keyword search over a space routes to search → cursor shape, no total.

    Verified against an already-populated space (with an indexed ES index) so the
    result is independent of Celery/ES readiness for freshly-uploaded files.
    """
    spaces = assert_resp_200(client.get(V2 + "/", params={"type": TYPE_SPACE, "page_size": 20}))
    candidate = None
    for sp in spaces.get("data", []):
        fl = client.get(f"{V2}/file/list", params={"knowledge_id": sp["id"], "page_size": 1}).json()
        if fl.get("status_code") == 200 and fl["data"].get("data"):
            candidate = sp["id"]
            break
    if candidate is None:
        pytest.skip("no populated knowledge space available for keyword search")

    resp = client.get(f"{V2}/file/list", params={"knowledge_id": candidate, "keyword": "测试", "page_size": 5})
    sdata = assert_resp_200(resp)
    assert "has_more" in sdata and "next_cursor" in sdata
    assert "total" not in sdata          # cursor contract (INV-6), even via search path
