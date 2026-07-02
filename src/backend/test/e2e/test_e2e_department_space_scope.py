"""E2E tests for F033: Department knowledge space member authorization scope.

Verifies that a *department* knowledge space restricts member authorization to
the bound department subtree (departments + their members) and forbids the
user-group dimension, while *normal* knowledge spaces keep the unchanged,
tenant-wide three-dimension behavior.

Prerequisites:
- Backend running on localhost:7860 (or E2E_API_BASE), real middleware.
- Default admin account admin/Bisheng@top1 (super_admin) — used to prove the
  scope restriction is NOT bypassed by super_admin (design B6 / AC-04).

Covers (API-automatable ACs):
- AC-02: department dimension only returns bound department + subtree
- AC-03: user dimension only returns bound-subtree members
- AC-04: authorize rejects user_group / out-of-subtree subjects (incl. super_admin)
- AC-05: normal space keeps three dimensions + tenant-wide range (regression)

UI-only ACs (AC-01) and the cleanup script (AC-06) are out of scope here; see
the manual checklist.

Data isolation: all test resources use the 'e2e-f033-' prefix + a per-run id.
"""

import base64
import os

import httpx
import pytest

API_BASE = os.environ.get("E2E_API_BASE", "http://localhost:7860/api/v1")
HEALTH_URL = API_BASE.replace("/api/v1", "") + "/health"
PREFIX = "e2e-f033-"
ROOT_DEPT_NUMERIC_DEFAULT = None  # discovered from the tree at runtime
PERMISSION_DENIED = 19000


# ---------------------------------------------------------------------------
# Auth + API helpers (sync, mirroring test_e2e_department_tree.py)
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


class _FakeResp:
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


def _get_department_tree(client: httpx.Client, token: str):
    """F038/T012: the eager ``GET /departments/tree`` was removed — rebuild the
    same nested, scope-filtered tree from the lazy ``GET /departments/children``."""
    headers = _auth(token)

    def _layer(parent_id):
        params = {} if parent_id is None else {"parent_id": parent_id}
        return client.get(f"{API_BASE}/departments/children", headers=headers, params=params)

    root = _layer(None)
    if root.status_code != 200:
        return root
    body = root.json()
    if body.get("status_code") != 200:
        return _FakeResp(200, body)

    def _build(nodes):
        out = []
        for n in nodes:
            node = dict(n)
            node["children"] = _build(_layer(node["id"]).json().get("data") or []) if node.get("has_children") else []
            out.append(node)
        return out

    return _FakeResp(200, {"status_code": 200, "status_message": "SUCCESS", "data": _build(body.get("data") or [])})


def _assert_denied(resp: httpx.Response):
    assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:300]}"
    body = resp.json()
    assert body["status_code"] == PERMISSION_DENIED, (
        f"Expected denial {PERMISSION_DENIED}, got {body['status_code']}: {body.get('status_message')}"
    )


def _create_user(client: httpx.Client, token: str, name: str) -> int:
    resp = client.post(
        f"{API_BASE}/user/create",
        json={
            "user_name": name,
            "password": _encrypt_password(client, "Test_pass_123"),
            "group_roles": [{"group_id": 1, "role_ids": [2]}],
        },
        headers=_auth(token),
    )
    data = _assert_200(resp)
    return int(data["user_id"])


def _create_dept(client: httpx.Client, token: str, name: str, parent_id: int) -> dict:
    resp = client.post(
        f"{API_BASE}/departments/",
        json={"name": name, "parent_id": parent_id},
        headers=_auth(token),
    )
    return _assert_200(resp)


def _add_member(client: httpx.Client, token: str, dept_id: str, user_id: int) -> None:
    resp = client.post(
        f"{API_BASE}/departments/{dept_id}/members",
        json={"user_ids": [user_id], "is_primary": 0},
        headers=_auth(token),
    )
    _assert_200(resp)


def _grant_url(space_id: str, kind: str) -> str:
    return f"{API_BASE}/permissions/resources/knowledge_space/{space_id}/grant-subjects/{kind}"


def _authorize_url(space_id: str) -> str:
    return f"{API_BASE}/permissions/resources/knowledge_space/{space_id}/authorize"


def _flatten_dept_ids(tree) -> set[int]:
    ids: set[int] = set()

    def _walk(nodes):
        for node in nodes or []:
            if node.get("id") is not None:
                ids.add(int(node["id"]))
            _walk(node.get("children"))

    _walk(tree)
    return ids


# Substrings that mark a space we must never mutate, even for grant+revoke.
_SENSITIVE_SPACE_MARKERS = ("勿动", "生产", "压测", "首钢")


def _mine_space_items(client: httpx.Client, token: str) -> list[dict]:
    data = _assert_200(client.get(f"{API_BASE}/knowledge/space/mine", headers=_auth(token)))
    if isinstance(data, dict):
        items = data.get("data", [])
        return items if isinstance(items, list) else []
    return data if isinstance(data, list) else []


def _pick_reusable_normal_space(client: httpx.Client, token: str) -> str:
    """Pick an admin-owned, non-department, non-sensitive normal space to reuse.

    The admin's space-creation quota (30) is full of real spaces, so the normal
    control space is reused (read-only checks + a grant-then-revoke) rather than
    created. Admin ownership guarantees permission-management access.
    """
    dept_all = _assert_200(client.get(f"{API_BASE}/knowledge/space/department/all", headers=_auth(token)))
    dept_ids = {int(s["id"]) for s in (dept_all or []) if s.get("id") is not None}
    candidates = [
        s
        for s in _mine_space_items(client, token)
        if s.get("id") is not None
        and int(s["id"]) not in dept_ids
        and (s.get("space_kind") or "normal") == "normal"
        and not any(m in (s.get("name") or "") for m in _SENSITIVE_SPACE_MARKERS)
    ]
    # Prefer an obvious test space if present.
    candidates.sort(key=lambda s: (not (s.get("name") or "").startswith("e2e-"), int(s["id"])))
    assert candidates, "no reusable normal space found for the regression control"
    return str(candidates[0]["id"])


def _preclean_prefixed(client: httpx.Client, token: str) -> None:
    """Remove leftover e2e-f033 department spaces + departments from prior runs."""
    dept_all = _assert_200(client.get(f"{API_BASE}/knowledge/space/department/all", headers=_auth(token)))
    for sp in dept_all or []:
        if (sp.get("name") or "").startswith(PREFIX) and sp.get("id") is not None:
            client.delete(f"{API_BASE}/knowledge/space/{sp['id']}", headers=_auth(token))

    tree = _assert_200(_get_department_tree(client, token))
    stale: list[dict] = []

    def _collect(nodes):
        for n in nodes or []:
            if (n.get("name") or "").startswith(PREFIX):
                stale.append(n)
            _collect(n.get("children"))

    _collect(tree)
    stale.sort(key=lambda d: len(d.get("path", "")), reverse=True)  # leaf-first
    for d in stale:
        members = _assert_200(client.get(f"{API_BASE}/departments/{d['dept_id']}/members", headers=_auth(token)))
        for m in members.get("data", []) if isinstance(members, dict) else []:
            client.delete(f"{API_BASE}/departments/{d['dept_id']}/members/{m['user_id']}", headers=_auth(token))
        client.delete(f"{API_BASE}/departments/{d['dept_id']}", headers=_auth(token))


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
def env(client, admin_token):
    """Build a department subtree + members + a department space and a normal space.

    root
     ├── parent (P)  ──► bound to department knowledge space
     │     └── child (C)        [in-subtree]  ← user_in
     └── sibling (S)            [out-subtree] ← user_out
    """
    import uuid

    run = uuid.uuid4().hex[:6]
    _preclean_prefixed(client, admin_token)
    tree = _assert_200(_get_department_tree(client, admin_token))
    root_id = int(tree[0]["id"])

    parent = _create_dept(client, admin_token, f"{PREFIX}{run}-parent", root_id)
    child = _create_dept(client, admin_token, f"{PREFIX}{run}-child", int(parent["id"]))
    sibling = _create_dept(client, admin_token, f"{PREFIX}{run}-sibling", root_id)

    user_in = _create_user(client, admin_token, f"{PREFIX}{run}-uin")
    user_out = _create_user(client, admin_token, f"{PREFIX}{run}-uout")
    _add_member(client, admin_token, child["dept_id"], user_in)
    _add_member(client, admin_token, sibling["dept_id"], user_out)
    # admin (user 1) is a guaranteed active tenant member; add to the in-subtree
    # child so the user-listing assertion has a tenant-visible subtree member.
    _add_member(client, admin_token, child["dept_id"], 1)

    # Department knowledge space bound to the parent department.
    dept_space = _assert_200(
        client.post(
            f"{API_BASE}/knowledge/space/department/batch-create",
            json={"items": [{"department_id": int(parent["id"])}]},
            headers=_auth(admin_token),
        )
    )
    dept_space_id = str(dept_space[0]["id"])

    # Normal knowledge space (control / regression) — reuse an existing
    # admin-owned space; the create quota is full of real spaces.
    normal_space_id = _pick_reusable_normal_space(client, admin_token)

    data = {
        "root_id": root_id,
        "parent_id": int(parent["id"]),
        "child_id": int(child["id"]),
        "sibling_id": int(sibling["id"]),
        "user_in": user_in,
        "user_out": user_out,
        "dept_space_id": dept_space_id,
        "normal_space_id": normal_space_id,
        "parent_dept_str": parent["dept_id"],
        "child_dept_str": child["dept_id"],
        "sibling_dept_str": sibling["dept_id"],
    }

    yield data

    # Best-effort teardown (prefix-scoped). Only the owned department space is
    # deleted; the reused normal space is left untouched.
    client.delete(f"{API_BASE}/knowledge/space/{dept_space_id}", headers=_auth(admin_token))
    for dept_str, uid in (
        (data["child_dept_str"], user_in),
        (data["child_dept_str"], 1),
        (data["sibling_dept_str"], user_out),
    ):
        client.delete(f"{API_BASE}/departments/{dept_str}/members/{uid}", headers=_auth(admin_token))
    for dept_str in (data["child_dept_str"], data["sibling_dept_str"], data["parent_dept_str"]):
        client.delete(f"{API_BASE}/departments/{dept_str}", headers=_auth(admin_token))


# ---------------------------------------------------------------------------
# Tests (definition order = execution order)
# ---------------------------------------------------------------------------


class TestDepartmentSpaceScope:
    def test_ac02_departments_scoped_to_subtree(self, client, admin_token, env):
        """AC-02: department dimension returns only the bound department + subtree."""
        tree = _assert_200(client.get(_grant_url(env["dept_space_id"], "departments"), headers=_auth(admin_token)))
        ids = _flatten_dept_ids(tree)
        assert env["parent_id"] in ids, "bound department must be listed"
        assert env["child_id"] in ids, "sub-department must be listed"
        assert env["sibling_id"] not in ids, "out-of-subtree department must be excluded"
        assert env["root_id"] not in ids, "ancestor (root) must be excluded"

    def test_ac03_users_scoped_to_subtree(self, client, admin_token, env):
        """AC-03: user dimension returns only bound-subtree members.

        Uses admin (user 1, a guaranteed active tenant member added to the
        in-subtree child) for the inclusion check, and proves scoping by showing
        the department-space list is a strict subset of the tenant-wide list.
        """
        dept_users = {
            int(u["user_id"])
            for u in _assert_200(
                client.get(
                    _grant_url(env["dept_space_id"], "users"),
                    params={"page": 1, "page_size": 2000},
                    headers=_auth(admin_token),
                )
            )
        }
        normal_users = {
            int(u["user_id"])
            for u in _assert_200(
                client.get(
                    _grant_url(env["normal_space_id"], "users"),
                    params={"page": 1, "page_size": 2000},
                    headers=_auth(admin_token),
                )
            )
        }
        assert 1 in dept_users, "in-subtree tenant member (admin) must be listed"
        assert dept_users < normal_users, "department space must list a strict subset of tenant users"
        outsider = next(uid for uid in normal_users if uid not in dept_users)
        assert outsider not in dept_users, "a tenant user outside the subtree must be excluded"

    def test_ac04_user_groups_disabled_on_department_space(self, client, admin_token, env):
        """AC-04: department space exposes no user-group candidates."""
        groups = _assert_200(client.get(_grant_url(env["dept_space_id"], "user-groups"), headers=_auth(admin_token)))
        assert groups == [], "department space must not list any user groups"

    def test_ac04_authorize_rejects_user_group(self, client, admin_token, env):
        """AC-04: granting a user_group on a department space is denied (super_admin too)."""
        resp = client.post(
            _authorize_url(env["dept_space_id"]),
            json={
                "grants": [{"subject_type": "user_group", "subject_id": 1, "relation": "viewer"}],
                "revokes": [],
            },
            headers=_auth(admin_token),
        )
        _assert_denied(resp)

    def test_ac04_authorize_rejects_out_of_subtree_department(self, client, admin_token, env):
        """AC-04: granting an out-of-subtree department is denied."""
        resp = client.post(
            _authorize_url(env["dept_space_id"]),
            json={
                "grants": [{"subject_type": "department", "subject_id": env["sibling_id"], "relation": "viewer"}],
                "revokes": [],
            },
            headers=_auth(admin_token),
        )
        _assert_denied(resp)

    def test_ac04_authorize_rejects_out_of_subtree_user(self, client, admin_token, env):
        """AC-04: granting an out-of-subtree user is denied."""
        resp = client.post(
            _authorize_url(env["dept_space_id"]),
            json={
                "grants": [{"subject_type": "user", "subject_id": env["user_out"], "relation": "viewer"}],
                "revokes": [],
            },
            headers=_auth(admin_token),
        )
        _assert_denied(resp)

    def test_ac04_authorize_allows_in_subtree_user(self, client, admin_token, env):
        """AC-04: granting an in-subtree user succeeds."""
        resp = client.post(
            _authorize_url(env["dept_space_id"]),
            json={
                "grants": [{"subject_type": "user", "subject_id": env["user_in"], "relation": "viewer"}],
                "revokes": [],
            },
            headers=_auth(admin_token),
        )
        _assert_200(resp)

    def test_ac05_normal_space_lists_user_groups(self, client, admin_token, env):
        """AC-05 regression: normal space keeps the user-group dimension."""
        groups = _assert_200(client.get(_grant_url(env["normal_space_id"], "user-groups"), headers=_auth(admin_token)))
        assert isinstance(groups, list) and len(groups) >= 1, "normal space must still list user groups"

    def test_ac05_normal_space_departments_tenant_wide(self, client, admin_token, env):
        """AC-05 regression: normal space department dimension is tenant-wide (not scoped)."""
        tree = _assert_200(client.get(_grant_url(env["normal_space_id"], "departments"), headers=_auth(admin_token)))
        ids = _flatten_dept_ids(tree)
        assert env["root_id"] in ids, "normal space must list the whole tenant tree (root present)"
        assert env["sibling_id"] in ids, "normal space must include departments outside any subtree"

    def test_ac05_normal_space_authorize_user_group_ok(self, client, admin_token, env):
        """AC-05 regression: granting a user_group on a normal space still succeeds.

        The normal space is reused, so the grant is immediately revoked to leave
        no net change.
        """
        grant = {"subject_type": "user_group", "subject_id": 1, "relation": "editor"}
        resp = client.post(
            _authorize_url(env["normal_space_id"]),
            json={"grants": [grant], "revokes": []},
            headers=_auth(admin_token),
        )
        _assert_200(resp)
        # Revert: leave the reused space as we found it.
        client.post(
            _authorize_url(env["normal_space_id"]),
            json={"grants": [], "revokes": [grant]},
            headers=_auth(admin_token),
        )
