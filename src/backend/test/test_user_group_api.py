"""API integration tests for User Group endpoints (F003).

Tests endpoint routing, request validation, response format, and error codes
by mocking UserGroupService at the service boundary. This avoids deep ORM
import chain issues from the premock system while thoroughly testing the API layer.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from starlette.testclient import TestClient

# Pre-mock
import sys
for mod in ('celery', 'celery.schedules', 'celery.app', 'celery.app.task'):
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()
from test.fixtures.mock_services import premock_import_chain
premock_import_chain()

from bisheng.user_group.api.router import router as user_group_router
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.user_group import (
    UserGroupDefaultProtectedError,
    UserGroupHasMembersError,
    UserGroupMemberExistsError,
    UserGroupMemberNotFoundError,
    UserGroupNameDuplicateError,
    UserGroupNotFoundError,
    UserGroupPermissionDeniedError,
)


class MockAdminUser:
    user_id = 1
    user_name = 'admin'
    user_role = [1]
    tenant_id = 1
    group_cache = {}


class MockNonAdminUser:
    user_id = 99
    user_name = 'viewer'
    user_role = [2]
    tenant_id = 1
    group_cache = {}


SAMPLE_GROUP = {
    'id': 10,
    'group_name': 'Project Alpha',
    'visibility': 'public',
    'remark': None,
    'member_count': 0,
    'create_user': 1,
    'create_time': '2026-04-12T10:00:00',
    'update_time': '2026-04-12T10:00:00',
    'group_admins': [{'user_id': 1, 'user_name': 'admin'}],
}

SERVICE_PATH = 'bisheng.user_group.domain.services.user_group_service.UserGroupService'


def _make_app(user_cls):
    app = FastAPI()
    app.include_router(user_group_router, prefix='/api/v1')

    async def get_user():
        return user_cls()

    app.dependency_overrides[UserPayload.get_login_user] = get_user
    return app


# =========================================================================
# CRUD Tests
# =========================================================================

class TestUserGroupCRUD:

    def test_create_group(self):
        """AC-01: Create succeeds with 200."""
        app = _make_app(MockAdminUser)
        with patch(f'{SERVICE_PATH}.acreate_group', new_callable=AsyncMock,
                   return_value=SAMPLE_GROUP):
            with TestClient(app) as c:
                resp = c.post('/api/v1/user-groups/', json={
                    'group_name': 'Project Alpha', 'visibility': 'public',
                })
                body = resp.json()
                assert body['status_code'] == 200
                assert body['data']['group_name'] == 'Project Alpha'
                assert body['data']['id'] == 10

    def test_create_group_duplicate_name(self):
        """AC-02: Duplicate name returns 23001."""
        app = _make_app(MockAdminUser)
        with patch(f'{SERVICE_PATH}.acreate_group', new_callable=AsyncMock,
                   side_effect=UserGroupNameDuplicateError()):
            with TestClient(app) as c:
                resp = c.post('/api/v1/user-groups/', json={
                    'group_name': 'Dup',
                })
                assert resp.json()['status_code'] == 23001

    def test_list_groups(self):
        """AC-04: List returns paginated data."""
        app = _make_app(MockAdminUser)
        result = {'data': [SAMPLE_GROUP], 'total': 1}
        with patch(f'{SERVICE_PATH}.alist_groups', new_callable=AsyncMock,
                   return_value=result):
            with TestClient(app) as c:
                resp = c.get('/api/v1/user-groups/?page=1&limit=20')
                body = resp.json()
                assert body['status_code'] == 200
                assert body['data']['total'] == 1
                assert len(body['data']['data']) == 1

    def test_get_group(self):
        """AC-05: Get group detail."""
        app = _make_app(MockAdminUser)
        with patch(f'{SERVICE_PATH}.aget_group', new_callable=AsyncMock,
                   return_value=SAMPLE_GROUP):
            with TestClient(app) as c:
                resp = c.get('/api/v1/user-groups/10')
                body = resp.json()
                assert body['status_code'] == 200
                assert body['data']['group_name'] == 'Project Alpha'

    def test_get_group_not_found(self):
        """AC-06: Non-existent group returns 23000."""
        app = _make_app(MockAdminUser)
        with patch(f'{SERVICE_PATH}.aget_group', new_callable=AsyncMock,
                   side_effect=UserGroupNotFoundError()):
            with TestClient(app) as c:
                resp = c.get('/api/v1/user-groups/99999')
                assert resp.json()['status_code'] == 23000

    def test_update_group(self):
        """AC-07: Update succeeds."""
        app = _make_app(MockAdminUser)
        updated = {**SAMPLE_GROUP, 'group_name': 'Updated'}
        with patch(f'{SERVICE_PATH}.aupdate_group', new_callable=AsyncMock,
                   return_value=updated):
            with TestClient(app) as c:
                resp = c.put('/api/v1/user-groups/10', json={
                    'group_name': 'Updated',
                })
                body = resp.json()
                assert body['status_code'] == 200
                assert body['data']['group_name'] == 'Updated'

    def test_update_group_duplicate_name(self):
        """AC-08: Update to existing name returns 23001."""
        app = _make_app(MockAdminUser)
        with patch(f'{SERVICE_PATH}.aupdate_group', new_callable=AsyncMock,
                   side_effect=UserGroupNameDuplicateError()):
            with TestClient(app) as c:
                resp = c.put('/api/v1/user-groups/10', json={
                    'group_name': 'Existing',
                })
                assert resp.json()['status_code'] == 23001

    def test_delete_group(self):
        """AC-09: Delete empty non-default group."""
        app = _make_app(MockAdminUser)
        with patch(f'{SERVICE_PATH}.adelete_group', new_callable=AsyncMock):
            with TestClient(app) as c:
                resp = c.delete('/api/v1/user-groups/10')
                assert resp.json()['status_code'] == 200

    def test_delete_default_group(self):
        """AC-10: Delete default group returns 23002."""
        app = _make_app(MockAdminUser)
        with patch(f'{SERVICE_PATH}.adelete_group', new_callable=AsyncMock,
                   side_effect=UserGroupDefaultProtectedError()):
            with TestClient(app) as c:
                resp = c.delete('/api/v1/user-groups/2')
                assert resp.json()['status_code'] == 23002

    def test_delete_group_has_members(self):
        """AC-11: Delete group with members returns 23003."""
        app = _make_app(MockAdminUser)
        with patch(f'{SERVICE_PATH}.adelete_group', new_callable=AsyncMock,
                   side_effect=UserGroupHasMembersError()):
            with TestClient(app) as c:
                resp = c.delete('/api/v1/user-groups/10')
                assert resp.json()['status_code'] == 23003


# =========================================================================
# Member Tests
# =========================================================================

class TestUserGroupMembers:

    def test_add_members(self):
        """AC-12: Batch add members."""
        app = _make_app(MockAdminUser)
        with patch(f'{SERVICE_PATH}.aadd_members', new_callable=AsyncMock):
            with TestClient(app) as c:
                resp = c.post('/api/v1/user-groups/10/members', json={
                    'user_ids': [3, 5, 7],
                })
                assert resp.json()['status_code'] == 200

    def test_add_members_duplicate(self):
        """AC-13: Duplicate member returns 23004."""
        app = _make_app(MockAdminUser)
        with patch(f'{SERVICE_PATH}.aadd_members', new_callable=AsyncMock,
                   side_effect=UserGroupMemberExistsError()):
            with TestClient(app) as c:
                resp = c.post('/api/v1/user-groups/10/members', json={
                    'user_ids': [3],
                })
                assert resp.json()['status_code'] == 23004

    def test_get_members(self):
        """AC-14: Get paginated members."""
        app = _make_app(MockAdminUser)
        result = {
            'data': [{'user_id': 3, 'user_name': 'alice',
                       'is_group_admin': False, 'create_time': None}],
            'total': 1,
        }
        with patch(f'{SERVICE_PATH}.aget_members', new_callable=AsyncMock,
                   return_value=result):
            with TestClient(app) as c:
                resp = c.get('/api/v1/user-groups/10/members?page=1&limit=20')
                body = resp.json()
                assert body['status_code'] == 200
                assert body['data']['total'] == 1

    def test_remove_member(self):
        """AC-15: Remove a member."""
        app = _make_app(MockAdminUser)
        with patch(f'{SERVICE_PATH}.aremove_member', new_callable=AsyncMock):
            with TestClient(app) as c:
                resp = c.delete('/api/v1/user-groups/10/members/3')
                assert resp.json()['status_code'] == 200

    def test_remove_member_not_found(self):
        """AC-16: Remove non-existent member returns 23005."""
        app = _make_app(MockAdminUser)
        with patch(f'{SERVICE_PATH}.aremove_member', new_callable=AsyncMock,
                   side_effect=UserGroupMemberNotFoundError()):
            with TestClient(app) as c:
                resp = c.delete('/api/v1/user-groups/10/members/999')
                assert resp.json()['status_code'] == 23005


# =========================================================================
# Permission Tests
# =========================================================================

class TestUserGroupPermission:

    def test_non_admin_create_denied(self):
        """AC-17: Non-admin cannot create group."""
        app = _make_app(MockNonAdminUser)
        with patch(f'{SERVICE_PATH}.acreate_group', new_callable=AsyncMock,
                   side_effect=UserGroupPermissionDeniedError()):
            with TestClient(app) as c:
                resp = c.post('/api/v1/user-groups/', json={
                    'group_name': 'ShouldFail',
                })
                assert resp.json()['status_code'] == 23006

    def test_non_admin_delete_denied(self):
        """AC-17: Non-admin cannot delete group."""
        app = _make_app(MockNonAdminUser)
        with patch(f'{SERVICE_PATH}.adelete_group', new_callable=AsyncMock,
                   side_effect=UserGroupPermissionDeniedError()):
            with TestClient(app) as c:
                resp = c.delete('/api/v1/user-groups/10')
                assert resp.json()['status_code'] == 23006

    def test_private_group_denied(self):
        """AC-19: Non-member viewing private group returns 23006."""
        app = _make_app(MockNonAdminUser)
        with patch(f'{SERVICE_PATH}.aget_group', new_callable=AsyncMock,
                   side_effect=UserGroupPermissionDeniedError()):
            with TestClient(app) as c:
                resp = c.get('/api/v1/user-groups/10')
                assert resp.json()['status_code'] == 23006


# =========================================================================
# Admin Tests
# =========================================================================

class TestUserGroupAdmins:

    def test_set_admins(self):
        """AC-20: Set group admins."""
        app = _make_app(MockAdminUser)
        result = [{'user_id': 1, 'user_name': 'admin'},
                  {'user_id': 5, 'user_name': 'manager1'}]
        with patch(f'{SERVICE_PATH}.aset_admins', new_callable=AsyncMock,
                   return_value=result):
            with TestClient(app) as c:
                resp = c.put('/api/v1/user-groups/10/admins', json={
                    'user_ids': [1, 5],
                })
                body = resp.json()
                assert body['status_code'] == 200

    def test_set_admins_not_found(self):
        """AC-20 error path: group not found."""
        app = _make_app(MockAdminUser)
        with patch(f'{SERVICE_PATH}.aset_admins', new_callable=AsyncMock,
                   side_effect=UserGroupNotFoundError()):
            with TestClient(app) as c:
                resp = c.put('/api/v1/user-groups/99999/admins', json={
                    'user_ids': [1],
                })
                assert resp.json()['status_code'] == 23000


# =========================================================================
# Request Validation Tests
# =========================================================================

class TestRequestValidation:

    def test_create_empty_name_rejected(self):
        """Pydantic validation: empty group_name rejected."""
        app = _make_app(MockAdminUser)
        with TestClient(app) as c:
            resp = c.post('/api/v1/user-groups/', json={
                'group_name': '',
            })
            assert resp.status_code == 422

    def test_create_invalid_visibility_rejected(self):
        """Pydantic validation: invalid visibility rejected."""
        app = _make_app(MockAdminUser)
        with TestClient(app) as c:
            resp = c.post('/api/v1/user-groups/', json={
                'group_name': 'Test',
                'visibility': 'invalid',
            })
            assert resp.status_code == 422

    def test_add_members_empty_list_rejected(self):
        """Pydantic validation: empty user_ids rejected."""
        app = _make_app(MockAdminUser)
        with TestClient(app) as c:
            resp = c.post('/api/v1/user-groups/10/members', json={
                'user_ids': [],
            })
            assert resp.status_code == 422
