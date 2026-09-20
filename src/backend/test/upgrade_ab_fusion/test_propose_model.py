"""模型按 provider+model_name bind, 对不上则 create."""

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.propose_model import propose


def test_same_provider_and_name_binds():
    result = propose(
        [{"id": "3", "provider": "openai", "model_name": "gpt-4"}],
        [{"id": "1", "provider": "openai", "model_name": "gpt-4"}],
    )
    assert result["map"][0]["action"] == "bind"
    assert result["map"][0]["a_model_id"] == "3"


def test_unmatched_creates():
    result = propose(
        [{"id": "3", "provider": "openai", "model_name": "gpt-4"}],
        [{"id": "1", "provider": "azure", "model_name": "gpt-4"}],
    )
    assert result["map"][0]["action"] == "create"
    assert result["map"][0]["a_model_id"] == ""
    assert result["manual"] == []
