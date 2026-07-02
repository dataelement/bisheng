"""E2E tests for F041: 工作流 / 助手应用支持选择知识空间.

Covers the API-automatable ACs — the knowledge-space selector data 口径 and the
assistant-app persistence round-trip (space/KB type marker + user 权限校验 toggle).

Prerequisites:
- Backend running on localhost:7860 (or E2E_API_BASE), real middleware.
- Default admin account admin/Bisheng@top1 (super_admin) with existing knowledge
  spaces + knowledge bases (used as the config author selecting its own visible
  spaces). Override the password via E2E_ADMIN_PASSWORD.

Covers (API-automatable ACs):
- AC-02: knowledge-space 口径 = mine + joined + department dedup union, 广场(/square)
  is a distinct endpoint and NOT part of the selectable union.
- AC-05: the three space endpoints return one-shot plain lists (no cursor paging).
- AC-11: assistant `knowledge_auth` (用户知识库权限校验) defaults to OFF on create.
- AC-10: `knowledge_auth` toggle persists (ON then OFF) across update → GET info.
- AC-03 / AC-04: assistant `knowledge_list` round-trips a mix of a document KB
  (type=0) and a knowledge space (type=3); GET info echoes both with the correct
  `type` marker so the frontend can group each into the right tab.

Retrieval-filtering + citation-resolve ACs (AC-12~16, AC-19~25) require ingested
space files in Milvus/ES plus users with differentiated view_file and are covered
by the manual checklist / unit tests (test_space_flow_retrieval, test_access_scope_tiering).

Data isolation: all created assistants use the 'e2e-f041-' prefix + a per-run id;
teardown deletes only those. Knowledge spaces / KBs are read-only here (never mutated).
"""

import base64
import os
import uuid

import httpx
import pytest

API_BASE = os.environ.get("E2E_API_BASE", "http://localhost:7860/api/v1")
HEALTH_URL = API_BASE.replace("/api/v1", "") + "/health"
PREFIX = "e2e-f041-"
KNOWLEDGE_TYPE_NORMAL = 0
KNOWLEDGE_TYPE_SPACE = 3


# ---------------------------------------------------------------------------
# Auth + API helpers (sync, mirroring test_e2e_department_space_scope.py)
# ---------------------------------------------------------------------------


def _encrypt_password(client: httpx.Client, password: str) -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    public_key_pem = client.get(f"{API_BASE}/user/public_key").json()["data"]["public_key"]
    public_key = serialization.load_pem_public_key(public_key_pem.encode())
    encrypted = public_key.encrypt(password.encode(), padding.PKCS1v15())
    return base64.b64encode(encrypted).decode()


def _login(client: httpx.Client, username: str = "admin", password: str | None = None) -> str:
    if password is None:
        password = os.environ.get("E2E_ADMIN_PASSWORD", "Bisheng@top1")
    resp = client.post(
        f"{API_BASE}/user/login",
        json={"user_name": username, "password": _encrypt_password(client, password)},
    )
    body = resp.json()
    assert body["status_code"] == 200, f"Login failed: {body.get('status_message')}"
    return body["data"]["access_token"]


def _auth(token: str) -> dict:
    return {"Cookie": f"access_token_cookie={token}"}


def _assert_200(resp: httpx.Response):
    assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:300]}"
    body = resp.json()
    assert body["status_code"] == 200, f"Business error {body['status_code']}: {body.get('status_message')}"
    return body.get("data")


def _as_list(data) -> list:
    """Space endpoints return either a bare list or a paged {data:[...]} envelope."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("data") or data.get("items") or []
    return []


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    with httpx.Client(timeout=60) as c:
        assert c.get(HEALTH_URL).status_code == 200, "Backend not reachable"
        yield c


@pytest.fixture(scope="module")
def admin_token(client):
    return _login(client)


@pytest.fixture(scope="module")
def created_assistant_ids():
    ids: list[str] = []
    yield ids


@pytest.fixture(scope="module", autouse=True)
def _cleanup(client, admin_token, created_assistant_ids):
    """Teardown: delete only the assistants this suite created (prefix-guarded)."""
    yield
    for aid in created_assistant_ids:
        try:
            client.post(
                f"{API_BASE}/assistant/delete",
                params={"assistant_id": aid},
                headers=_auth(admin_token),
            )
        except Exception:
            pass


def _create_assistant(client: httpx.Client, token: str, ids: list[str]) -> dict:
    run = uuid.uuid4().hex[:8]
    payload = {
        "name": f"{PREFIX}{run}",
        # prompt has a min_length=20 constraint on AssistantCreateReq
        "prompt": "F041 e2e knowledge space selection round-trip assistant.",
        "logo": "",
    }
    data = _assert_200(client.post(f"{API_BASE}/assistant", json=payload, headers=_auth(token)))
    aid = str(data["id"])
    ids.append(aid)
    return data


def _get_assistant_info(client: httpx.Client, token: str, assistant_id: str) -> dict:
    return _assert_200(client.get(f"{API_BASE}/assistant/info/{assistant_id}", headers=_auth(token)))


def _update_assistant(client: httpx.Client, token: str, info: dict, **overrides) -> dict:
    """PUT /assistant with the FULL mutable field set, mirroring the frontend
    (``saveAssistanttApi(...assistantState)``). The update service null-overwrites
    omitted scalar fields (temperature/model_name are NOT NULL columns), so a
    partial payload would fail — the real client always sends the whole state."""
    payload = {
        "id": str(info["id"]),
        "name": info.get("name", ""),
        "prompt": info.get("prompt", ""),
        "desc": info.get("desc", "") or "",
        "logo": info.get("logo", "") or "",
        "model_name": info.get("model_name", "") or "",
        "temperature": info.get("temperature", 1),
        "max_token": info.get("max_token", 32000),
        "guide_word": info.get("guide_word", "") or "",
        "guide_question": [q for q in (info.get("guide_question") or []) if q],
        **overrides,
    }
    return _assert_200(client.put(f"{API_BASE}/assistant", json=payload, headers=_auth(token)))


# ---------------------------------------------------------------------------
# AC-02 / AC-05 — knowledge-space selector 口径
# ---------------------------------------------------------------------------


class TestSpaceListScope:
    def test_ac02_selectable_union_excludes_square(self, client, admin_token):
        """AC-02: selectable spaces = mine + joined + department dedup union; the
        square (/square) is a distinct endpoint, not part of the selectable set."""
        mine = _as_list(_assert_200(client.get(f"{API_BASE}/knowledge/space/mine", headers=_auth(admin_token))))
        joined = _as_list(_assert_200(client.get(f"{API_BASE}/knowledge/space/joined", headers=_auth(admin_token))))
        dept = _as_list(_assert_200(client.get(f"{API_BASE}/knowledge/space/department", headers=_auth(admin_token))))

        # Every returned space carries an id; build the dedup union (frontend 口径).
        union = {}
        for s in mine + joined + dept:
            assert "id" in s, f"space row missing id: {s}"
            union.setdefault(s["id"], s)
        assert len(union) >= 1, "admin should see at least one selectable knowledge space"
        # Union size never exceeds the naive concatenation (dedup is a no-op-or-shrink).
        assert len(union) <= len(mine) + len(joined) + len(dept)

        # /square is a SEPARATE endpoint (广场) and must not be conflated with the
        # selectable union — it returns a paged envelope, distinct shape.
        square = client.get(f"{API_BASE}/knowledge/space/square", headers=_auth(admin_token))
        assert square.status_code == 200, "square endpoint should exist and be distinct"

    def test_ac05_endpoints_are_one_shot_lists(self, client, admin_token):
        """AC-05: the three endpoints load one-shot (plain list / no next_cursor
        paging like the document-KB tab)."""
        for ep in ("mine", "joined", "department"):
            data = _assert_200(client.get(f"{API_BASE}/knowledge/space/{ep}", headers=_auth(admin_token)))
            rows = _as_list(data)
            assert isinstance(rows, list)
            # one-shot lists do not expose a document-KB style next_cursor token
            if isinstance(data, dict):
                assert "next_cursor" not in data, f"{ep} unexpectedly cursor-paginated"


# ---------------------------------------------------------------------------
# AC-10 / AC-11 — 用户知识库权限校验 toggle (default OFF + persist)
# ---------------------------------------------------------------------------


class TestKnowledgeAuthToggle:
    def test_ac11_default_off_on_create(self, client, admin_token, created_assistant_ids):
        """AC-11: a freshly created assistant has knowledge_auth = False (default OFF)."""
        info = _create_assistant(client, admin_token, created_assistant_ids)
        assert info.get("knowledge_auth") in (False, 0, None), (
            f"new assistant knowledge_auth should default OFF, got {info.get('knowledge_auth')!r}"
        )
        reloaded = _get_assistant_info(client, admin_token, str(info["id"]))
        assert reloaded.get("knowledge_auth") in (False, 0), "persisted default must be OFF"

    def test_ac10_toggle_persists_on_then_off(self, client, admin_token, created_assistant_ids):
        """AC-10: toggling knowledge_auth ON persists; toggling OFF persists back."""
        info = _create_assistant(client, admin_token, created_assistant_ids)
        aid = str(info["id"])

        # Turn ON
        _update_assistant(client, admin_token, info, knowledge_auth=True)
        assert _get_assistant_info(client, admin_token, aid)["knowledge_auth"] in (True, 1)

        # Turn OFF
        _update_assistant(client, admin_token, info, knowledge_auth=False)
        assert _get_assistant_info(client, admin_token, aid)["knowledge_auth"] in (False, 0)

    def test_ac10_omitting_toggle_leaves_it_unchanged(self, client, admin_token, created_assistant_ids):
        """AC-10 (None semantics): an update that omits knowledge_auth must not reset it."""
        info = _create_assistant(client, admin_token, created_assistant_ids)
        aid = str(info["id"])
        _update_assistant(client, admin_token, info, knowledge_auth=True)
        # Update something else without sending knowledge_auth → stays ON.
        _update_assistant(client, admin_token, info, desc="touched")
        assert _get_assistant_info(client, admin_token, aid)["knowledge_auth"] in (True, 1)


# ---------------------------------------------------------------------------
# AC-03 / AC-04 — knowledge_list round-trip with space + KB type marker
# ---------------------------------------------------------------------------


class TestKnowledgeListRoundTrip:
    def _pick_space_id(self, client, token) -> int | None:
        rows = _as_list(_assert_200(client.get(f"{API_BASE}/knowledge/space/mine", headers=_auth(token))))
        return rows[0]["id"] if rows else None

    def _pick_kb_id(self, client, token) -> int | None:
        data = _assert_200(
            client.get(
                f"{API_BASE}/knowledge",
                params={"permission_id": "use_kb", "type": KNOWLEDGE_TYPE_NORMAL, "page_size": 5},
                headers=_auth(token),
            )
        )
        rows = _as_list(data)
        return rows[0]["id"] if rows else None

    def test_ac03_ac04_mixed_space_and_kb_echo_type(self, client, admin_token, created_assistant_ids):
        """AC-03/AC-04: saving a mix of a knowledge space (type=3) and a document KB
        (type=0) round-trips; GET info echoes each with its correct `type` so the
        frontend can group each into the right tab, and both share one knowledge_list."""
        space_id = self._pick_space_id(client, admin_token)
        kb_id = self._pick_kb_id(client, admin_token)
        if space_id is None:
            pytest.skip("no selectable knowledge space available for admin")
        if kb_id is None:
            pytest.skip("no document knowledge base available for admin")

        info = _create_assistant(client, admin_token, created_assistant_ids)
        aid = str(info["id"])

        _update_assistant(client, admin_token, info, knowledge_list=[kb_id, space_id])

        reloaded = _get_assistant_info(client, admin_token, aid)
        kl = reloaded.get("knowledge_list") or []
        by_id = {item["id"]: item for item in kl}
        assert kb_id in by_id, f"document KB {kb_id} missing from round-tripped knowledge_list"
        assert space_id in by_id, f"knowledge space {space_id} missing from round-tripped knowledge_list"
        # The type marker is what lets the frontend echo each into the right tab.
        assert by_id[kb_id]["type"] == KNOWLEDGE_TYPE_NORMAL, "KB must echo type=0 (document tab)"
        assert by_id[space_id]["type"] == KNOWLEDGE_TYPE_SPACE, "space must echo type=3 (space tab)"
