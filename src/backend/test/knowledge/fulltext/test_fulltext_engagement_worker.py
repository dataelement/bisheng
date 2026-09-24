from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import KnowledgeFulltextEngagementBulkResult
from bisheng.knowledge.domain.services.knowledge_fulltext_engagement_service import (
    settle_knowledge_fulltext_engagement_batch,
)


async def test_worker_acknowledges_terminal_items_and_retries_only_failed():
    class Queue:
        def __init__(self):
            self.acked = []
            self.retried = []

        async def ack_many(self, *, file_ids, lease_owner):
            self.acked.extend((file_id, lease_owner) for file_id in file_ids)

        async def retry_many(self, *, file_ids, lease_owner, now_epoch):
            self.retried.extend((file_id, lease_owner, now_epoch) for file_id in file_ids)

    queue = Queue()
    result = KnowledgeFulltextEngagementBulkResult(
        updated_ids=[11],
        noop_ids=[12],
        missing_ids=[13],
        failed_ids=[14],
    )

    await settle_knowledge_fulltext_engagement_batch(
        queue_repository=queue,
        result=result,
        lease_owner="worker-a",
        now_epoch=1000,
    )

    assert [item[0] for item in queue.acked] == [11, 12, 13]
    assert [item[0] for item in queue.retried] == [14]
