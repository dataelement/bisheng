"""F078 T15: temporary sessions for debug windows and single-node tests."""

import pytest

from bisheng.agent_runtime.domain.services.tmp_session import (
    TMP_SESSION_TTL_SECONDS,
    TmpSessionService,
    tmp_deliverable_dir,
)
from test.linsight.fixtures.fake_minio import FakeMinioStorage


class _FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    async def aset(self, key, value, expiration=3600):
        self.values[key] = value
        self.ttls[key] = expiration

    async def aget(self, key):
        return self.values.get(key)

    async def adelete(self, key):
        self.ttls.pop(key, None)
        return 1 if self.values.pop(key, None) is not None else 0

    async def aexists(self, key):
        return key in self.values


@pytest.fixture
def redis():
    return _FakeRedis()


@pytest.fixture
def minio():
    return FakeMinioStorage()


@pytest.fixture
def service(redis, minio):
    return TmpSessionService(redis=redis, minio=minio)


class TestTmpSession:
    async def test_register_then_owner_of(self, service, redis):
        tmp_id = service.new_id()
        await service.aregister(tmp_id, user_id=7, tenant_id=2)
        assert await service.aowner_of(tmp_id) == {"user_id": 7, "tenant_id": 2}
        assert redis.ttls[f"agent_runtime:tmp_session:{tmp_id}"] == TMP_SESSION_TTL_SECONDS

    async def test_unknown_or_expired_session_has_no_owner(self, service, redis):
        tmp_id = service.new_id()
        await service.aregister(tmp_id, user_id=7, tenant_id=2)
        redis.values.clear()  # what expiry looks like
        assert await service.aowner_of(tmp_id) is None
        assert await service.aowner_of("not-registered") is None

    async def test_touch_refreshes_the_ttl(self, service, redis):
        tmp_id = service.new_id()
        await service.aregister(tmp_id, user_id=7, tenant_id=2)
        redis.ttls[f"agent_runtime:tmp_session:{tmp_id}"] = 5
        await service.aregister(tmp_id, user_id=7, tenant_id=2)
        assert redis.ttls[f"agent_runtime:tmp_session:{tmp_id}"] == TMP_SESSION_TTL_SECONDS

    async def test_close_removes_workspace_deliverables_and_registration(self, service, minio):
        tmp_id = service.new_id()
        await service.aregister(tmp_id, user_id=7, tenant_id=2)
        minio.put_object_sync(object_name=f"workspace/agent/tmp-{tmp_id}/wf-n1/output/a.md", file=b"a")
        minio.put_object_sync(
            bucket_name=minio.tmp_bucket, object_name=f"{tmp_deliverable_dir(tmp_id)}/f1.md", file=b"a"
        )
        minio.put_object_sync(object_name="workspace/agent/c1/wf-n1/output/keep.md", file=b"k")

        await service.aclose(tmp_id)

        assert await service.aowner_of(tmp_id) is None
        assert minio.keys(f"workspace/agent/tmp-{tmp_id}/") == []
        assert not [name for (bucket, name) in minio.store if bucket == minio.tmp_bucket]
        assert minio.keys("workspace/agent/c1/") == ["workspace/agent/c1/wf-n1/output/keep.md"]

    async def test_ids_are_path_safe_and_unique(self, service):
        ids = {service.new_id() for _ in range(20)}
        assert len(ids) == 20
        assert all(i.isalnum() for i in ids)


class TestSweep:
    async def test_sweep_removes_only_expired_sessions(self, service, minio):
        live, dead = service.new_id(), service.new_id()
        await service.aregister(live, user_id=7, tenant_id=2)
        for tmp_id in (live, dead):
            minio.put_object_sync(object_name=f"workspace/agent/tmp-{tmp_id}/wf-n1/output/a.md", file=b"a")
        minio.put_object_sync(object_name="workspace/agent/c1/wf-n1/output/a.md", file=b"a")

        assert await service.asweep_expired() == 1

        assert minio.keys(f"workspace/agent/tmp-{dead}/") == []
        assert minio.keys(f"workspace/agent/tmp-{live}/") != []
        assert minio.keys("workspace/agent/c1/") != []
