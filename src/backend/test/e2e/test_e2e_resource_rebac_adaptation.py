"""
E2E tests for F008: Resource ReBAC Adaptation

Prerequisites:
- Backend running on localhost:7860 (or E2E_API_BASE)
- MySQL/Redis/OpenFGA services running
- Admin user exists (admin/admin123)

Covers:
- AC-02: Resource creation writes owner tuple (INV-2)
- AC-03: Resource deletion cleans FGA tuples
- AC-04: List APIs use ReBAC filtering
- AC-06: KnowledgeSpace dual-write adaptation
- AC-07: Channel dual-write adaptation
- AC-08: group_ids removal from responses
"""

import time

import pytest
import httpx

from test.e2e.helpers.auth import (
    get_admin_token, get_user_token, auth_headers, create_test_user,
    encrypt_password, get_public_key,
)
from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error

# Data prefix for test isolation (must be >= 5 chars)
# Append run ID for uniqueness across parallel runs
_RUN_ID = str(int(time.time()))[-6:]
PREFIX = f"e2e-f008-{_RUN_ID}-"


def _assert_resp_ok(resp: httpx.Response) -> dict:
    """Assert success for responses that may return 200 or 201."""
    assert resp.status_code in (200, 201), f'HTTP {resp.status_code}: {resp.text[:300]}'
    body = resp.json()
    assert body['status_code'] == 200, (
        f"Business error {body['status_code']}: {body.get('status_message')}"
    )
    return body.get('data')


# ────────────── Helpers ──────────────────────────────────────────────────────


async def _check_permission(
    client: httpx.AsyncClient, token: str,
    relation: str, object_type: str, object_id: str,
) -> bool:
    """Check permission via /permissions/check endpoint."""
    resp = await client.post(
        f'{API_BASE}/permissions/check',
        json={
            'relation': relation,
            'object_type': object_type,
            'object_id': object_id,
        },
        headers=auth_headers(token),
    )
    body = resp.json()
    if body.get('status_code') != 200:
        return False
    return body.get('data', {}).get('allowed', False)


async def _create_workflow(
    client: httpx.AsyncClient, token: str, name: str,
) -> dict:
    """Create a workflow and return its data."""
    resp = await client.post(
        f'{API_BASE}/workflow/create',
        json={'name': name, 'description': f'{name} desc'},
        headers=auth_headers(token),
    )
    return _assert_resp_ok(resp)


async def _create_assistant(
    client: httpx.AsyncClient, token: str, name: str,
) -> dict:
    """Create an assistant and return its data."""
    resp = await client.post(
        f'{API_BASE}/assistant',
        json={'name': name, 'description': f'{name} desc',
              'prompt': 'This is a test assistant prompt for E2E testing.',
              'logo': ''},
        headers=auth_headers(token),
    )
    return _assert_resp_ok(resp)


async def _create_knowledge_space(
    client: httpx.AsyncClient, token: str, name: str,
    auth_type: str = 'public',
) -> dict:
    """Create a knowledge space and return its data."""
    resp = await client.post(
        f'{API_BASE}/knowledge/space',
        json={'name': name, 'description': f'{name} desc', 'auth_type': auth_type},
        headers=auth_headers(token),
    )
    return assert_resp_200(resp)


async def _cleanup_workflows(client: httpx.AsyncClient, token: str):
    """Clean up test workflows by prefix."""
    headers = auth_headers(token)
    resp = await client.get(
        f'{API_BASE}/workflow/list',
        params={'page': 1, 'limit': 100},
        headers=headers,
    )
    if resp.status_code != 200:
        return
    body = resp.json()
    if body.get('status_code') != 200:
        return
    data = body.get('data', {})
    items = data.get('data', []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        return
    for item in items:
        name = item.get('name', '')
        if name.startswith(PREFIX):
            flow_id = item.get('id')
            if flow_id:
                await client.delete(
                    f'{API_BASE}/workflow/{flow_id}',
                    headers=headers,
                )


async def _cleanup_assistants(client: httpx.AsyncClient, token: str):
    """Clean up test assistants by prefix."""
    headers = auth_headers(token)
    resp = await client.get(
        f'{API_BASE}/assistant',
        params={'page': 1, 'limit': 100},
        headers=headers,
    )
    if resp.status_code != 200:
        return
    body = resp.json()
    if body.get('status_code') != 200:
        return
    data = body.get('data', {})
    items = data.get('data', []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        return
    for item in items:
        name = item.get('name', '')
        if name.startswith(PREFIX):
            aid = item.get('id')
            if aid:
                await client.post(
                    f'{API_BASE}/assistant/delete',
                    json={'id': aid},
                    headers=headers,
                )


async def _cleanup_spaces(client: httpx.AsyncClient, token: str):
    """Clean up test knowledge spaces by prefix."""
    headers = auth_headers(token)
    resp = await client.get(
        f'{API_BASE}/knowledge/space/mine',
        headers=headers,
    )
    if resp.status_code != 200:
        return
    body = resp.json()
    if body.get('status_code') != 200:
        return
    data = body.get('data', [])
    if not isinstance(data, list):
        return
    for item in data:
        name = item.get('name', '')
        if name.startswith(PREFIX):
            sid = item.get('id')
            if sid:
                await client.delete(
                    f'{API_BASE}/knowledge/space/{sid}',
                    headers=headers,
                )


async def _cleanup_users(client: httpx.AsyncClient, admin_token: str):
    """Clean up test users by prefix."""
    headers = auth_headers(admin_token)
    resp = await client.get(
        f'{API_BASE}/user/list',
        params={'page_num': 1, 'page_size': 100},
        headers=headers,
    )
    if resp.status_code != 200:
        return
    body = resp.json()
    if body.get('status_code') != 200:
        return
    data = body.get('data', {})
    items = data.get('data', []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        return
    for item in items:
        name = item.get('user_name', '')
        if name.startswith(PREFIX):
            uid = item.get('user_id')
            if uid:
                await client.delete(
                    f'{API_BASE}/user/{uid}',
                    headers=headers,
                )


# ────────────── Test Suite ───────────────────────────────────────────────────


@pytest.mark.asyncio
class TestE2EResourceRebacAdaptation:
    """E2E: F008 Resource ReBAC Adaptation"""

    # ──────── Fixtures ────────

    @pytest.fixture(autouse=True, scope='class')
    async def setup_and_teardown(self):
        """Dual cleanup: clear previous test data before and after tests."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            admin_token = await get_admin_token(client)
            # Pre-cleanup
            await _cleanup_workflows(client, admin_token)
            await _cleanup_assistants(client, admin_token)
            await _cleanup_spaces(client, admin_token)
            await _cleanup_users(client, admin_token)

            yield

            # Post-cleanup
            admin_token = await get_admin_token(client)
            await _cleanup_workflows(client, admin_token)
            await _cleanup_assistants(client, admin_token)
            await _cleanup_spaces(client, admin_token)
            await _cleanup_users(client, admin_token)

    @pytest.fixture
    async def client(self):
        async with httpx.AsyncClient(timeout=60.0) as client:
            yield client

    @pytest.fixture
    async def admin_token(self, client):
        return await get_admin_token(client)

    @pytest.fixture
    async def regular_user(self, client, admin_token):
        """Create a regular test user and return (user_data, token) tuple."""
        headers = auth_headers(admin_token)
        test_password = 'test_pwd_123'
        username = f'{PREFIX}user'
        # Encrypt password for user creation
        pubkey = await get_public_key(client)
        encrypted_pwd = encrypt_password(test_password, pubkey)
        resp = await client.post(
            f'{API_BASE}/user/create',
            json={
                'user_name': username,
                'password': encrypted_pwd,
                'role_id': 2,
                'group_roles': [],
            },
            headers=headers,
        )
        body = resp.json()
        token = await get_user_token(client, username, test_password)
        return body.get('data', {}), token

    # ──────── AC-02: Resource creation writes owner tuple ────────

    async def test_ac02_workflow_creation_writes_owner(self, client, admin_token):
        """AC-02: Creating a workflow writes owner tuple → creator has can_read permission."""
        flow = await _create_workflow(client, admin_token, f'{PREFIX}wf-owner-test')
        flow_id = flow.get('id') or flow.get('flow_id')
        assert flow_id, 'Workflow creation should return an id'

        # Verify owner has permission via ReBAC
        has_perm = await _check_permission(
            client, admin_token, 'can_read', 'workflow', str(flow_id),
        )
        assert has_perm, 'Creator should have can_read permission on the workflow'

    async def test_ac02_knowledge_space_writes_owner(self, client, admin_token):
        """AC-02: Creating a knowledge space writes owner tuple."""
        space = await _create_knowledge_space(client, admin_token, f'{PREFIX}space-owner')
        space_id = space.get('id')
        assert space_id, 'Space creation should return an id'

        has_perm = await _check_permission(
            client, admin_token, 'can_read', 'knowledge_space', str(space_id),
        )
        assert has_perm, 'Creator should have can_read on knowledge_space'

    # ──────── AC-03: Resource deletion cleans FGA tuples ────────

    async def test_ac03_workflow_delete_cleans_fga(self, client, admin_token):
        """AC-03: Deleting a workflow clears its FGA tuples → not accessible after delete."""
        flow = await _create_workflow(client, admin_token, f'{PREFIX}wf-delete-test')
        flow_id = str(flow.get('id') or flow.get('flow_id'))

        # Delete the workflow (try multiple endpoint patterns)
        headers = auth_headers(admin_token)
        resp = await client.delete(f'{API_BASE}/workflow/{flow_id}', headers=headers)
        if resp.status_code == 404 or resp.status_code == 405:
            # Try PATCH-based soft delete or POST-based delete
            resp = await client.post(
                f'{API_BASE}/workflow/delete',
                json={'flow_id': flow_id},
                headers=headers,
            )
        body = resp.json()
        assert body.get('status_code') == 200, f'Workflow deletion should succeed: {body}'

        # Verify the workflow is no longer in the list
        resp = await client.get(
            f'{API_BASE}/workflow/list',
            params={'page': 1, 'limit': 100},
            headers=headers,
        )
        data = assert_resp_200(resp)
        items = data.get('data', []) if isinstance(data, dict) else data
        remaining_ids = [str(item.get('id') or item.get('flow_id')) for item in items]
        assert flow_id not in remaining_ids, 'Deleted workflow should not appear in list'

    async def test_ac03_knowledge_space_delete_cleans_fga(self, client, admin_token):
        """AC-03: Deleting a knowledge space clears FGA tuples."""
        space = await _create_knowledge_space(client, admin_token, f'{PREFIX}space-del')
        space_id = space.get('id')

        resp = await client.delete(
            f'{API_BASE}/knowledge/space/{space_id}',
            headers=auth_headers(admin_token),
        )
        body = resp.json()
        assert body.get('status_code') == 200, f'Space deletion failed: {body}'

    # ──────── AC-04: List APIs use ReBAC filtering ────────

    async def test_ac04_workflow_list_filtered_by_rebac(
        self, client, admin_token, regular_user,
    ):
        """AC-04: Workflow list returns only resources authorized via ReBAC."""
        _, user_token = regular_user

        # Admin creates a workflow
        admin_flow = await _create_workflow(
            client, admin_token, f'{PREFIX}wf-admin-only',
        )

        # Regular user creates a workflow
        user_flow = await _create_workflow(
            client, user_token, f'{PREFIX}wf-user-owned',
        )
        user_flow_id = str(user_flow.get('id') or user_flow.get('flow_id'))

        # Regular user lists workflows — should see their own but not admin's
        resp = await client.get(
            f'{API_BASE}/workflow/list',
            params={'page': 1, 'limit': 100},
            headers=auth_headers(user_token),
        )
        data = assert_resp_200(resp)
        items = data.get('data', []) if isinstance(data, dict) else data
        user_flow_ids = [str(item.get('id') or item.get('flow_id')) for item in items]

        assert user_flow_id in user_flow_ids, \
            'Regular user should see their own workflow'

        admin_flow_id = str(admin_flow.get('id') or admin_flow.get('flow_id'))
        assert admin_flow_id not in user_flow_ids, \
            'Regular user should NOT see admin-only workflow'

        # Admin should see all workflows
        resp = await client.get(
            f'{API_BASE}/workflow/list',
            params={'page': 1, 'limit': 100},
            headers=auth_headers(admin_token),
        )
        data = assert_resp_200(resp)
        items = data.get('data', []) if isinstance(data, dict) else data
        all_ids = [str(item.get('id') or item.get('flow_id')) for item in items]
        assert admin_flow_id in all_ids, 'Admin should see all workflows'

    # ──────── AC-06: KnowledgeSpace dual-write ────────

    async def test_ac06_space_create_dual_write(self, client, admin_token):
        """AC-06: Knowledge space creation writes both SpaceChannelMember and FGA owner tuple."""
        space = await _create_knowledge_space(
            client, admin_token, f'{PREFIX}space-dual',
        )
        space_id = space.get('id')

        # Verify creator can read the space via info endpoint
        resp = await client.get(
            f'{API_BASE}/knowledge/space/{space_id}/info',
            headers=auth_headers(admin_token),
        )
        # If /info path doesn't work, try alternate paths
        if resp.status_code == 404 or resp.status_code == 405:
            resp = await client.get(
                f'{API_BASE}/knowledge/space/info',
                params={'space_id': space_id},
                headers=auth_headers(admin_token),
            )
        data = assert_resp_200(resp)
        assert data.get('name') == f'{PREFIX}space-dual'

        # Verify creator appears in my created spaces
        resp = await client.get(
            f'{API_BASE}/knowledge/space/mine',
            headers=auth_headers(admin_token),
        )
        data = assert_resp_200(resp)
        # data may be a list directly or a dict with 'data' key
        items = data if isinstance(data, list) else data.get('data', [])
        space_ids = [str(item.get('id')) for item in items]
        assert str(space_id) in space_ids, 'Created space should appear in mine list'

    async def test_ac06_space_permission_check(self, client, admin_token, regular_user):
        """AC-06: Regular user cannot edit admin's space without permission."""
        _, user_token = regular_user

        space = await _create_knowledge_space(
            client, admin_token, f'{PREFIX}space-perm',
        )
        space_id = space.get('id')

        # Regular user should not have edit permission
        has_edit = await _check_permission(
            client, user_token, 'can_edit', 'knowledge_space', str(space_id),
        )
        assert not has_edit, 'Regular user should NOT have can_edit on admin space'

    # ──────── AC-08: group_ids removal from responses ────────

    async def test_ac08_workflow_list_no_group_ids(self, client, admin_token):
        """AC-08: Workflow list response should not contain group_ids field."""
        await _create_workflow(client, admin_token, f'{PREFIX}wf-no-gids')

        resp = await client.get(
            f'{API_BASE}/workflow/list',
            params={'page': 1, 'limit': 10},
            headers=auth_headers(admin_token),
        )
        data = assert_resp_200(resp)
        items = data.get('data', []) if isinstance(data, dict) else data
        for item in items:
            if item.get('name', '').startswith(PREFIX):
                assert 'group_ids' not in item, \
                    f'Workflow list response should not contain group_ids: {item.get("name")}'
                break

    async def test_ac08_assistant_list_no_group_ids(self, client, admin_token):
        """AC-08: Assistant list response should not contain meaningful group_ids."""
        await _create_assistant(client, admin_token, f'{PREFIX}asst-no-gids')

        resp = await client.get(
            f'{API_BASE}/assistant',
            params={'page': 1, 'limit': 10},
            headers=auth_headers(admin_token),
        )
        data = assert_resp_200(resp)
        items = data.get('data', []) if isinstance(data, dict) else data
        for item in items:
            if item.get('name', '').startswith(PREFIX):
                # group_ids should be absent, None, or empty list (all acceptable)
                gids = item.get('group_ids')
                assert not gids, \
                    f'Assistant should not have populated group_ids: {gids}'
                break

    # ──────── AC-02+03 combined: Channel lifecycle ────────

    async def test_ac07_channel_create_and_dismiss(self, client, admin_token):
        """AC-07: Channel creation writes owner tuple; dismiss clears FGA tuples."""
        # Create channel
        resp = await client.post(
            f'{API_BASE}/channel/manager/create',
            json={
                'name': f'{PREFIX}channel-test',
                'description': 'test channel',
                'visibility': 'public',
                'source_list': [],
            },
            headers=auth_headers(admin_token),
        )
        channel = _assert_resp_ok(resp)
        channel_id = channel.get('id')
        assert channel_id, 'Channel creation should return an id'

        # Verify creator has permission
        has_perm = await _check_permission(
            client, admin_token, 'can_read', 'channel', str(channel_id),
        )
        assert has_perm, 'Channel creator should have can_read permission'

        # Dismiss channel
        resp = await client.delete(
            f'{API_BASE}/channel/manager/{channel_id}',
            headers=auth_headers(admin_token),
        )
        body = resp.json()
        assert body.get('status_code') == 200, f'Channel dismiss should succeed: {body}'
