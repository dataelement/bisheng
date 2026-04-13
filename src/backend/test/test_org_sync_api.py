"""API integration tests for F009 org sync — test DTO validation and masking.

These tests verify request/response schemas and the masking function
without requiring a running server or database.
"""

import pytest

from bisheng.org_sync.domain.schemas.org_sync_schema import (
    OrgSyncConfigCreate,
    OrgSyncConfigUpdate,
    OrgSyncConfigRead,
    OrgSyncLogRead,
    RemoteTreeNode,
    mask_sensitive_fields,
)


class TestOrgSyncConfigCreate:

    def test_valid_config(self):
        config = OrgSyncConfigCreate(
            provider='feishu',
            config_name='Test',
            auth_type='api_key',
            auth_config={'app_id': 'xxx', 'app_secret': 'yyy'},
        )
        assert config.provider == 'feishu'
        assert config.schedule_type == 'manual'

    def test_invalid_provider(self):
        with pytest.raises(ValueError, match='provider must be one of'):
            OrgSyncConfigCreate(
                provider='invalid',
                config_name='Test',
                auth_type='api_key',
                auth_config={},
            )

    def test_invalid_auth_type(self):
        with pytest.raises(ValueError, match='auth_type must be one of'):
            OrgSyncConfigCreate(
                provider='feishu',
                config_name='Test',
                auth_type='oauth',
                auth_config={},
            )

    def test_cron_schedule(self):
        config = OrgSyncConfigCreate(
            provider='generic_api',
            config_name='Test',
            auth_type='api_key',
            auth_config={'endpoint_url': 'https://api.example.com'},
            schedule_type='cron',
            cron_expression='0 2 * * *',
        )
        assert config.schedule_type == 'cron'
        assert config.cron_expression == '0 2 * * *'


class TestOrgSyncConfigUpdate:

    def test_partial_update(self):
        update = OrgSyncConfigUpdate(schedule_type='manual')
        assert update.schedule_type == 'manual'
        assert update.auth_config is None
        assert update.status is None

    def test_full_update(self):
        update = OrgSyncConfigUpdate(
            auth_config={'app_secret': 'new'},
            schedule_type='cron',
            cron_expression='0 3 * * *',
            status='disabled',
        )
        assert update.auth_config == {'app_secret': 'new'}


class TestMaskSensitiveFields:

    def test_mask_known_keys(self):
        auth = {
            'app_id': 'cli_xxx',
            'app_secret': 'secret123',
            'api_key': 'sk-xxx',
            'password': 'mypassword',
        }
        masked = mask_sensitive_fields(auth)
        assert masked['app_id'] == 'cli_xxx'
        assert masked['app_secret'] == '****'
        assert masked['api_key'] == '****'
        assert masked['password'] == '****'

    def test_mask_nested(self):
        auth = {
            'outer': 'visible',
            'nested': {'password': 'hidden', 'name': 'visible'},
        }
        masked = mask_sensitive_fields(auth)
        assert masked['outer'] == 'visible'
        assert masked['nested']['password'] == '****'
        assert masked['nested']['name'] == 'visible'

    def test_empty_dict(self):
        assert mask_sensitive_fields({}) == {}


class TestOrgSyncConfigRead:

    def test_serialization(self):
        read = OrgSyncConfigRead(
            id=1,
            provider='feishu',
            config_name='Test',
            auth_type='api_key',
            auth_config={'app_id': 'xxx', 'app_secret': '****'},
            schedule_type='manual',
            sync_status='idle',
            status='active',
        )
        data = read.model_dump(mode='json')
        assert data['id'] == 1
        assert data['auth_config']['app_secret'] == '****'


class TestOrgSyncLogRead:

    def test_defaults(self):
        log = OrgSyncLogRead(
            id=1, config_id=1, trigger_type='manual', status='running',
        )
        assert log.dept_created == 0
        assert log.error_details is None


class TestRemoteTreeNode:

    def test_tree_structure(self):
        root = RemoteTreeNode(
            external_id='root',
            name='Root',
            children=[
                RemoteTreeNode(external_id='child', name='Child'),
            ],
        )
        assert len(root.children) == 1
        assert root.children[0].external_id == 'child'
