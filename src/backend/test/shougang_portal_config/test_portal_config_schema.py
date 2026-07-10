import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from bisheng.shougang_portal_config.api.endpoints.portal_config import router
from bisheng.shougang_portal_config.domain.schemas.portal_config_schema import (
    ShougangPortalAdminConfig,
    redact_portal_admin_config,
)
from bisheng.shougang_portal_config.domain.services.portal_config_service import (
    ShougangPortalConfigService,
)


def _minimal_portal_config() -> dict:
    return {
        'domains': [],
        'sections': [],
        'document_types': [],
        'qa': {
            'welcome_message': '',
            'hot_questions': [],
            'ai_search_system_prompt': '',
            'qa_system_prompt': '',
            'quick_mode_system_prompt': '',
            'normal_mode_system_prompt': '',
            'expert_mode_system_prompt': '',
            'selected_model': '',
            'general_model': '',
            'reasoning_model': '',
            'template_categories': [],
            'templates': [],
        },
        'recommendation': {
            'provider': 'tag_feed',
            'home_strategy': 'latest',
            'detail_strategy': 'related',
        },
        'display': {
            'home': {},
            'list': {},
            'search': {},
            'detail': {},
        },
        'apps': [],
        'banners': [],
        'integrations': {},
        'site': {},
    }


def test_redact_portal_admin_config_hides_plaintext_secrets():
    config = ShougangPortalAdminConfig(
        portal=_minimal_portal_config(),
        bisheng={
            'base_url': 'http://bisheng.example.com',
            'asset_base_url': 'http://assets.example.com',
            'username': 'portal-admin',
            'timeout_seconds': 12,
            'saved_password': 'plain-password',
            'last_auth_at': '2026-06-01T00:00:00+00:00',
        },
        unified_auth={
            'enabled': True,
            'provider': 'custom',
            'client_id': 'client-id',
            'client_secret': 'plain-client-secret',
            'redirect_uri': 'https://portal.example.com/callback',
            'authorize_url': 'https://iam.example.com/authorize',
            'token_url': 'https://iam.example.com/token',
            'userinfo_url': 'https://iam.example.com/userinfo',
            'state_secret': 'plain-state-secret',
            'login_sync_hmac_secret': 'plain-login-sync-secret',
        },
    )

    view = redact_portal_admin_config(config)
    view_data = view.model_dump(mode='json')
    serialized = view.model_dump_json()

    assert config.bisheng.saved_password == 'plain-password'
    assert config.unified_auth.client_secret == 'plain-client-secret'
    assert view.bisheng.has_saved_password is True
    assert view.unified_auth.has_client_secret is True
    assert view.unified_auth.has_state_secret is True
    assert view.unified_auth.has_login_sync_hmac_secret is True
    assert 'plain-password' not in serialized
    assert 'plain-client-secret' not in serialized
    assert 'plain-state-secret' not in serialized
    assert 'plain-login-sync-secret' not in serialized
    assert 'saved_password' not in view_data['bisheng']
    assert 'client_secret' not in view_data['unified_auth']
    assert 'state_secret' not in view_data['unified_auth']
    assert 'login_sync_hmac_secret' not in view_data['unified_auth']


def test_portal_document_type_generates_missing_child_codes():
    raw_config = _minimal_portal_config()
    raw_config['document_types'] = [
        {
            'code': 'pol',
            'label': '政策制度',
            'description_examples': '  例如：管理制度、通知公告  ',
            'children': [
                {'label': '制度文件'},
                {'code': 'POL-OLD', 'label': '历史分类'},
            ],
        },
    ]

    config = ShougangPortalAdminConfig(
        portal=raw_config,
        bisheng={'base_url': 'http://bisheng.example.com'},
        unified_auth={},
    )
    children = config.portal.document_types[0].children

    assert re.fullmatch(r'POL-[A-Z0-9]{4}', children[0].code)
    assert children[0].label == '制度文件'
    assert children[1].code == 'POL-OLD'
    assert children[1].label == '历史分类'
    assert config.portal.document_types[0].description_examples == '例如：管理制度、通知公告'


def test_portal_config_round_trips_unified_url_application():
    raw_config = _minimal_portal_config()
    raw_config['agent_config'] = {
        'categories': [{'id': 'operations', 'name': '运营', 'enabled': True}],
        'applications': [
            {
                'id': 'operations-dashboard',
                'type': 'url',
                'workflow_id': '',
                'url': 'https://apps.example.com/dashboard',
                'name': '运营看板',
                'desc': '运营数据查看',
                'category_id': 'operations',
                'tags': ['运营'],
                'icon': 'BarChart3',
                'icon_image_url': '/uploads/app-icons/dashboard.png',
                'color': '#2563eb',
                'bg': '#eff6ff',
                'enabled': True,
            },
        ],
    }

    config = ShougangPortalAdminConfig(
        portal=raw_config,
        bisheng={'base_url': 'http://bisheng.example.com'},
        unified_auth={},
    )
    saved_payload = config.model_dump(mode='json')
    reloaded = ShougangPortalAdminConfig.model_validate(saved_payload)

    assert 'apps' not in saved_payload['portal']
    applications = reloaded.portal.agent_config.applications
    assert len(applications) == 1
    assert applications[0].type == 'url'
    assert applications[0].url == 'https://apps.example.com/dashboard'
    assert applications[0].icon_image_url == '/uploads/app-icons/dashboard.png'


def test_portal_config_migrates_legacy_agents_and_only_valid_url_apps():
    raw_config = _minimal_portal_config()
    raw_config['agent_config'] = {
        'categories': [{'id': 'qa', 'name': 'AI 问答', 'enabled': True}],
        'agents': [
            {
                'id': 'policy-agent',
                'workflow_id': 'workflow-1',
                'name': '制度助手',
                'category_id': 'qa',
                'icon': 'BookOpen',
                'color': '#2563eb',
                'bg': '#eff6ff',
                'enabled': True,
            },
        ],
    }
    raw_config['apps'] = [
        {
            'id': 9,
            'name': '经营分析',
            'icon': 'Globe',
            'desc': '经营数据',
            'color': '#2563eb',
            'bg': '#eff6ff',
            'url': 'https://apps.example.com/analysis',
            'enabled': True,
        },
        {
            'id': 10,
            'name': '不迁移',
            'icon': 'Globe',
            'desc': '',
            'color': '#2563eb',
            'bg': '#eff6ff',
            'url': 'javascript:alert(1)',
            'enabled': True,
        },
    ]

    config = ShougangPortalAdminConfig(
        portal=raw_config,
        bisheng={'base_url': 'http://bisheng.example.com'},
        unified_auth={},
    )

    assert [category.id for category in config.portal.agent_config.categories] == ['qa', 'url-apps']
    assert [item.id for item in config.portal.agent_config.applications] == ['policy-agent', 'url-app-9']
    assert [item.type for item in config.portal.agent_config.applications] == ['workflow', 'url']
    assert 'apps' not in config.portal.model_dump(mode='json')


def test_portal_config_rejects_invalid_url_application():
    raw_config = _minimal_portal_config()
    raw_config['agent_config'] = {
        'categories': [{'id': 'url-apps', 'name': 'URL 应用', 'enabled': True}],
        'applications': [
            {
                'id': 'invalid-url',
                'type': 'url',
                'url': 'data:text/html,invalid',
                'name': '无效应用',
                'category_id': 'url-apps',
                'icon': 'Globe',
                'color': '#2563eb',
                'bg': '#eff6ff',
            },
        ],
    }

    with pytest.raises(ValidationError):
        ShougangPortalAdminConfig(
            portal=raw_config,
            bisheng={'base_url': 'http://bisheng.example.com'},
            unified_auth={},
        )


def test_internal_config_endpoint_returns_full_config_without_auth(monkeypatch):
    config = ShougangPortalAdminConfig(
        portal=_minimal_portal_config(),
        bisheng={
            'base_url': 'http://bisheng.example.com',
            'username': 'portal-admin',
            'saved_password': 'plain-password',
        },
        unified_auth={
            'client_secret': 'plain-client-secret',
            'state_secret': 'plain-state-secret',
            'login_sync_hmac_secret': 'plain-login-sync-secret',
        },
    )

    async def fake_get_config():
        return config

    monkeypatch.setattr(ShougangPortalConfigService, 'get_config', staticmethod(fake_get_config))
    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).get('/shougang-portal/config/internal')

    assert response.status_code == 200
    body = response.json()
    assert body['status_code'] == 200
    assert body['data']['bisheng']['saved_password'] == 'plain-password'
    assert body['data']['unified_auth']['client_secret'] == 'plain-client-secret'
    assert body['data']['unified_auth']['state_secret'] == 'plain-state-secret'
    assert body['data']['unified_auth']['login_sync_hmac_secret'] == 'plain-login-sync-secret'
