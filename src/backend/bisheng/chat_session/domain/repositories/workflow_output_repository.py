"""使用调用方事务保存普通 Agent 长任务的纯文本输出。"""

import json

from bisheng.database.models.message import WORKFLOW_RESUME_OUTPUT_KEY, ChatMessage


def _marker(execution_id):
    return {WORKFLOW_RESUME_OUTPUT_KEY: {"format": 1, "execution_id": execution_id}}


def insert_output(session, *, execution_id, workflow_id, chat_id, user_id, tenant_id, category, message):
    row = ChatMessage(
        chat_id=chat_id,
        flow_id=workflow_id,
        user_id=user_id,
        tenant_id=tenant_id,
        is_bot=True,
        type="over",
        category=category,
        source=0,
        files="[]",
        message=json.dumps(message, ensure_ascii=False),
        extra=json.dumps(_marker(execution_id)),
    )
    session.add(row)
    session.flush()
    return row.id


def read_output(session, *, message_id, execution_id, workflow_id, chat_id, user_id, tenant_id):
    row = session.get(ChatMessage, message_id)
    if row is None or (row.flow_id, row.chat_id, row.user_id, row.tenant_id) != (
        workflow_id,
        chat_id,
        user_id,
        tenant_id,
    ):
        return None
    try:
        marker, message = json.loads(row.extra or "{}"), json.loads(row.message)
    except (TypeError, ValueError):
        return None
    if marker != _marker(execution_id) or not isinstance(message, dict):
        return None
    return {"message_id": row.id, "message": message}
