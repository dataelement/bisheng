"""v2 ``GET /api/v2/filelib/file/list`` — knowledge-base (type 0/1) cursor paging.

Regression: the pseudo-cursor stored a page number but fetched
``page_size + 1`` rows per page and computed ``OFFSET (page - 1) * (page_size + 1)``,
so the probe row of each page was never returned (one file lost at every page
boundary). The query also had no ORDER BY, so the row order was not defined.

These tests walk every page against a real (SQLite) ``knowledgefile`` table and
check that the union of all pages equals the full set, without duplicates, also
when many files share the same ``update_time``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.pool import StaticPool

import bisheng.knowledge.domain.models.knowledge_file as kf_module
from bisheng.common.cursor import encode_cursor
from bisheng.common.errcode.knowledge import KnowledgeInvalidCursorError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.services import knowledge_service as ks_module
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService

KNOWLEDGE_ID = 7
OTHER_KNOWLEDGE_ID = 8
# Every seeded file shares one timestamp: the tie group must not break paging.
SAME_TIME = datetime(2026, 10, 9, 10, 0, 0)


class _Perm:
    async def ensure_knowledge_read_async(self, **_kwargs):
        return None

    async def check_action_async(self, **_kwargs):
        return True


@pytest.fixture
async def seeded(monkeypatch):
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(KnowledgeFile.__table__.create)

    @asynccontextmanager
    async def _session():
        session = AsyncSession(bind=engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    monkeypatch.setattr(kf_module, "get_async_db_session", _session)

    async def _seed(count: int, knowledge_id: int = KNOWLEDGE_ID, status: int = 2) -> list[int]:
        ids = []
        with bypass_tenant_filter():
            async with _session() as session:
                for i in range(count):
                    row = KnowledgeFile(
                        knowledge_id=knowledge_id,
                        file_name=f"doc-{knowledge_id}-{i:03d}.txt",
                        status=status,
                        user_id=1,
                    )
                    row.create_time = SAME_TIME
                    row.update_time = SAME_TIME
                    session.add(row)
                    await session.commit()
                    await session.refresh(row)
                    ids.append(row.id)
        return ids

    async def _query_by_id(_knowledge_id):
        return SimpleNamespace(id=_knowledge_id, user_id=1)

    async def _decorate(_db_knowledge, rows):
        return list(rows)

    monkeypatch.setattr(ks_module.KnowledgeDao, "aquery_by_id", _query_by_id)
    monkeypatch.setattr(KnowledgeService, "permission_service", _Perm())
    monkeypatch.setattr(KnowledgeService, "_adecorate_knowledge_files", classmethod(lambda cls, k, r: _decorate(k, r)))

    yield _seed
    await engine.dispose()


async def _walk(page_size: int, **filters) -> tuple[list[int], int]:
    ids: list[int] = []
    pages = 0
    cursor = None
    with bypass_tenant_filter():
        while True:
            page, writeable = await KnowledgeService.aget_knowledge_files_cursor(
                None, SimpleNamespace(user_id=1), KNOWLEDGE_ID, page_size=page_size, cursor=cursor, **filters
            )
            assert writeable is True
            pages += 1
            ids += [one.id for one in page.data]
            if not page.has_more:
                assert page.next_cursor is None
                break
            assert len(page.data) == page_size
            cursor = page.next_cursor
            assert pages < 100, "paging did not terminate"
    return ids, pages


@pytest.mark.parametrize("total,page_size", [(25, 10), (20, 10), (7, 3), (5, 1), (3, 10)])
async def test_walk_returns_every_file_once(seeded, total, page_size):
    expected = await seeded(total)
    await seeded(4, knowledge_id=OTHER_KNOWLEDGE_ID)  # must never leak in

    ids, pages = await _walk(page_size)

    assert len(ids) == len(set(ids)), "a file appeared on two pages"
    assert set(ids) == set(expected), "a file was skipped"
    assert pages == max(1, -(-total // page_size))


async def test_order_is_id_desc_and_stable(seeded):
    expected = await seeded(12)

    first, _ = await _walk(5)
    second, _ = await _walk(5)

    assert first == sorted(expected, reverse=True)
    assert first == second


async def test_status_filter_pages_cover_filtered_set(seeded):
    parsed = await seeded(9, status=2)
    await seeded(6, status=3)

    ids, _ = await _walk(4, status=[2])

    assert sorted(ids) == sorted(parsed)


async def test_empty_knowledge_base(seeded):
    ids, pages = await _walk(10)
    assert ids == [] and pages == 1


@pytest.mark.parametrize(
    "cursor",
    [
        # Page-number cursor issued before the fix: context changed, so reject it.
        encode_cursor((2,), context="filelib_file|kb"),
        encode_cursor(("x",), context="filelib_file|kb|id_desc"),
        encode_cursor((0,), context="filelib_file|kb|id_desc"),
        encode_cursor((True,), context="filelib_file|kb|id_desc"),
        "not-a-cursor",
    ],
)
async def test_invalid_cursor_rejected(seeded, cursor):
    with pytest.raises(KnowledgeInvalidCursorError):
        await KnowledgeService.aget_knowledge_files_cursor(
            None, SimpleNamespace(user_id=1), KNOWLEDGE_ID, page_size=10, cursor=cursor
        )


@pytest.mark.parametrize("page_size", ["0", "-1"])
async def test_non_positive_page_size_is_http_400(monkeypatch, page_size):
    """``page_size < 1`` used to reach ``res[-1]`` on an empty slice (HTTP 500)."""
    from unittest.mock import AsyncMock

    from fastapi import Depends, FastAPI
    from httpx import ASGITransport, AsyncClient

    from bisheng.open_api.api import dependencies
    from bisheng.open_api.api.exception_handlers import register_open_api_exception_handlers
    from bisheng.open_endpoints.api.endpoints import filelib
    from test.open_api.test_dependencies import service_account_principal

    app = FastAPI()
    register_open_api_exception_handlers(app)
    app.include_router(filelib.router, prefix="/api/v2", dependencies=[Depends(dependencies.verify_open_api_access)])
    for dep in (
        filelib.get_knowledge_document_version_repository,
        filelib.get_knowledge_document_repository,
        filelib.get_knowledge_file_repository,
    ):
        app.dependency_overrides[dep] = lambda: None
    monkeypatch.setattr(
        dependencies,
        "validate_bearer",
        AsyncMock(return_value=service_account_principal(scopes=frozenset({"knowledge:read"}))),
    )
    listing = AsyncMock()
    monkeypatch.setattr(filelib.KnowledgeService, "aget_knowledge_files_cursor", listing)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v2/filelib/file/list",
            params={"knowledge_id": KNOWLEDGE_ID, "page_size": page_size},
            headers={"Authorization": "Bearer fixture"},
        )

    assert (response.status_code, response.json()["status_code"]) == (400, 400)
    listing.assert_not_awaited()
