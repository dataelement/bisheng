"""E2E verification for tenant_code auto-generation (covers tasks 4-7).

Validates the new behavior end-to-end against a live backend on 114:

  1. Mount with tenant_code omitted -> response.tenant_code == "t{dept_id}"
  2. Unmount -> tenant_code rewritten to "t{dept_id}#archived#<ts>"
  3. Re-mount same dept -> new tenant_code == "t{dept_id}" (no UNIQUE collision)
  4. Mount with explicit valid tenant_code -> code preserved verbatim
  5. Mount with invalid tenant_code -> 422 (pattern still enforced)

Run on 114:
  cd /opt/bisheng/src/backend
  /root/.local/bin/uv run pytest test/e2e/test_e2e_tenant_code_autogen.py -v -s
"""

import base64
import os
import time

import httpx
import pytest


API_BASE = os.environ.get('E2E_API_BASE', 'http://localhost:7860/api/v1')


def _login(client: httpx.Client) -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    pubkey_resp = client.get(f'{API_BASE}/user/public_key')
    assert pubkey_resp.status_code == 200
    public_key_pem = pubkey_resp.json()['data']['public_key']

    admin_password = os.environ.get('E2E_ADMIN_PASSWORD', 'Bisheng@top1')
    public_key = serialization.load_pem_public_key(public_key_pem.encode())
    encrypted = public_key.encrypt(admin_password.encode(), padding.PKCS1v15())
    encrypted_password = base64.b64encode(encrypted).decode()

    login_resp = client.post(
        f'{API_BASE}/user/login',
        json={'user_name': 'admin', 'password': encrypted_password},
    )
    assert login_resp.status_code == 200, login_resp.text
    body = login_resp.json()
    assert body['status_code'] == 200, body.get('status_message')
    return body['data']['access_token']


def _auth(token: str) -> dict:
    return {'Authorization': f'Bearer {token}'}


def _create_test_dept(client: httpx.Client, token: str, name: str) -> dict:
    """Create a fresh leaf dept under root for testing. Returns the dept dict
    (must include the integer ``id`` PK, not the BS@ business id)."""
    # Tree root: list current tree, find root, create child under it
    tree = client.get(f'{API_BASE}/departments/tree', headers=_auth(token))
    assert tree.status_code == 200, tree.text
    nodes = tree.json().get('data') or tree.json()
    # tree may be wrapped or raw; normalize
    if isinstance(nodes, dict) and 'data' in nodes:
        nodes = nodes['data']
    assert nodes and isinstance(nodes, list), f'tree shape unexpected: {nodes!r}'

    root = nodes[0]
    root_id_str = root.get('dept_id') or root.get('id')

    create = client.post(
        f'{API_BASE}/departments/',
        headers=_auth(token),
        json={'name': name, 'parent_id': root_id_str},
    )
    assert create.status_code == 200, f'create dept failed: {create.text}'
    body = create.json()
    data = body.get('data', body)
    # Need the integer PK ``id`` for /mount-tenant. Some endpoints return only
    # ``dept_id`` (BS@...); look it up via tree if missing.
    if 'id' in data and isinstance(data['id'], int):
        return data

    # Refresh tree, locate by name
    tree2 = client.get(f'{API_BASE}/departments/tree', headers=_auth(token))
    def _walk(nodes_):
        for n in nodes_:
            if n.get('name') == name:
                return n
            r = _walk(n.get('children') or [])
            if r:
                return r
        return None
    nodes2 = tree2.json()
    if isinstance(nodes2, dict):
        nodes2 = nodes2.get('data') or []
    found = _walk(nodes2)
    assert found, f'created dept not found by name {name!r}'
    return found


def _delete_dept(client: httpx.Client, token: str, dept_id_str: str) -> None:
    """Best-effort cleanup; ignore failures (the test row may already be in
    use by an active mount and need archived first)."""
    try:
        client.delete(
            f'{API_BASE}/departments/{dept_id_str}',
            headers=_auth(token),
        )
    except Exception:
        pass


@pytest.mark.skipif(
    os.environ.get('E2E_SKIP', '0') == '1',
    reason='E2E tests skipped (E2E_SKIP=1)',
)
class TestTenantCodeAutogen:

    @pytest.fixture(scope='class')
    def client(self):
        with httpx.Client(timeout=30.0) as c:
            yield c

    @pytest.fixture(scope='class')
    def token(self, client):
        return _login(client)

    @pytest.fixture(scope='class')
    def test_dept(self, client, token):
        """Create one fresh dept used across all cases. Class-scoped so we can
        chain mount → unmount → re-mount on the same dept_id."""
        name = f'e2e-autogen-{int(time.time())}'
        dept = _create_test_dept(client, token, name)
        # Capture both ids: integer PK for mount, BS@ string id for cleanup
        int_id = dept['id'] if isinstance(dept.get('id'), int) else None
        str_id = dept.get('dept_id') or str(dept.get('id'))
        if int_id is None:
            # Tree node uses ``id`` as the BS@ string. The integer PK lives
            # elsewhere; pull from /departments/{dept_id} detail.
            detail = client.get(
                f'{API_BASE}/departments/{str_id}', headers=_auth(token),
            )
            assert detail.status_code == 200, detail.text
            d = detail.json()
            d = d.get('data', d)
            int_id = d['id'] if isinstance(d.get('id'), int) else d.get('pk')
            assert isinstance(int_id, int), f'no int id in {d!r}'
        info = {'int_id': int_id, 'str_id': str_id, 'name': name}
        print(f'\n>>> test dept: {info}')
        yield info
        # Cleanup at class teardown — try unmount then delete
        try:
            client.delete(
                f'{API_BASE}/departments/{int_id}/mount-tenant',
                headers=_auth(token),
            )
        except Exception:
            pass
        _delete_dept(client, token, str_id)

    # ──────── Case 1: auto-generated code ────────
    def test_case1_mount_auto_generates_t_dept_id(self, client, token, test_dept):
        int_id = test_dept['int_id']
        resp = client.post(
            f'{API_BASE}/departments/{int_id}/mount-tenant',
            headers=_auth(token),
            json={'tenant_name': test_dept['name']},  # NO tenant_code
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        data = body.get('data', body)
        expected = f't{int_id}'
        assert data['tenant_code'] == expected, (
            f'expected tenant_code={expected!r}, got {data!r}'
        )
        print(f'  ✓ case1: dept_id={int_id} → tenant_code={data["tenant_code"]!r}')

    # ──────── Case 2: unmount + re-mount → no collision ────────
    def test_case2_unmount_then_remount_no_collision(self, client, token, test_dept):
        int_id = test_dept['int_id']
        # Unmount the tenant created in case1
        unmount = client.delete(
            f'{API_BASE}/departments/{int_id}/mount-tenant',
            headers=_auth(token),
        )
        assert unmount.status_code == 200, unmount.text
        print(f'  ✓ unmount ok: {unmount.json()}')

        # Re-mount same dept_id without tenant_code; must not 1062-collide
        remount = client.post(
            f'{API_BASE}/departments/{int_id}/mount-tenant',
            headers=_auth(token),
            json={'tenant_name': test_dept['name'] + '-v2'},
        )
        assert remount.status_code == 200, remount.text
        data = remount.json().get('data', remount.json())
        expected = f't{int_id}'
        assert data['tenant_code'] == expected, (
            f'remount expected tenant_code={expected!r}, got {data!r}'
        )
        print(f'  ✓ case2: re-mount → tenant_code={data["tenant_code"]!r} (collision-free)')

    # ──────── Case 3: explicit valid code preserved ────────
    def test_case3_explicit_valid_code_preserved(self, client, token):
        # Need a fresh dept since test_dept is occupied by case2's remount
        name = f'e2e-explicit-{int(time.time())}'
        dept = _create_test_dept(client, token, name)
        int_id = dept['id'] if isinstance(dept.get('id'), int) else None
        if int_id is None:
            detail = client.get(
                f'{API_BASE}/departments/{dept.get("dept_id") or dept.get("id")}',
                headers=_auth(token),
            )
            d = detail.json().get('data', detail.json())
            int_id = d['id']
        explicit_code = f'e2e_explicit_{int(time.time())}'
        try:
            resp = client.post(
                f'{API_BASE}/departments/{int_id}/mount-tenant',
                headers=_auth(token),
                json={'tenant_code': explicit_code, 'tenant_name': name},
            )
            assert resp.status_code == 200, resp.text
            data = resp.json().get('data', resp.json())
            assert data['tenant_code'] == explicit_code, (
                f'expected explicit {explicit_code!r}, got {data!r}'
            )
            print(f'  ✓ case3: explicit code preserved: {data["tenant_code"]!r}')
        finally:
            try:
                client.delete(
                    f'{API_BASE}/departments/{int_id}/mount-tenant',
                    headers=_auth(token),
                )
            except Exception:
                pass

    # ──────── Case 4: invalid code rejected ────────
    def test_case4_invalid_code_rejected_422(self, client, token):
        # Need a fresh dept (won't actually mount — should 422 on schema)
        name = f'e2e-invalid-{int(time.time())}'
        dept = _create_test_dept(client, token, name)
        int_id = dept['id'] if isinstance(dept.get('id'), int) else None
        if int_id is None:
            detail = client.get(
                f'{API_BASE}/departments/{dept.get("dept_id") or dept.get("id")}',
                headers=_auth(token),
            )
            d = detail.json().get('data', detail.json())
            int_id = d['id']
        try:
            resp = client.post(
                f'{API_BASE}/departments/{int_id}/mount-tenant',
                headers=_auth(token),
                json={'tenant_code': '1bad_starts_with_digit', 'tenant_name': name},
            )
            assert resp.status_code == 422, (
                f'expected 422 for invalid code, got {resp.status_code}: {resp.text}'
            )
            print(f'  ✓ case4: invalid code rejected 422: {resp.json()}')
        finally:
            _delete_dept(
                client, token, dept.get('dept_id') or str(dept.get('id')),
            )
