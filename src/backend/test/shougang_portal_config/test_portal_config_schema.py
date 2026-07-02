from fastapi import FastAPI
from fastapi.testclient import TestClient

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
