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


def test_shipped_initdb_config_has_no_retired_keys():
    from pathlib import Path

    import yaml

    shipped = yaml.safe_load((Path(__file__).parents[2] / "bisheng" / "initdb_config.yaml").read_text(encoding="utf-8"))
    assert not set(RETIRED) & set(shipped.get("linsight") or {})
