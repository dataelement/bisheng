from bisheng.knowledge.domain.schemas.portal_hot_search_schema import PortalHotSearchItem
from bisheng.knowledge.domain.services.portal_hot_search_read_service import (
    PortalHotSearchReadService,
)


class _FakeRedisRepo:
    def __init__(self, cached=None, *, fail=False):
        self._cached = cached
        self._fail = fail
        self.replaced = None

    async def get(self, tenant_id):
        if self._fail:
            raise RuntimeError("redis down")
        return self._cached

    async def replace(self, tenant_id, items):
        self.replaced = list(items)

    async def acquire_lock(self, tenant_id):
        return True

    async def release_lock(self, tenant_id):
        pass


class _FakeSnapshotRepo:
    def __init__(self, items):
        self._items = items
        self.calls = 0

    async def list_home_snapshot(self, *, top_k):
        self.calls += 1
        return self._items[:top_k]

    # unused abstract-ish members for this read test
    async def insert_batch_run(self, *a, **k): ...
    async def update_batch_run(self, *a, **k): ...
    async def replace_snapshot(self, *a, **k): ...
    async def insert_candidates(self, *a, **k): ...
    async def purge_old_diagnostics(self, *a, **k): ...


async def test_read_returns_cache_without_db_when_hit():
    cached = [PortalHotSearchItem(rank=1, query="设备检修安全要求？")]
    redis = _FakeRedisRepo(cached=cached)
    snapshot = _FakeSnapshotRepo([PortalHotSearchItem(rank=1, query="不应被读取？")])
    svc = PortalHotSearchReadService(redis_repository=redis, snapshot_repository=snapshot, top_k=5)

    result = await svc.list_for_home(1)
    assert [i.query for i in result] == ["设备检修安全要求？"]
    assert snapshot.calls == 0  # cache hit -> no DB read


async def test_read_falls_back_to_db_and_backfills_cache():
    redis = _FakeRedisRepo(cached=None)
    snapshot = _FakeSnapshotRepo([PortalHotSearchItem(rank=1, query="能源管理制度？")])
    svc = PortalHotSearchReadService(redis_repository=redis, snapshot_repository=snapshot, top_k=5)

    result = await svc.list_for_home(1)
    assert [i.query for i in result] == ["能源管理制度？"]
    assert snapshot.calls == 1
    assert redis.replaced is not None  # backfilled


async def test_read_returns_empty_when_no_data():
    redis = _FakeRedisRepo(cached=None)
    snapshot = _FakeSnapshotRepo([])
    svc = PortalHotSearchReadService(redis_repository=redis, snapshot_repository=snapshot, top_k=5)
    assert await svc.list_for_home(1) == []


async def test_read_survives_redis_failure():
    redis = _FakeRedisRepo(fail=True)
    snapshot = _FakeSnapshotRepo([PortalHotSearchItem(rank=1, query="环保设施运行要求？")])
    svc = PortalHotSearchReadService(redis_repository=redis, snapshot_repository=snapshot, top_k=5)
    result = await svc.list_for_home(1)
    assert [i.query for i in result] == ["环保设施运行要求？"]


# --------------------------------------------------------------------------
# T028 home endpoint / service wrapper
# --------------------------------------------------------------------------


def _bare_service():
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

    return KnowledgeSpaceService.__new__(KnowledgeSpaceService)


async def test_home_merges_hot_searches_and_serializes(monkeypatch):
    from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
        ShougangPortalHomeReq,
        ShougangPortalHomeResp,
    )

    svc = _bare_service()

    async def _sections(req):
        return {"sections": {"最新精选": []}, "tags": ["热轧"]}

    async def _hot():
        return [PortalHotSearchItem(rank=1, query="设备检修安全要求？")]

    monkeypatch.setattr(svc, "_get_shougang_portal_home_sections", _sections)
    monkeypatch.setattr(svc, "_list_shougang_portal_hot_searches", _hot)

    result = await svc.get_shougang_portal_home(ShougangPortalHomeReq(sections=[{"tag": "最新精选"}]))
    assert result["tags"] == ["热轧"]  # existing fields untouched
    resp = ShougangPortalHomeResp(**result)
    assert [i.query for i in resp.hot_searches] == ["设备检修安全要求？"]


async def test_home_empty_hot_searches_serializes(monkeypatch):
    from bisheng.knowledge.domain.schemas.knowledge_space_schema import (
        ShougangPortalHomeReq,
        ShougangPortalHomeResp,
    )

    svc = _bare_service()

    async def _sections(req):
        return {"sections": {}, "tags": []}

    async def _hot():
        return []

    monkeypatch.setattr(svc, "_get_shougang_portal_home_sections", _sections)
    monkeypatch.setattr(svc, "_list_shougang_portal_hot_searches", _hot)

    result = await svc.get_shougang_portal_home(ShougangPortalHomeReq(sections=[]))
    resp = ShougangPortalHomeResp(**result)
    assert resp.hot_searches == []


async def test_list_hot_searches_returns_empty_when_disabled(monkeypatch):
    from bisheng.common.services import config_service

    monkeypatch.setattr(config_service.settings.portal_hot_search, "enabled", False)
    svc = _bare_service()
    assert await svc._list_shougang_portal_hot_searches() == []
