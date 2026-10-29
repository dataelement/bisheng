"""Preset extra: tool row first, category only when the row is empty."""

from types import SimpleNamespace

from bisheng.tool.domain.services.executor import ToolExecutor


def test_parse_preset_extra_uses_tool_row_when_present():
    tool = SimpleNamespace(extra='{"type": "local"}')
    tool_type = SimpleNamespace(extra='{"type": "container"}')
    assert ToolExecutor.parse_preset_extra(tool, tool_type) == {"type": "local"}


def test_parse_preset_extra_falls_back_to_category_when_row_empty():
    tool = SimpleNamespace(extra=None)
    tool_type = SimpleNamespace(extra='{"type": "container"}')
    assert ToolExecutor.parse_preset_extra(tool, tool_type) == {"type": "container"}


def test_parse_preset_extra_empty_string_row_falls_back():
    tool = SimpleNamespace(extra="")
    tool_type = SimpleNamespace(extra='{"type": "e2b"}')
    assert ToolExecutor.parse_preset_extra(tool, tool_type) == {"type": "e2b"}


def test_parse_preset_extra_copies_dict_payload():
    stored = {"type": "container", "config": {"container": {}}}
    tool = SimpleNamespace(extra=stored)
    parsed = ToolExecutor.parse_preset_extra(tool, None)
    parsed["type"] = "local"
    parsed["config"]["container"]["keep_session"] = True
    assert stored["type"] == "container"
    assert stored["config"]["container"] == {}


def test_parse_preset_extra_keeps_non_json_runtime_objects():
    # The task-mode code interpreter stores E2B WriteEntry objects in extra before
    # init; a JSON round trip raised TypeError and silently dropped the tool.
    from e2b.sandbox.filesystem.filesystem import WriteEntry

    entry = WriteEntry(data="/ws/skills/a.py", path="./skills/a.py")
    stored = {"type": "local", "config": {"e2b": {"file_list": [entry]}}}
    parsed = ToolExecutor.parse_preset_extra(SimpleNamespace(extra=stored), None)
    assert parsed["config"]["e2b"]["file_list"][0].path == "./skills/a.py"
    parsed["config"]["e2b"]["file_list"].clear()
    assert len(stored["config"]["e2b"]["file_list"]) == 1
