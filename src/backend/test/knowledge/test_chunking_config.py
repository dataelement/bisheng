import pytest
from pydantic import ValidationError

from bisheng.api.v1.endpoints import save_config
from bisheng.common.errcode.server import SystemConfigInvalidError
from bisheng.core.config.settings import KnowledgeConf


def test_knowledge_chunking_config_defaults_and_accepts_override():
    assert KnowledgeConf().chunking.max_chunk_chars == 10000
    assert KnowledgeConf(chunking={"max_chunk_chars": 4096}).chunking.max_chunk_chars == 4096


def test_knowledge_chunking_config_rejects_limit_below_default_chunk_size():
    with pytest.raises(ValidationError):
        KnowledgeConf(chunking={"max_chunk_chars": 999})


def test_system_config_save_rejects_invalid_chunk_limit_before_persisting():
    yaml_data = "knowledges:\n  chunking:\n    max_chunk_chars: 999\n"

    with pytest.raises(SystemConfigInvalidError):
        save_config({"data": yaml_data}, admin_user=object())
