"""Annotation task read policy shared by task and conversation adapters."""

from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.database.models.mark_task import MarkTaskDao
from bisheng.database.models.session import MessageSessionDao
from bisheng.permission.application.identity import is_current_tenant_administrator


async def require_mark_task_reader(task_id: int, login_user, chat_id: str | None = None):
    """Same membership question as the mark-task list.

    Creators, assignees, platform admins, and the current tenant's administrator
    (the list's ``is_current_tenant_administrator`` gate) may open a task that
    the list already returned. Soft-deleted chats stay out: the annotation
    queues also filter ``include_delete=False``.
    """
    task = MarkTaskDao.get_task_byid(task_id)
    if task is None:
        raise NotFoundError()
    tenant_id = get_current_tenant_id() or login_user.tenant_id
    assignees = {value.strip() for value in (task.process_users or "").split(",")}
    allowed = (
        login_user.is_admin()
        or task.create_id == login_user.user_id
        or str(login_user.user_id) in assignees
        or await is_current_tenant_administrator(login_user)
    )
    if task.tenant_id != tenant_id or not allowed:
        raise UnAuthorizedError()
    if chat_id:
        session = MessageSessionDao.get_one(chat_id)
        if (
            session is None
            or session.is_delete
            or session.tenant_id != tenant_id
            or session.flow_id not in {value.strip() for value in task.app_id.split(",") if value.strip()}
        ):
            raise UnAuthorizedError()
    return task
