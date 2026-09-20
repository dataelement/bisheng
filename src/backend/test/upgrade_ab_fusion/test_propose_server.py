"""llm_server 按 type+name bind."""

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.propose_server import propose


def test_same_type_and_name_binds():
    result = propose(
        [{"id": "3", "name": "openai", "type": "openai"}],
        [{"id": "1", "name": "openai", "type": "openai"}],
    )
    assert result["map"][0]["a_server_id"] == "3"


def test_name_only_does_not_bind():
    result = propose(
        [{"id": "3", "name": "openai", "type": "openai"}],
        [{"id": "1", "name": "openai", "type": "azure"}],
    )
    assert result["map"][0]["action"] == "create"
    assert result["map"][0]["a_server_id"] == ""
    assert result["manual"] == []
