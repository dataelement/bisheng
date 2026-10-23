"""Parse the tool-result shapes the release plan names. Do not treat the whole event as 6."""

from __future__ import annotations

import ast
import json
from typing import Any


def parse_object(value: Any) -> dict | None:
    """Dict, JSON object, or a Python dict literal. Anything else is not a tool result."""
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text.startswith("{"):
        return None
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        loaded = None
    if isinstance(loaded, dict):
        return loaded
    try:
        literal = ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return None
    return literal if isinstance(literal, dict) else None


def _after_tool_output(value: str) -> dict | None:
    marker = "Tool Output:"
    if marker not in value:
        return None
    return parse_object(value.split(marker, 1)[1].strip().rstrip(",").strip())


def log_sum(result: dict | None) -> bool:
    """Container and local: exitcode 0 and log.strip() == '6'. The whole object is not '6'."""
    if not result or "log" not in result:
        return False
    log = result.get("log")
    if not isinstance(log, str) or log.strip() != "6":
        return False
    if str(result).strip() == "6":
        return False
    return result.get("exitcode") == 0


def e2b_sum(result: dict | None) -> bool:
    """e2b has no log field. stdout is a list of strings."""
    if not result or "log" in result:
        return False
    stdout = result.get("stdout")
    if not isinstance(stdout, list):
        return False
    return "".join(str(item) for item in stdout).strip() == "6"


def walk_log_items(log_data: Any):
    if not isinstance(log_data, list):
        return
    for row in log_data:
        if isinstance(row, dict):
            yield row
        elif isinstance(row, list):
            for item in row:
                if isinstance(item, dict):
                    yield item


def workflow_tool_result(frame: dict) -> dict | None:
    """Agent node end: category node_run, message.log_data, type tool, key is the tool name."""
    if frame.get("category") != "node_run" or frame.get("type") != "end":
        return None
    message = frame.get("message")
    if not isinstance(message, dict):
        return None
    for item in walk_log_items(message.get("log_data")):
        if item.get("type") != "tool" or item.get("key") != "bisheng_code_interpreter":
            continue
        value = item.get("value")
        if isinstance(value, str):
            return _after_tool_output(value) or parse_object(value)
        return parse_object(value)
    return None


def code_output_values(frame: dict) -> dict | None:
    if frame.get("category") != "node_run" or frame.get("type") != "end":
        return None
    message = frame.get("message")
    if not isinstance(message, dict):
        return None
    for item in walk_log_items(message.get("log_data")):
        if item.get("key") != "code_output":
            continue
        value = item.get("value")
        return value if isinstance(value, dict) else None
    return None


def output_msg_text(frame: dict) -> str | None:
    if frame.get("category") != "output_msg" or frame.get("type") != "over":
        return None
    message = frame.get("message")
    if isinstance(message, dict):
        msg = message.get("msg")
        return msg if isinstance(msg, str) else None
    return None


def assistant_tool_result(frame: dict) -> dict | None:
    if frame.get("category") != "tool" or frame.get("type") != "end":
        return None
    message = frame.get("message")
    payload = parse_object(message) if isinstance(message, str) else message if isinstance(message, dict) else None
    if not payload or payload.get("tool_key") != "bisheng_code_interpreter":
        return None
    output = payload.get("output")
    return parse_object(output)


def daily_tool_result(event_name: str, data: dict) -> dict | None:
    """SSE event name is message. The tool end is category agent_tool_call."""
    if event_name != "message":
        return None
    if data.get("category") != "agent_tool_call" or data.get("type") != "end":
        return None
    message = data.get("message")
    if not isinstance(message, dict) or message.get("tool_name") != "bisheng_code_interpreter":
        return None
    results = message.get("results")
    found = parse_object(results)
    if found:
        return found
    if isinstance(results, list):
        for item in results:
            if isinstance(item, dict) and "text" in item:
                found = parse_object(item.get("text"))
                if found:
                    return found
    return None


def history_steps(tasks: list) -> list[dict]:
    steps: list[dict] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        history = task.get("history")
        if isinstance(history, list):
            steps.extend(item for item in history if isinstance(item, dict))
    return steps


def task_tool_results(tasks: list, name: str = "bisheng_code_interpreter") -> list[dict]:
    found = []
    for step in history_steps(tasks):
        if step.get("name") != name or step.get("status") not in (None, "end"):
            continue
        parsed = parse_object(step.get("output"))
        if parsed:
            found.append({"step": step, "result": parsed})
    return found


def chosen_tool_result(results: list, accept) -> dict | None:
    """Any result accept() allows. Otherwise the last result, so a failure still shows what ran."""
    present = [item for item in results if item]
    for item in present:
        if accept(item):
            return item
    return present[-1] if present else None


def step_text(step: dict) -> str:
    output = step.get("output")
    params = step.get("params")
    return f"{output or ''}\n{params or ''}"
