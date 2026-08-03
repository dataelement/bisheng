from __future__ import annotations

from collections import defaultdict


class _FakeRedisConnection:
    def __init__(self, stat_cls):
        self.stat_cls = stat_cls
        self.zsets: dict[str, dict[str, float]] = defaultdict(dict)
        self.hashes: dict[str, dict[str, str]] = defaultdict(dict)
        self.values: dict[str, str] = {}

    @staticmethod
    def _text(value):
        return value.decode() if isinstance(value, bytes) else str(value)

    def set(self, key, value, *, nx=False, ex=None):
        del ex
        if nx and key in self.values:
            return False
        self.values[key] = str(value)
        return True

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        existed = key in self.values
        self.values.pop(key, None)
        self.zsets.pop(key, None)
        self.hashes.pop(key, None)
        return int(existed)

    def zadd(self, key, mapping, nx=False):
        added = 0
        for member, score in mapping.items():
            if nx and member in self.zsets[key]:
                continue
            added += int(member not in self.zsets[key])
            self.zsets[key][str(member)] = float(score)
        return added

    def zcard(self, key):
        return len(self.zsets[key])

    def zrange(self, key, start, end, withscores=False):
        rows = sorted(self.zsets[key].items(), key=lambda item: (item[1], item[0]))
        if end >= 0:
            rows = rows[start : end + 1]
        else:
            rows = rows[start:]
        if withscores:
            return rows
        return [member for member, _ in rows]

    def eval(self, script, numkeys, *args):
        keys = args[:numkeys]
        values = args[numkeys:]
        stat_cls = self.stat_cls
        if script == stat_cls.RENEW_LOCK_SCRIPT:
            key = keys[0]
            return int(self.values.get(key) == str(values[0]))
        if script == stat_cls.RELEASE_LOCK_SCRIPT:
            key = keys[0]
            if self.values.get(key) != str(values[0]):
                return 0
            self.values.pop(key, None)
            return 1
        if script == stat_cls.CLAIM_SCRIPT:
            pending_key, processing_key, meta_key, lock_key = keys
            owner_token, _claimed_at, lease_deadline, batch_size = values
            if self.values.get(lock_key) != str(owner_token):
                return []
            rows = sorted(
                self.zsets[pending_key].items(),
                key=lambda item: (item[1], item[0]),
            )[: int(batch_size)]
            result = []
            for member, enqueued_at in rows:
                self.zsets[pending_key].pop(member)
                self.zsets[processing_key][member] = float(lease_deadline)
                self.hashes[meta_key][member] = str(enqueued_at)
                result.extend([member.encode(), str(enqueued_at).encode()])
            return result
        if script == stat_cls.RENEW_CLAIMS_SCRIPT:
            processing_key, lock_key = keys
            owner_token, deadline, *members = values
            if self.values.get(lock_key) != str(owner_token):
                return 0
            renewed = 0
            for member in members:
                member = self._text(member)
                if member in self.zsets[processing_key]:
                    self.zsets[processing_key][member] = float(deadline)
                    renewed += 1
            return renewed
        if script == stat_cls.ACK_SCRIPT:
            processing_key, meta_key, lock_key = keys
            owner_token, *members = values
            if self.values.get(lock_key) != str(owner_token):
                return 0
            removed = 0
            for member in members:
                member = self._text(member)
                removed += int(member in self.zsets[processing_key])
                self.zsets[processing_key].pop(member, None)
                self.hashes[meta_key].pop(member, None)
            return removed
        if script == stat_cls.RECLAIM_SCRIPT:
            pending_key, processing_key, meta_key = keys
            now_ms = float(values[0])
            expired = [member for member, deadline in self.zsets[processing_key].items() if deadline <= now_ms]
            for member in expired:
                enqueued_at = float(self.hashes[meta_key].get(member, now_ms))
                self.zsets[pending_key].setdefault(member, enqueued_at)
                self.zsets[processing_key].pop(member, None)
                self.hashes[meta_key].pop(member, None)
            return len(expired)
        raise AssertionError("unexpected script")


class _FakeRedisClient:
    def __init__(self, stat_cls):
        self.connection = _FakeRedisConnection(stat_cls)

    def cluster_nodes(self, _key):
        return None

    def setNx(self, key, value, expiration=3600):
        return self.connection.set(key, value, nx=True, ex=expiration)

    def delete(self, key):
        return self.connection.delete(key)


def _install_fake(monkeypatch):
    from bisheng.telemetry.domain.mid_table import knowledge_space_content as module

    fake = _FakeRedisClient(module.KnowledgeSpaceContentStat)
    monkeypatch.setattr(module, "get_redis_client_sync", lambda: fake)
    monkeypatch.setattr(
        module.KnowledgeSpaceContentStat,
        "_schedule_pending_sync",
        lambda *_args, **_kwargs: None,
    )
    return module.KnowledgeSpaceContentStat, fake


def test_claim_reenqueue_and_ack_preserves_new_pending_signal(monkeypatch):
    stat_cls, fake = _install_fake(monkeypatch)
    stat_cls._zadd_pending_sync(fake, ["file:11"], now_ms=1_000)
    owner = stat_cls.acquire_lock_sync("owner-a")

    claimed = stat_cls.claim_pending_sync(owner, now_ms=1_100)
    stat_cls._zadd_pending_sync(fake, ["file:11"], now_ms=1_200)
    assert stat_cls.ack_claimed_sync(owner, ["file:11"])

    assert [(item.member, item.enqueued_at_ms) for item in claimed] == [("file:11", 1_000)]
    assert fake.connection.zsets[stat_cls.PENDING_KEY] == {"file:11": 1_200.0}
    assert fake.connection.zsets[stat_cls.PROCESSING_KEY] == {}


def test_processing_lease_renewal_and_recovery_use_controllable_time(monkeypatch):
    stat_cls, fake = _install_fake(monkeypatch)
    stat_cls._zadd_pending_sync(fake, ["file:12"], now_ms=2_000)
    owner = stat_cls.acquire_lock_sync("owner-a")
    stat_cls.claim_pending_sync(owner, now_ms=3_000)

    assert stat_cls.renew_claims_sync(owner, ["file:12"], now_ms=100_000)
    assert stat_cls.reclaim_expired_sync(now_ms=339_999) == 0
    assert stat_cls.reclaim_expired_sync(now_ms=340_000) == 1
    assert fake.connection.zsets[stat_cls.PENDING_KEY] == {"file:12": 2_000.0}


def test_owner_lock_rejects_non_owner_renew_and_release(monkeypatch):
    stat_cls, fake = _install_fake(monkeypatch)
    owner = stat_cls.acquire_lock_sync("owner-a")

    assert owner == "owner-a"
    assert stat_cls.acquire_lock_sync("owner-b") is None
    assert stat_cls.renew_lock_sync("owner-b") is False
    assert stat_cls.release_lock_sync("owner-b") is False
    assert fake.connection.values[stat_cls.LOCK_KEY] == "owner-a"
    assert stat_cls.renew_lock_sync("owner-a") is True
    assert stat_cls.release_lock_sync("owner-a") is True


def test_projection_redis_keys_share_cluster_hash_tag():
    from bisheng.telemetry.domain.mid_table.knowledge_space_content import (
        KnowledgeSpaceContentStat,
    )

    keys = {
        KnowledgeSpaceContentStat.PENDING_KEY,
        KnowledgeSpaceContentStat.PROCESSING_KEY,
        KnowledgeSpaceContentStat.PROCESSING_META_KEY,
        KnowledgeSpaceContentStat.SCHEDULED_KEY,
        KnowledgeSpaceContentStat.LOCK_KEY,
    }
    assert all("{knowledge_space_content}" in key for key in keys)
    assert not hasattr(KnowledgeSpaceContentStat, "PREVIEW_PENDING_KEY")
