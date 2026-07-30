"""F018 owner-transfer and legacy permission mutation retirement."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from bisheng.permission.api.router import router as permission_router
from bisheng.permission.domain.services.grant_source_service import (
    GrantModelSnapshot,
    GrantSnapshot,
    GrantSourceService,
)
from bisheng.tenant.api.router import router as tenant_router

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_transfer_owner_and_legacy_permission_mutations_are_unreachable() -> None:
    app = FastAPI()
    app.include_router(permission_router, prefix="/api/v1")
    app.include_router(tenant_router, prefix="/api/v1")
    paths = {route.path for route in app.routes}

    assert "/api/v1/tenants/{tenant_id}/resources/transfer-owner" not in paths
    assert "/api/v1/tenants/{tenant_id}/resources/pending-transfer" not in paths
    assert "/api/v1/permissions/relation-models" not in paths
    assert ("/api/v1/permissions/resources/{resource_type}/{resource_id}/authorize") not in paths
    assert ("/api/v1/permissions/resources/{resource_type}/{resource_id}/grants:mutate") in paths


def test_f018_runtime_modules_are_removed_from_the_startup_build() -> None:
    assert not (BACKEND_ROOT / "bisheng/tenant/api/endpoints/resource_owner_transfer.py").exists()
    assert not (BACKEND_ROOT / "bisheng/tenant/domain/services/resource_ownership_service.py").exists()


def test_multiple_ordinary_owners_do_not_replace_protected_creator() -> None:
    sources = GrantSourceService()
    model = GrantModelSnapshot(
        model_key="owner",
        active=True,
        action_codes=("manage_permission", "delete"),
        derived_level=4,
        allow_same_level=True,
    )
    grant = GrantSnapshot(
        grant_id="owner-grant",
        tenant_id=5,
        resource_type="workflow",
        resource_id="wf-1",
        model=model,
        active=False,
        sources=(),
    )
    creator = sources.canonicalize_source(
        source_id=1,
        subject_type="user",
        subject_id="7",
        source_type="CREATOR",
        source_ref="workflow:wf-1",
        protected=True,
    )
    owner_a = sources.canonicalize_source(
        source_id=2,
        subject_type="user",
        subject_id="8",
        source_type="DIRECT",
    )
    owner_b = sources.canonicalize_source(
        source_id=3,
        subject_type="user",
        subject_id="9",
        source_type="DIRECT",
    )

    grant = sources.add_source(grant, creator).grant
    grant = sources.add_source(grant, owner_a).grant
    grant = sources.add_source(grant, owner_b).grant
    grant = sources.remove_source(grant, source_id=2).grant

    assert tuple(source.source_id for source in grant.sources) == (1, 3)
    assert grant.sources[0].protected is True
    assert grant.sources[1].protected is False
