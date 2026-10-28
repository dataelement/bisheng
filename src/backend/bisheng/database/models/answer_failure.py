"""判断一条聊天消息是不是回答过程中的失败, 并据此标记会话."""

import json

from loguru import logger


def message_has_answer_failure(message) -> bool:
    """没做完, 或执行中真正失败, 算回答异常.

    工具还在准备阶段就失败, 并且没有进入执行, 不算. 用户自己点停止也不算.

    Args:
        message: 聊天消息. 读取 is_bot, category, extra, message.

    Returns:
        这条消息是否算回答异常.
    """
    if message is None:
        return False
    return payload_has_answer_failure(
        is_bot=bool(getattr(message, "is_bot", False)),
        category=getattr(message, "category", "") or "",
        extra=getattr(message, "extra", None),
        message=getattr(message, "message", None),
    )


def payload_has_answer_failure(*, is_bot: bool, category: str, extra, message) -> bool:
    """用已经取出的字段判断回答异常.

    Args:
        is_bot: 是否机器人消息.
        category: 消息类别.
        extra: 扩展 JSON 或字典.
        message: 消息正文.

    Returns:
        是否算回答异常.
    """
    if category == "error":
        return True
    extra_data = _load_json(extra)
    if isinstance(extra_data, dict) and _extra_failed(extra_data):
        return True
    if not is_bot:
        return False
    body = _load_json(message)
    if not isinstance(body, dict):
        return False
    if category == "node_run":
        return _node_reason_failed(body.get("reason"))
    if _is_unused_prep_failure(body):
        return False
    if category in {"tool_result", "tool_call"} and body.get("status") == "error":
        return True
    events = body.get("events")
    if isinstance(events, list) and any(_event_failed(event) for event in events):
        return True
    return False


def node_failure_should_persist(reason: str | None) -> bool:
    """节点执行失败要落库, 供审计详情显示. 用户停止不落.

    Args:
        reason: 节点结束时的失败说明.

    Returns:
        是否把这次节点结束写成失败消息.
    """
    return _node_reason_failed(reason)


def tool_output_error(raw_output) -> str | None:
    """工具结果带 error 状态时, 取出失败说明.

    Args:
        raw_output: 工具结束事件里的 output.

    Returns:
        失败说明. 没有 error 状态时返回 None.
    """
    status = getattr(raw_output, "status", None)
    if isinstance(raw_output, dict):
        status = raw_output.get("status")
    if status != "error":
        return None
    content = getattr(raw_output, "content", None)
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(raw_output, dict):
        for key in ("error", "content", "message"):
            value = raw_output.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return "工具调用失败"


def note_answer_failure(message) -> None:
    """会话已存在时把回答失败标成异常.

    会话还没建好时更新行数为 0. 调用方需要在建会话后再标一次.

    Args:
        message: 刚写入的聊天消息.
    """
    if not message_has_answer_failure(message):
        return
    chat_id = getattr(message, "chat_id", None)
    if not chat_id:
        return
    try:
        from bisheng.database.models.session import MessageSessionDao

        MessageSessionDao.mark_answer_abnormal(chat_id)
    except Exception:
        # 消息本身已经写入. 标记失败只影响审计列表, 下次失败或迁移回填可以补上.
        logger.exception("mark answer abnormal failed chat_id={}", chat_id)


def _extra_failed(extra: dict) -> bool:
    if extra.get("unfinished") is True:
        return True
    return _failed_value(extra.get("error"))


def _event_failed(event) -> bool:
    if not isinstance(event, dict):
        return False
    # 准备失败的合成事件没有进入执行, 不算异常. 原句仍留在消息里给详情展示.
    if _is_unused_prep_failure(event):
        return False
    if event.get("type") == "error":
        return True
    return _failed_value(event.get("error"))


def _is_unused_prep_failure(event: dict) -> bool:
    # init_fail_ 是准备工具时写入的合成事件, 工具没有进入本轮执行.
    return str(event.get("tool_call_id") or "").startswith("init_fail_")


def _node_reason_failed(reason) -> bool:
    if _is_user_stop(reason):
        return False
    return _failed_value(reason)


def _is_user_stop(value) -> bool:
    return isinstance(value, str) and "stop by user" in value


def _failed_value(value) -> bool:
    if value is True:
        return True
    return isinstance(value, str) and bool(value.strip())


def _load_json(value):
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None
