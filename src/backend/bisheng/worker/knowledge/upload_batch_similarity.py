"""Drop queued same-batch repairs. Marking happens only on the file that just parsed."""

from bisheng.worker.main import bisheng_celery


@bisheng_celery.task(acks_late=True)
def reconcile_upload_batch_similarity(batch_id: int, epoch: int) -> str:
    from bisheng.knowledge.domain.services.knowledge_upload_batch_service import reconcile_upload_batch
    from bisheng.worker._asyncio_utils import run_async_task

    return run_async_task(lambda: reconcile_upload_batch(batch_id, epoch))
