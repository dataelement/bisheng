"""Parse the tool-result shapes the release plan names. Do not treat the whole event as 6."""

from __future__ import annotations

import ast
import json
import re
from typing import Any

_OFFLOAD_PATH = re.compile(r"/large_tool_results/([A-Za-z0-9._\-]+)")
_NUMBERED_PREVIEW = re.compile(r"^\s*(\d+)\t(.*)$")
_PRINTED_ENDS = re.compile(r"^FIRST:(.*)\nLAST:(.*)\nCOUNT:(\d+)\s*$", re.M)


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


def offload_from_text(text: str) -> dict | None:
    """Path and the preview's first line, last line, and line count.

    The system writes the original tool text to ``large_tool_results/<id>`` and
    replaces the message with a head-and-tail preview whose line numbers run to
    the original line count. No length threshold is applied here.
    """
    if "Tool result too large" not in text:
        return None
    found = _OFFLOAD_PATH.search(text)
    if found is None:
        return None
    numbered = []
    for line in text.splitlines():
        match = _NUMBERED_PREVIEW.match(line)
        if match:
            numbered.append((int(match.group(1)), match.group(2)))
    if not numbered or numbered[0][0] != 1:
        return None
    last_number, last_line = numbered[-1]
    return {
        "path": f"large_tool_results/{found.group(1)}",
        "first": numbered[0][1],
        "last": last_line,
        "count": last_number,
    }


def printed_ends(log: str) -> tuple[str, str, int] | None:
    """FIRST / LAST / COUNT lines the code tool was asked to print."""
    match = _PRINTED_ENDS.search(log)
    if match is None:
        return None
    return match.group(1).strip(), match.group(2).strip(), int(match.group(3))


def offload_notice(tasks: list) -> dict | None:
    for step in history_steps(tasks):
        output = step.get("output")
        if isinstance(output, str):
            text = output
        elif output is None:
            continue
        else:
            text = json.dumps(output, ensure_ascii=False)
        notice = offload_from_text(text)
        if notice:
            return notice
    return None


def step_text(step: dict) -> str:
    output = step.get("output")
    params = step.get("params")
    return f"{output or ''}\n{params or ''}"
