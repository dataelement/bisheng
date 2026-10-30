"""D16: a code node whose main() returns nothing reports 28008, not a generic error."""

from __future__ import annotations

import pytest

from bisheng.common.errcode.sandbox import SandboxCodeNodeNoResultError
from bisheng.workflow.nodes.code.code import CodeNode


def _bare_node(outputs: list[dict]) -> CodeNode:
    # Skip BaseNode.__init__: only the output parser is under test.
    node = object.__new__(CodeNode)
    node.name = "code_1"
    node._code_output = outputs
    return node


def test_none_result_raises_no_result_error():
    node = _bare_node([{"key": "a"}])
    with pytest.raises(SandboxCodeNodeNoResultError) as err:
        node._parse_code_output(None)
    assert err.value.code == 28008


@pytest.mark.parametrize("value", [[1, 2], "text", 3, 0, False])
def test_non_dict_result_keeps_type_message(value):
    node = _bare_node([{"key": "a"}])
    with pytest.raises(Exception, match="main function output must be dict") as err:
        node._parse_code_output(value)
    assert not isinstance(err.value, SandboxCodeNodeNoResultError)


def test_dict_result_picks_declared_keys():
    node = _bare_node([{"key": "a"}])
    assert node._parse_code_output({"a": 1, "b": 2}) == {"a": 1}
