"""Tests for the similarity-candidate historical backfill script."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import scripts.backfill_file_similarity_candidates as script_mod
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from scripts.backfill_file_similarity_candidates import backfill


async def _seed_space(session, knowledge_id: int, knowledge_type: int = 3) -> None:
    session.add(Knowledge(id=knowledge_id, name=f"space{knowledge_id}", type=knowledge_type, user_id=1))
    await session.commit()


async def _seed_file(
    session,
    *,
    file_id: int,
    knowledge_id: int = 1,
    status: int = 2,
    file_type: int = 1,
    similar_status: int = 0,
    simhash: str | None = "aaaaaaaaaaaaaaaa",
    file_encoding: str | None = "GF-ZD-SC-20260500000001",
) -> None:
    session.add(
        KnowledgeFile(
            id=file_id,
            knowledge_id=knowledge_id,
            file_name=f"f{file_id}.pdf",
            file_type=file_type,
            status=status,
            similar_status=similar_status,
            simhash=simhash,
            file_encoding=file_encoding,
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_backfill_dry_run_counts_without_refresh(async_db_session, monkeypatch):
    await _seed_space(async_db_session, 1)
    await _seed_file(async_db_session, file_id=100)
    refresh = AsyncMock(return_value=1)
    monkeypatch.setattr(
        script_mod, "_build_service", lambda session: SimpleNamespace(refresh_similar_candidates_for_file=refresh)
    )

    report = await backfill(async_db_session, apply=False)

    assert report.would_refresh == 1
    assert report.refreshed_files == 0
    refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_backfill_apply_refreshes_eligible_files(async_db_session, monkeypatch):
    await _seed_space(async_db_session, 1)
    await _seed_file(async_db_session, file_id=100)
    refresh = AsyncMock(return_value=2)
    monkeypatch.setattr(
        script_mod, "_build_service", lambda session: SimpleNamespace(refresh_similar_candidates_for_file=refresh)
    )

    report = await backfill(async_db_session, apply=True)

    assert report.refreshed_files == 1
    assert report.candidates_written == 2
    refresh.assert_awaited_once_with(100)


@pytest.mark.asyncio
async def test_backfill_skips_resolved_and_invalid_encoding(async_db_session, monkeypatch):
    await _seed_space(async_db_session, 1)
    await _seed_file(async_db_session, file_id=100, similar_status=2)
    await _seed_file(async_db_session, file_id=101, file_encoding="BAD")
    await _seed_file(async_db_session, file_id=102)
    refresh = AsyncMock(return_value=0)
    monkeypatch.setattr(
        script_mod, "_build_service", lambda session: SimpleNamespace(refresh_similar_candidates_for_file=refresh)
    )

    report = await backfill(async_db_session, apply=True)

    assert report.total_files_scanned == 2
    assert report.skipped_invalid_encoding == 1
    assert report.refreshed_files == 1
    assert report.no_candidates == 1
    refresh.assert_awaited_once_with(102)


@pytest.mark.asyncio
async def test_backfill_respects_knowledge_id_filter(async_db_session, monkeypatch):
    await _seed_space(async_db_session, 1)
    await _seed_space(async_db_session, 2)
    await _seed_file(async_db_session, file_id=100, knowledge_id=1)
    await _seed_file(async_db_session, file_id=200, knowledge_id=2)
    refresh = AsyncMock(return_value=1)
    monkeypatch.setattr(
        script_mod, "_build_service", lambda session: SimpleNamespace(refresh_similar_candidates_for_file=refresh)
    )

    report = await backfill(async_db_session, apply=True, knowledge_id=2)

    assert report.refreshed_files == 1
    refresh.assert_awaited_once_with(200)
