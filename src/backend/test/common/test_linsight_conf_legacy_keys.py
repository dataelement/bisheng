"""F087 P2: retired task-mode config keys are gone, and old configs still load (AC-22, AC-23).

Deployed environments keep these keys in the database config row and in their
config.yaml; ``LinsightConf`` ignores unknown keys, so they must keep loading.
"""

import pytest

from bisheng.core.config.settings import LinsightConf

RETIRED = (
    "tool_buffer",
    "file_content_length",
    "max_file_num",
    "max_knowledge_num",
    "retry_temperature",
    "max_file_content_num",
)


@pytest.mark.parametrize("key", RETIRED)
def test_retired_key_is_not_a_field(key):
    assert key not in LinsightConf.model_fields


def test_config_carrying_retired_keys_still_loads():
    legacy = {
        "tool_buffer": 100000,
        "file_content_length": 5000,
        "max_file_num": 5,
        "max_knowledge_num": 20,
        "retry_temperature": 1,
        "max_file_content_num": 3,
        "max_steps": 2500,
    }

    conf = LinsightConf(**legacy)

    assert conf.max_steps == 2500
    assert not hasattr(conf, "tool_buffer")


LEGACY_DB_CONFIG = {"linsight": {"tool_buffer": 100000, "max_file_num": 5, "max_steps": 2500}}


def test_db_config_with_retired_keys_loads_through_the_sync_loader(monkeypatch):
    """The real loader copies DB keys with setattr, which pydantic rejects for unknown fields."""
    from bisheng.common.services.config_service import settings

    monkeypatch.setattr(type(settings), "get_all_config", lambda self: LEGACY_DB_CONFIG)

    conf = settings.get_linsight_conf()

    assert conf.max_steps == 2500
    assert not hasattr(conf, "tool_buffer")


async def test_db_config_with_retired_keys_loads_through_the_async_loader(monkeypatch):
    from bisheng.common.services.config_service import settings

    async def fake_all_config(self):
        return LEGACY_DB_CONFIG

    monkeypatch.setattr(type(settings), "aget_all_config", fake_all_config)

    conf = await settings.aget_linsight_conf()

    assert conf.max_steps == 2500
    assert not hasattr(conf, "tool_buffer")


def test_shipped_initdb_config_has_no_retired_keys():
    from pathlib import Path

    import yaml

    shipped = yaml.safe_load((Path(__file__).parents[2] / "bisheng" / "initdb_config.yaml").read_text(encoding="utf-8"))
    assert not set(RETIRED) & set(shipped.get("linsight") or {})
