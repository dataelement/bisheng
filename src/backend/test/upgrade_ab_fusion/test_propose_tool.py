"""工具按 tool_key bind, 不按名合并."""

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.propose_tool import propose


def test_same_key_binds():
    result = propose(
        [{"id": "9", "name": "A工具", "tool_key": "k1"}],
        [{"id": "2", "name": "B工具", "tool_key": "k1"}],
    )
    assert result["map"][0]["action"] == "bind"
    assert result["map"][0]["a_tool_id"] == "9"
    assert result["conflict"] == []


def test_same_name_different_key_is_manual():
    result = propose(
        [{"id": "9", "name": "搜索", "tool_key": "a"}],
        [{"id": "2", "name": "搜索", "tool_key": "b"}],
    )
    assert result["map"][0]["action"] == "create"
    assert result["map"][0]["a_tool_id"] == ""
    assert result["map"][0]["a_tool_key"] == "b"
    assert result["manual"] == []


def test_empty_key_creates_generated_key():
    result = propose(
        [{"id": "9", "name": "A工具", "tool_key": "k1"}],
        [{"id": "2", "name": "B工具", "tool_key": ""}],
    )
    assert result["map"][0]["action"] == "create"
    assert result["map"][0]["a_tool_key"] == "btool_2"
    assert result["manual"] == []
