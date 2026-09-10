"""回答反馈的公共读取规则。"""

import json


def feedback_allowed(message) -> bool:
    if not message.is_bot or message.type not in {"end", "over", "end_cover", "bot", "answer"}:
        return False
    if message.category not in {
        "answer",
        "agent_answer",
        "stream_msg",
        "output_msg",
        "output_with_input_msg",
        "output_with_choose_msg",
    }:
        return False
    if message.remark in {"break_answer", "inaction"} or not message.message:
        return False
    try:
        extra = json.loads(message.extra or "{}")
    except (ValueError, TypeError):
        return False
    return isinstance(extra, dict) and not extra.get("error") and not extra.get("unfinished")


def feedback_fields(message) -> dict:
    return {
        "liked": message.liked or 0,
        "comment": "" if message.remark in {"break_answer", "inaction"} else (message.remark or ""),
        "feedback_allowed": feedback_allowed(message),
    }
