"""F021 WeCom auth_config schema validation tests.

Covers AC-36 (missing required fields), AC-37 (invalid allow_dept_ids),
and confirms AC-38 masking is handled by F009's existing SENSITIVE_KEYS.
"""

import pytest

from bisheng.org_sync.domain.schemas.org_sync_schema import (
    OrgSyncConfigCreate,
    OrgSyncConfigUpdate,
    mask_sensitive_fields,
)


VALID_WECOM_AUTH = {
    'corpid': 'wwa04427c3f62b5769',
    'corpsecret': 'qVldC5Kp5houi1fG8yBvmZMaufN2KmFNkijdls1DdVc',
    'agent_id': '1000017',
}


def _build_create(auth_config: dict) -> None:
    OrgSyncConfigCreate(
        provider='wecom',
        config_name='WeCom Prod',
        auth_type='api_key',
        auth_config=auth_config,
    )


class TestWeComCreateValidation:

    def test_valid_wecom_config(self):
        # Happy path — no exception
        _build_create(VALID_WECOM_AUTH)

    def test_valid_wecom_config_with_allow_dept_ids(self):
        auth = {**VALID_WECOM_AUTH, 'allow_dept_ids': [1, 2, 3]}
        _build_create(auth)

    @pytest.mark.parametrize('missing_key', ['corpid', 'corpsecret', 'agent_id'])
    def test_missing_required_field(self, missing_key: str):
        auth = {k: v for k, v in VALID_WECOM_AUTH.items() if k != missing_key}
        with pytest.raises(ValueError, match=missing_key):
            _build_create(auth)

    @pytest.mark.parametrize('empty_value', ['', '   ', None])
    def test_empty_or_none_required_field(self, empty_value):
        auth = {**VALID_WECOM_AUTH, 'corpid': empty_value}
        with pytest.raises(ValueError, match='corpid'):
            _build_create(auth)

    def test_non_string_required_field(self):
        auth = {**VALID_WECOM_AUTH, 'agent_id': 1000017}  # int, not str
        with pytest.raises(ValueError, match='agent_id'):
            _build_create(auth)

    def test_corpsecret_cannot_be_masked_on_create(self):
        # Create path rejects the '****' placeholder — user must supply plaintext.
        auth = {**VALID_WECOM_AUTH, 'corpsecret': '****'}
        with pytest.raises(ValueError, match='corpsecret'):
            _build_create(auth)

    def test_invalid_allow_dept_ids_not_list(self):
        auth = {**VALID_WECOM_AUTH, 'allow_dept_ids': '1,2,3'}
        with pytest.raises(ValueError, match='allow_dept_ids'):
            _build_create(auth)

    @pytest.mark.parametrize('bad_item', ['1', 1.5, None, True])
    def test_invalid_allow_dept_ids_non_int_elements(self, bad_item):
        auth = {**VALID_WECOM_AUTH, 'allow_dept_ids': [1, bad_item]}
        with pytest.raises(ValueError, match='allow_dept_ids'):
            _build_create(auth)

    def test_non_wecom_provider_skips_wecom_validation(self):
        # Feishu provider should ignore the WeCom-specific rules.
        OrgSyncConfigCreate(
            provider='feishu',
            config_name='Feishu',
            auth_type='api_key',
            auth_config={'app_id': 'x', 'app_secret': 'y'},
        )


class TestWeComUpdateValidation:

    def test_allow_dept_ids_on_update_validated(self):
        with pytest.raises(ValueError, match='allow_dept_ids'):
            OrgSyncConfigUpdate(auth_config={'allow_dept_ids': 'bad'})

    def test_update_allows_masked_corpsecret(self):
        # The '****' sentinel tells the Service layer "keep stored secret".
        update = OrgSyncConfigUpdate(auth_config={'corpsecret': '****'})
        assert update.auth_config == {'corpsecret': '****'}

    def test_update_partial_auth_config_ok(self):
        # Partial update without allow_dept_ids or secret is accepted.
        update = OrgSyncConfigUpdate(auth_config={'agent_id': '1000018'})
        assert update.auth_config == {'agent_id': '1000018'}


class TestCorpSecretAutoMasked:
    """AC-38 — confirm F009 existing mask_sensitive_fields already handles corpsecret."""

    def test_corpsecret_substring_match(self):
        masked = mask_sensitive_fields({
            'corpid': 'wwa04427c3f62b5769',
            'corpsecret': 'qVldC5KpHOUI',
            'agent_id': '1000017',
            'allow_dept_ids': [1, 2],
        })
        assert masked['corpsecret'] == '****'
        assert masked['corpid'] == 'wwa04427c3f62b5769'
        assert masked['agent_id'] == '1000017'
        assert masked['allow_dept_ids'] == [1, 2]

    def test_nested_dict_masking(self):
        masked = mask_sensitive_fields({
            'outer': {'corpsecret': 'SECRET', 'value': 42},
        })
        assert masked['outer']['corpsecret'] == '****'
        assert masked['outer']['value'] == 42
