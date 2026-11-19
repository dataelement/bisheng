"""昆联工作流资料同步异步投递与定时重试 Celery 任务。"""

from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery
from bisheng.workflow.application.kunlian_snapshot_sync import get_kunlian_snapshot_sync_service


@bisheng_celery.task(name="kunlian.workflow_snapshot_deliver", shared=False)
def deliver_workflow_snapshot(event_id: str):
    """投递单条持久化的昆联工作流快照同步事件。"""
    headers = getattr(deliver_workflow_snapshot.request, "headers", None) or {}
    tenant_id = headers.get("tenant_id")
    if type(tenant_id) is not int or tenant_id <= 0:
        raise ValueError("Missing trusted tenant header")

    async def execute():
        service = get_kunlian_snapshot_sync_service()
        return await service.deliver_event(tenant_id, event_id)

    return run_async_task(execute)


@bisheng_celery.task(name="kunlian.workflow_snapshot_reconcile", shared=False)
def reconcile_workflow_snapshots(limit: int = 100):
    """定时扫描到期的 PENDING / RETRYING 事件，实现退避重试与进程重启恢复。"""

    async def execute():
        service = get_kunlian_snapshot_sync_service()
        return await service.reconcile_due_events(limit=limit)

    return run_async_task(execute)
