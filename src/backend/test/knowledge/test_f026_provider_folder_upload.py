"""Provider folder-upload prepare: local DIR tree + folder mappings + capabilities."""

from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bisheng.common.errcode.knowledge_space import (
    SpaceFolderDepthError,
    SpaceFolderDuplicateError,
    SpaceFolderNotFoundError,
    SpaceFolderUploadCountExceededError,
)
from bisheng.knowledge.api.endpoints import knowledge_space as api
from bisheng.knowledge.application import provider_folder_upload as folder_upload
from bisheng.knowledge.application import provider_upload_v1 as uploads
from bisheng.knowledge.application.provider_v1_runtime import ProviderFeatureUnavailable
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderMapping as Mapping

ROUTE = NS(
    tenant_id=3,
    space_id=14,
    provider_key="weknora",
    capability_revision=7,
    instance_id=1,
    generation=2,
    remote_scope_id="9",
    remote_kb_id="lib-1",
)


def test_parse_paths_builds_nested_dir_set():
    root, dirs = folder_upload._parse_paths(["docs/a.txt", "docs/sub/b.txt", "docs/sub/deep/c.txt"])
    assert root == "docs"
    assert dirs == {("docs",), ("docs", "sub"), ("docs", "sub", "deep")}


def test_parse_paths_rejects_hidden_and_bare_and_multi_root():
    with pytest.raises(SpaceFolderNotFoundError):
        folder_upload._parse_paths([".hidden/a.txt"])
    with pytest.raises(SpaceFolderNotFoundError):
        folder_upload._parse_paths(["a.txt"])
    with pytest.raises(SpaceFolderNotFoundError):
        folder_upload._parse_paths(["a/x.txt", "b/y.txt"])


def test_parse_paths_rejects_count_overflow():
    with pytest.raises(SpaceFolderUploadCountExceededError):
        folder_upload._parse_paths([f"root/f{i}.txt" for i in range(1001)])


@pytest.fixture
async def mapping_db(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Mapping.__table__.create)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(folder_upload, "get_async_db_session", sessions)
        yield sessions
    finally:
        await engine.dispose()


async def test_prepare_creates_dirs_and_folder_mappings(monkeypatch, mapping_db):
    created = []
    folders = {name: NS(id=100 + i) for i, name in enumerate(["docs", "sub"], start=1)}

    async def acreate_folder(*, knowledge, parent_id, folder_name):
        row = folders[folder_name]
        created.append((parent_id, folder_name, row.id))
        return row

    application = NS(acreate_folder=acreate_folder)
    svc = NS(
        require_upload_container=AsyncMock(return_value=NS(tenant_id=3)),
        upload_application_factory=Mock(return_value=application),
        _get_folder_for_action=AsyncMock(),
        _compensate_upload=AsyncMock(),
    )
    monkeypatch.setattr(folder_upload, "resolve_space_route", AsyncMock(return_value=ROUTE))
    monkeypatch.setattr(folder_upload, "upload_admission", AsyncMock(return_value=object()))
    monkeypatch.setattr(folder_upload, "get_current_tenant_id", lambda: 3)
    monkeypatch.setattr(folder_upload, "_existing_tree", AsyncMock(return_value={}))

    result = await folder_upload.prepare_folder_tree(
        svc,
        14,
        folder_upload.ProviderFolderPrepareRequest(
            parent_id=None,
            paths=["docs/a.txt", "docs/sub/b.txt"],
        ),
    )
    assert result.root_name == "docs"
    assert [(f.relative_dir, f.folder_id) for f in result.folders] == [
        ("docs", 101),
        ("docs/sub", 102),
    ]
    assert created == [(None, "docs", 101), (101, "sub", 102)]

    async with mapping_db() as db:
        rows = (await db.execute(select(Mapping))).scalars().all()
    assert {(r.local_resource_id, r.remote_object_id, r.lifecycle_state) for r in rows} == {
        (101, "lf:2:101", "active"),
        (102, "lf:2:102", "active"),
    }
    assert all(r.resource_type == "folder" and r.ready_revision == 0 for r in rows)


async def test_prepare_rejects_duplicate_root_name(monkeypatch, mapping_db):
    svc = NS(
        require_upload_container=AsyncMock(return_value=NS(tenant_id=3)),
        upload_application_factory=Mock(side_effect=AssertionError("must not create")),
        _compensate_upload=AsyncMock(),
    )
    monkeypatch.setattr(folder_upload, "resolve_space_route", AsyncMock(return_value=ROUTE))
    monkeypatch.setattr(folder_upload, "upload_admission", AsyncMock(return_value=object()))
    monkeypatch.setattr(folder_upload, "get_current_tenant_id", lambda: 3)
    monkeypatch.setattr(folder_upload, "_existing_tree", AsyncMock(return_value=None))
    with pytest.raises(SpaceFolderDuplicateError):
        await folder_upload.prepare_folder_tree(
            svc,
            14,
            folder_upload.ProviderFolderPrepareRequest(paths=["docs/a.txt"]),
        )
    svc.upload_application_factory.assert_not_called()


async def test_prepare_rejects_depth_overflow(monkeypatch, mapping_db):
    parent = NS(id=9, file_level_path="/0", level=8)
    svc = NS(
        require_upload_container=AsyncMock(return_value=NS(tenant_id=3)),
        upload_application_factory=Mock(side_effect=AssertionError("must not create")),
        _get_folder_for_action=AsyncMock(return_value=parent),
        _compensate_upload=AsyncMock(),
    )
    monkeypatch.setattr(folder_upload, "resolve_space_route", AsyncMock(return_value=ROUTE))
    monkeypatch.setattr(folder_upload, "upload_admission", AsyncMock(return_value=object()))
    monkeypatch.setattr(folder_upload, "get_current_tenant_id", lambda: 3)
    monkeypatch.setattr(folder_upload, "_existing_tree", AsyncMock(return_value={}))
    # base_child_level = 9; two more segments → level 10 > MAX_FOLDER_LEVEL(9)
    with pytest.raises(SpaceFolderDepthError):
        await folder_upload.prepare_folder_tree(
            svc,
            14,
            folder_upload.ProviderFolderPrepareRequest(
                parent_id=9,
                paths=["docs/sub/a.txt"],
            ),
        )


async def test_capabilities_folder_upload_tracks_upload(monkeypatch):
    user = NS(tenant_id=3, user_id=17)
    actor = NS(current_tenant_id=3, subject_type="user", subject_id=17)
    svc = NS(
        login_user=user,
        _permission_actor=AsyncMock(return_value=actor),
        _require_action=AsyncMock(),
        require_upload_container=AsyncMock(return_value=NS(tenant_id=3)),
        upload_application_factory=Mock(),
    )
    monkeypatch.setattr(uploads, "get_current_tenant_id", lambda: 3)
    monkeypatch.setattr(uploads, "resolve_space_route", AsyncMock(return_value=ROUTE))
    monkeypatch.setattr(api.provider, "resolve_space_route", AsyncMock(return_value=ROUTE))
    monkeypatch.setattr(uploads, "upload_admission", AsyncMock(return_value=object()))

    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
    app.dependency_overrides[api.get_knowledge_space_service] = lambda: svc
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        caps = (await client.get("/api/v1/knowledge/space/14/capabilities")).json()["data"]["capabilities"]
    assert caps["upload"] == caps["folder_upload"] == "supported"

    monkeypatch.setattr(uploads, "upload_admission", AsyncMock(return_value=None))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        caps = (await client.get("/api/v1/knowledge/space/14/capabilities")).json()["data"]["capabilities"]
    assert caps["upload"] == caps["folder_upload"] == "unverified"


async def test_prepare_http_rejects_native_space(monkeypatch):
    user = NS(tenant_id=3, user_id=17)
    svc = NS(
        login_user=user,
        _permission_actor=AsyncMock(),
        _require_action=AsyncMock(),
    )
    monkeypatch.setattr(folder_upload, "resolve_space_route", AsyncMock(return_value=None))
    app = FastAPI()
    app.include_router(api.router, prefix="/api/v1")
    app.dependency_overrides[api.get_knowledge_space_service] = lambda: svc
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        with pytest.raises(ProviderFeatureUnavailable):
            await client.post(
                "/api/v1/knowledge/space/14/provider-folder-uploads/prepare",
                json={"paths": ["docs/a.txt"]},
            )


async def test_prepare_reuses_leftover_dir_tree(monkeypatch, mapping_db):
    """A retry after a partial failure must not be blocked by its own empty tree."""
    created = []

    async def acreate_folder(*, knowledge, parent_id, folder_name):
        created.append((parent_id, folder_name))
        return NS(id=200)

    svc = NS(
        require_upload_container=AsyncMock(return_value=NS(tenant_id=3)),
        upload_application_factory=Mock(return_value=NS(acreate_folder=acreate_folder)),
        _compensate_upload=AsyncMock(),
    )
    monkeypatch.setattr(folder_upload, "resolve_space_route", AsyncMock(return_value=ROUTE))
    monkeypatch.setattr(folder_upload, "upload_admission", AsyncMock(return_value=object()))
    monkeypatch.setattr(folder_upload, "get_current_tenant_id", lambda: 3)
    monkeypatch.setattr(folder_upload, "_existing_tree", AsyncMock(return_value={("docs",): 101}))

    result = await folder_upload.prepare_folder_tree(
        svc,
        14,
        folder_upload.ProviderFolderPrepareRequest(paths=["docs/a.txt", "docs/sub/b.txt"]),
    )
    assert [(f.relative_dir, f.folder_id) for f in result.folders] == [
        ("docs", 101),
        ("docs/sub", 200),
    ]
    # Only the missing level is created; the leftover root is reused as-is.
    assert created == [(101, "sub")]


@pytest.fixture
async def file_db(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(KnowledgeFile.__table__.create)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(folder_upload, "get_async_db_session", sessions)
        yield sessions
    finally:
        await engine.dispose()


async def _add_folder(sessions, *, ident, name, path, level=0, file_type=0):
    async with sessions() as db, db.begin():
        db.add(
            KnowledgeFile(
                id=ident,
                knowledge_id=10,
                tenant_id=1,
                file_name=name,
                file_type=file_type,
                file_level_path=path,
                level=level,
                status=2,
            )
        )


async def test_existing_tree_maps_only_directories(file_db):
    await _add_folder(file_db, ident=47, name="docs", path="")
    await _add_folder(file_db, ident=48, name="sub", path="/47", level=1)
    assert await folder_upload._existing_tree(10, "docs", "") == {
        ("docs",): 47,
        ("docs", "sub"): 48,
    }


async def test_existing_tree_blocks_a_real_folder(file_db):
    await _add_folder(file_db, ident=47, name="docs", path="")
    await _add_folder(file_db, ident=49, name="a.txt", path="/47", level=1, file_type=1)
    assert await folder_upload._existing_tree(10, "docs", "") is None


async def test_existing_tree_blocks_a_same_named_file(file_db):
    await _add_folder(file_db, ident=50, name="docs", path="", file_type=1)
    assert await folder_upload._existing_tree(10, "docs", "") is None


async def test_existing_tree_ignores_other_drop_points(file_db):
    await _add_folder(file_db, ident=60, name="docs", path="/55", level=1)
    assert await folder_upload._existing_tree(10, "docs", "") == {}
