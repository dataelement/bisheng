"""会话侧的 4D 输出事务端口。"""

import json

from loguru import logger

from bisheng.api.v1.schema.workflow import WorkflowEventType
from bisheng.chat_session.domain.repositories import workflow_output_repository
from bisheng.database.models.message import WORKFLOW_RESUME_OUTPUT_KEY, has_workflow_resume_output


def write_output(session, *, execution_id, workflow_id, chat_id, user_id, tenant_id, message):
    return workflow_output_repository.insert_output(
        session,
        execution_id=execution_id,
        workflow_id=workflow_id,
        chat_id=chat_id,
        user_id=user_id,
        tenant_id=tenant_id,
        category=WorkflowEventType.OutputMsg.value,
        message=message,
    )


def read_output(session, *, message_id, execution_id, workflow_id, chat_id, user_id, tenant_id):
    return workflow_output_repository.read_output(
        session,
        message_id=message_id,
        execution_id=execution_id,
        workflow_id=workflow_id,
        chat_id=chat_id,
        user_id=user_id,
        tenant_id=tenant_id,
    )


async def visible_history(messages, login_user):
    from bisheng.workflow.application.platform_agent import BrowserPlatformAgentRuntime

    visible = []
    for row in messages:
        if not has_workflow_resume_output(getattr(row, "extra", None)):
            visible.append(row)
            continue
        if login_user is None or (row.user_id, row.tenant_id) != (login_user.user_id, login_user.tenant_id):
            continue
        try:
            marker = json.loads(row.extra)[WORKFLOW_RESUME_OUTPUT_KEY]
            if marker["format"] != 1 or not row.chat_id:
                continue
            result = await BrowserPlatformAgentRuntime().read_long_task_resume_output(
                login_user, row.flow_id, f"{row.chat_id}_async_task_id", marker["execution_id"]
            )
        except Exception as exc:
            logger.debug("平台 Agent 历史输出未获授权或不可核验, error_type={}", type(exc).__name__)
            continue
        if result is not None and result["message_id"] == row.id:
            visible.append(row.model_copy(update={"extra": None}))
    return visible
