"""Tests for Shougang WeChat message push config loading.

The shared conftest pre-mocks ``bisheng.common.services.config_service`` to avoid
circular imports in the broader test suite. These tests need the real
``ConfigService`` class, so we temporarily restore the real module at import time.
"""

import sys
from unittest.mock import MagicMock, patch

# Names of modules pre-mocked by conftest.
_MOCKED_MODULES = [
    "bisheng.common.services",
    "bisheng.common.services.base",
    "bisheng.common.services.config_service",
]

# Stash the mocks and remove them so the real package can load.
_stashed_mocks = {name: sys.modules.pop(name, None) for name in _MOCKED_MODULES}

# The real bisheng.common.services.__init__ imports telemetry_service, which pulls
# in Elasticsearch. Stub it to keep the import chain light for these unit tests.
sys.modules["bisheng.common.services.telemetry"] = MagicMock()
sys.modules["bisheng.common.services.telemetry.telemetry_service"] = MagicMock()

from bisheng.common.services.config_service import ConfigService  # noqa: E402
from bisheng.core.config.settings import ShougangWeChatMessagePushConf  # noqa: E402

# Restore the pre-mocked modules so the rest of the test suite is unaffected.
for name, mock in _stashed_mocks.items():
    if mock is not None:
        sys.modules[name] = mock


def _make_settings() -> ConfigService:
    return ConfigService(
        in_app_message_forwarding={
            "shougang_wechat": {
                "enabled": True,
                "api_url": "https://yaml.example.com/push",
                "id": "yaml-id",
                "agentid": "yaml-agentid",
                "key": "yaml-key",
                "sys_id": "1",
                "msg_type": "text",
                "timeout_seconds": 10,
                "max_retries": 3,
                "batch_size": 100,
                "scan_interval_seconds": 30,
                "retry_base_seconds": 60,
                "retry_max_seconds": 3600,
                "templates": {
                    "qa_expert_invited": "yaml invited",
                    "qa_expert_answered": "yaml answered",
                    "qa_answer_commented": "yaml commented",
                    "qa_answer_accepted": "yaml accepted",
                },
            }
        }
    )


def test_shougang_wechat_defaults_disabled():
    conf = ShougangWeChatMessagePushConf()
    assert conf.enabled is False
    assert conf.api_url == "https://mobms.sggf.com.cn:30201/madp-app/madp/qywxPush-api/pushMessage"


def test_shougang_wechat_conf_falls_back_to_yaml_when_db_block_missing():
    service = _make_settings()
    with patch.object(ConfigService, "get_all_config", return_value={}):
        conf = service.get_shougang_wechat_message_push_conf()
    assert conf.enabled is True
    assert conf.api_url == "https://yaml.example.com/push"
    assert conf.agentid == "yaml-agentid"


def test_shougang_wechat_conf_merges_partial_db_block_with_yaml():
    """A DB block without ``enabled`` should inherit the YAML value, not the Pydantic default."""
    service = _make_settings()
    with patch.object(
        ConfigService,
        "get_all_config",
        return_value={
            "in_app_message_forwarding": {
                "shougang_wechat": {
                    "api_url": "https://db.example.com/push",
                }
            }
        },
    ):
        conf = service.get_shougang_wechat_message_push_conf()
    assert conf.enabled is True  # inherited from YAML
    assert conf.api_url == "https://db.example.com/push"  # overridden by DB
    assert conf.agentid == "yaml-agentid"  # inherited from YAML


def test_shougang_wechat_conf_db_explicit_disable_respected():
    service = _make_settings()
    with patch.object(
        ConfigService,
        "get_all_config",
        return_value={
            "in_app_message_forwarding": {
                "shougang_wechat": {
                    "enabled": False,
                }
            }
        },
    ):
        conf = service.get_shougang_wechat_message_push_conf()
    assert conf.enabled is False
    assert conf.api_url == "https://yaml.example.com/push"  # inherited from YAML


def test_shougang_wechat_conf_invalid_db_block_falls_back_to_yaml():
    service = _make_settings()
    with patch.object(
        ConfigService,
        "get_all_config",
        return_value={
            "in_app_message_forwarding": {
                "shougang_wechat": {
                    "enabled": "not-a-boolean",
                }
            }
        },
    ):
        conf = service.get_shougang_wechat_message_push_conf()
    assert conf.enabled is True
    assert conf.api_url == "https://yaml.example.com/push"
