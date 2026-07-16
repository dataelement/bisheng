from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from bisheng.knowledge.domain.services.portal_recommendation_projection_service import (
    PortalRecommendationProjectionService,
    PortalRecommendationSourceFile,
)


class _SourceRepository:
    def __init__(self, source):
        self.source = source

    async def find_by_id(self, file_id):
        return self.source if self.source and self.source.file_id == file_id else None


class _ProjectionRepository:
    def __init__(self):
        self.upserts = []
        self.deletes = []
        self.current_version = None

    async def upsert(self, value):
        self.upserts.append(value)
        if self.current_version is None or value.projection_version > self.current_version:
            self.current_version = value.projection_version
        else:
            return False
        return True

    async def delete(self, file_id, projection_version):
        self.deletes.append((file_id, projection_version))
        if self.current_version is None or self.current_version > projection_version:
            return False
        self.current_version = None
        return True


def _source(**overrides):
    values = {
        "file_id": 41,
        "space_id": 7,
        "file_type": 1,
        "status": 2,
        "split_rule": '{"business_domain_code": " sc "}',
        "file_encoding": "SG-STD-OLD-20260700000001",
        "file_level_path": "/11/12",
        "source_update_time": datetime(2026, 7, 15, tzinfo=timezone.utc),
        "is_primary": True,
    }
    values.update(overrides)
    return PortalRecommendationSourceFile(**values)


@pytest.mark.asyncio
async def test_projection_reuses_split_rule_domain_and_marks_normal_file_recommendable():
    source = _source()
    projection = _ProjectionRepository()
    service = PortalRecommendationProjectionService(
        source_repository=_SourceRepository(source),
        projection_repository=projection,
        binding_loader=lambda: [],
    )

    changed = await service.refresh_file(41, projection_version=100)

    assert changed is True
    saved = projection.upserts[-1]
    assert saved.business_domain_code == "SC"
    assert saved.permission_scope == "inherited"
    assert saved.recommendable is True
    assert saved.reason_code == "eligible"
    assert saved.projection_version == 100


@pytest.mark.asyncio
async def test_projection_falls_back_to_existing_file_encoding_parser():
    source = _source(split_rule=None, file_encoding="SG-STD-BD2-20260700000001")
    projection = _ProjectionRepository()
    service = PortalRecommendationProjectionService(
        source_repository=_SourceRepository(source),
        projection_repository=projection,
        binding_loader=lambda: [],
    )

    await service.refresh_file(41, projection_version=101)

    assert projection.upserts[-1].business_domain_code == "BD2"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"file_type": 0}, "not_file"),
        ({"status": 3}, "not_success"),
        ({"is_primary": False}, "not_primary"),
    ],
)
async def test_projection_fails_closed_for_ineligible_source(overrides, reason):
    projection = _ProjectionRepository()
    service = PortalRecommendationProjectionService(
        source_repository=_SourceRepository(_source(**overrides)),
        projection_repository=projection,
        binding_loader=lambda: [],
    )

    await service.refresh_file(41, projection_version=102)

    saved = projection.upserts[-1]
    assert saved.recommendable is False
    assert saved.reason_code == reason


@pytest.mark.asyncio
async def test_file_or_ancestor_custom_binding_is_not_shared_pool_eligible():
    bindings = [
        {"resource_type": "folder", "resource_id": "12", "subject_type": "user", "subject_id": 9},
    ]
    projection = _ProjectionRepository()
    service = PortalRecommendationProjectionService(
        source_repository=_SourceRepository(_source()),
        projection_repository=projection,
        binding_loader=lambda: bindings,
    )

    await service.refresh_file(41, projection_version=103)

    saved = projection.upserts[-1]
    assert saved.permission_scope == "custom"
    assert saved.recommendable is False
    assert saved.reason_code == "custom_acl"


@pytest.mark.asyncio
async def test_space_level_custom_binding_excludes_all_owned_files():
    projection = _ProjectionRepository()
    service = PortalRecommendationProjectionService(
        source_repository=_SourceRepository(_source()),
        projection_repository=projection,
        binding_loader=lambda: [
            {"resource_type": "knowledge_space", "resource_id": "7"},
        ],
    )

    await service.refresh_file(41, projection_version=103)

    assert projection.upserts[-1].permission_scope == "custom"
    assert projection.upserts[-1].recommendable is False


@pytest.mark.asyncio
async def test_binding_lookup_error_is_unknown_and_fails_closed():
    async def broken_loader():
        raise RuntimeError("permission config unavailable")

    projection = _ProjectionRepository()
    service = PortalRecommendationProjectionService(
        source_repository=_SourceRepository(_source()),
        projection_repository=projection,
        binding_loader=broken_loader,
    )

    await service.refresh_file(41, projection_version=104)

    saved = projection.upserts[-1]
    assert saved.permission_scope == "unknown"
    assert saved.recommendable is False
    assert saved.reason_code == "acl_unknown"


@pytest.mark.asyncio
async def test_deleted_or_missing_source_removes_projection_idempotently():
    projection = _ProjectionRepository()
    projection.current_version = 100
    service = PortalRecommendationProjectionService(
        source_repository=_SourceRepository(None),
        projection_repository=projection,
        binding_loader=lambda: [],
    )

    assert await service.refresh_file(41, projection_version=105, deleted=True) is True
    assert projection.deletes == [(41, 105)]
    assert projection.upserts == []


@pytest.mark.asyncio
async def test_out_of_order_delete_cannot_remove_a_newer_projection():
    projection = _ProjectionRepository()
    service = PortalRecommendationProjectionService(
        source_repository=_SourceRepository(_source()),
        projection_repository=projection,
        binding_loader=lambda: [],
    )

    assert await service.refresh_file(41, projection_version=200) is True
    assert await service.refresh_file(41, projection_version=199, deleted=True) is False
    assert projection.current_version == 200
    assert await service.refresh_file(41, projection_version=200, deleted=True) is True
    assert await service.refresh_file(41, projection_version=200, deleted=True) is False
    assert projection.current_version is None


def test_live_custom_acl_uses_current_file_lineage_not_projection_snapshot():
    file = SimpleNamespace(id=41, knowledge_id=7, file_level_path="/11/12")
    stale_projection = SimpleNamespace(permission_scope="inherited")
    bindings = [{"resource_type": "knowledge_file", "resource_id": "41"}]

    assert stale_projection.permission_scope == "inherited"
    assert PortalRecommendationProjectionService.has_custom_acl(file, bindings) is True


@pytest.mark.asyncio
async def test_strict_binding_loader_rejects_malformed_permission_config(monkeypatch):
    async def malformed(_key):
        return SimpleNamespace(value="not-json")

    monkeypatch.setattr(
        "bisheng.common.models.config.ConfigDao.aget_config_by_key",
        malformed,
    )

    with pytest.raises(ValueError, match="permission binding config"):
        await PortalRecommendationProjectionService.load_bindings_strict()
