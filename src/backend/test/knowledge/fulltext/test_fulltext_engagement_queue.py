from types import SimpleNamespace

from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_engagement_repository_impl import (
    KnowledgeFulltextEngagementQueueRepositoryImpl,
)


class InMemoryRedis:
    def __init__(self):
        self.pending: dict[str, int] = {}
        self.processing: dict[str, int] = {}
        self.owners: dict[str, str] = {}

    async def zadd(self, _key, mapping, nx=False):
        added = 0
        for member, score in mapping.items():
            if nx and member in self.pending:
                continue
            added += member not in self.pending
            self.pending[member] = int(score)
        return added

    async def eval(self, script, _key_count, *args):
        if script == KnowledgeFulltextEngagementQueueRepositoryImpl.CLAIM_SCRIPT:
            now_epoch, lease_until, owner, limit = int(args[3]), int(args[4]), str(args[5]), int(args[6])
            members = [
                member
                for member, _score in sorted(self.pending.items(), key=lambda item: (item[1], item[0]))
                if self.pending[member] <= now_epoch
            ][:limit]
            for member in members:
                self.pending.pop(member)
                self.processing[member] = lease_until
                self.owners[member] = owner
            return members
        if script == KnowledgeFulltextEngagementQueueRepositoryImpl.ACK_SCRIPT:
            member, owner = str(args[2]), str(args[3])
            if self.owners.get(member) != owner:
                return 0
            self.processing.pop(member, None)
            self.owners.pop(member, None)
            return 1
        if script == KnowledgeFulltextEngagementQueueRepositoryImpl.RETRY_SCRIPT:
            member, owner, ready_at = str(args[3]), str(args[4]), int(args[5])
            if self.owners.get(member) != owner:
                return 0
            self.processing.pop(member, None)
            self.owners.pop(member, None)
            self.pending.setdefault(member, ready_at)
            return 1
        if script == KnowledgeFulltextEngagementQueueRepositoryImpl.RECLAIM_SCRIPT:
            now_epoch = int(args[3])
            members = [member for member, lease_until in self.processing.items() if lease_until <= now_epoch]
            for member in members:
                self.pending.setdefault(member, now_epoch)
                self.processing.pop(member, None)
                self.owners.pop(member, None)
            return len(members)
        raise AssertionError("unexpected Lua script")


def _repository() -> KnowledgeFulltextEngagementQueueRepositoryImpl:
    redis = InMemoryRedis()
    return KnowledgeFulltextEngagementQueueRepositoryImpl(
        redis_client=SimpleNamespace(async_connection=redis),
        delay_seconds=300,
        lease_seconds=600,
    )


async def test_pending_window_deduplicates_without_extending_first_deadline():
    repository = _repository()

    await repository.enqueue(file_id=11, now_epoch=1000)
    await repository.enqueue(file_id=11, now_epoch=1100)

    assert await repository.claim(now_epoch=1299, lease_owner="worker-a", limit=10) == []
    assert await repository.claim(now_epoch=1300, lease_owner="worker-a", limit=10) == [11]


async def test_event_during_processing_survives_ack_as_next_window():
    repository = _repository()
    await repository.enqueue(file_id=11, now_epoch=1000)
    assert await repository.claim(now_epoch=1300, lease_owner="worker-a", limit=10) == [11]

    await repository.enqueue(file_id=11, now_epoch=1310)
    assert await repository.ack(file_id=11, lease_owner="worker-a") is True

    assert await repository.claim(now_epoch=1609, lease_owner="worker-b", limit=10) == []
    assert await repository.claim(now_epoch=1610, lease_owner="worker-b", limit=10) == [11]


async def test_expired_claim_is_reclaimed_and_wrong_owner_cannot_ack():
    repository = _repository()
    await repository.enqueue(file_id=11, now_epoch=1000)
    assert await repository.claim(now_epoch=1300, lease_owner="worker-a", limit=10) == [11]

    assert await repository.ack(file_id=11, lease_owner="worker-b") is False
    assert await repository.reclaim_expired(now_epoch=1900) == 1
    assert await repository.claim(now_epoch=1900, lease_owner="worker-b", limit=10) == [11]
