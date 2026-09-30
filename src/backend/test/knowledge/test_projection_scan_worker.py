"""扫描预算、续扫、互斥和发布失败恢复的编排回归。"""

import asyncio
import importlib
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from test.knowledge.projection_scan_helpers import scan_state as _scan_state_fixture
from test.knowledge.test_knowledge_document_permission_reconcile_worker import _entry, projection_worker

scan_state = _scan_state_fixture


@pytest.fixture
def scan_env(async_db_session, monkeypatch, scan_state):
    scanner = importlib.import_module("bisheng.worker.knowledge._projection_scan")

    @asynccontextmanager
    async def db():
        yield async_db_session

    conf = SimpleNamespace(
        projection_max_retries=4, projection_scan_max_pages=3, projection_scan_time_budget_seconds=45
    )
    monkeypatch.setattr(scanner, "get_shared_storage_conf", lambda: conf)
    monkeypatch.setattr(projection_worker, "get_async_db_session", db)
    publish = MagicMock()
    monkeypatch.setattr(projection_worker.process_document_projection, "apply_async", publish)
    return scanner, conf, publish


async def test_budget_cursor_covers_tail_and_queued_entries_are_not_redispatched(
    async_db_session,
    scan_env,
    scan_state,
):
    scanner, conf, publish = scan_env
    for entry_id in range(1, 206):
        async_db_session.add(_entry(entry_id, approval_instance_id=None, status="active"))
    await async_db_session.commit()

    assert await scanner.scan_tenant(7) == 100
    assert (await scan_state.cursor())["projection"] == 100
    assert await scanner.scan_tenant(7) == 100
    assert (await scan_state.cursor())["projection"] == 200
    assert await scanner.scan_tenant(7) == 5
    assert (await scan_state.cursor())["projection"] == 0
    assert [entry_id for call in publish.call_args_list for entry_id in call.kwargs["kwargs"]["entry_ids"]] == list(
        range(1, 206)
    )
    conf.projection_scan_max_pages = 15
    assert await scanner.scan_tenant(7) == 0
    assert publish.call_count == 3


async def test_overlapping_scan_skips_database(scan_env, scan_state):
    scanner, _, publish = scan_env
    scan_state.redis.locks.add(scan_state.key("lock", "tenant"))
    assert await scanner.scan_tenant(7) == 0
    publish.assert_not_called()


async def test_multiple_scan_pages_publish_one_complete_batch(async_db_session, scan_env, scan_state):
    scanner, conf, publish = scan_env
    conf.projection_scan_max_pages = 15
    for entry_id in range(1, 301):
        async_db_session.add(_entry(entry_id, approval_instance_id=None, status="active"))
    await async_db_session.commit()
    assert await scanner.scan_tenant(7) == 300
    publish.assert_called_once()
    assert publish.call_args.kwargs["kwargs"]["entry_ids"] == list(range(1, 301))
    assert len(publish.call_args.kwargs["kwargs"]["scan_tickets"]) == 300
    assert (await scan_state.cursor())["projection"] == 0


async def test_publish_failure_keeps_ticket_and_stale_message_is_rejected(async_db_session, scan_env, scan_state):
    scanner, _, publish = scan_env
    async_db_session.add(_entry(91, approval_instance_id=None, status="active"))
    await async_db_session.commit()
    publish.side_effect = RuntimeError("broker unavailable after send")
    with pytest.raises(RuntimeError, match="broker unavailable"):
        await scanner.scan_tenant(7)
    old = publish.call_args.kwargs["kwargs"]["scan_tickets"][0]
    assert not scan_state.redis.locks
    publish.side_effect = None
    assert await scanner.scan_tenant(7) == 0
    scan_state.clock[0] += 1801
    assert await scanner.scan_tenant(7) == 1
    assert not await scan_state.start(old)


async def test_time_budget_releases_lock_without_advancing_unfinished_page(scan_env, scan_state, monkeypatch):
    scanner, conf, publish = scan_env
    conf.projection_scan_time_budget_seconds = 1

    async def slow_query(**kwargs):
        await asyncio.sleep(10)

    monkeypatch.setattr(
        projection_worker.KnowledgeFileRepositoryImpl,
        "find_projection_candidates",
        lambda self, **kwargs: slow_query(**kwargs),
    )
    assert await scanner.scan_tenant(7) == 0
    assert not scan_state.redis.locks
    assert (await scan_state.cursor()).get("projection", 0) == 0
    publish.assert_not_called()


async def test_partial_scan_flushes_collected_batch_before_committing_cursor(
    async_db_session, scan_env, scan_state, monkeypatch
):
    scanner, conf, publish = scan_env
    conf.projection_scan_time_budget_seconds = 1
    conf.projection_scan_max_pages = 15
    for entry_id in range(1, 151):
        async_db_session.add(_entry(entry_id, approval_instance_id=None, status="active"))
    await async_db_session.commit()
    original = projection_worker.KnowledgeFileRepositoryImpl.find_permission_reconcile_candidates

    async def slow(self, **kwargs):
        assert (await scan_state.cursor())["projection"] == 0
        await asyncio.sleep(10)

    monkeypatch.setattr(projection_worker.KnowledgeFileRepositoryImpl, "find_permission_reconcile_candidates", slow)
    assert await scanner.scan_tenant(7) == 100
    publish.assert_called_once()
    assert (await scan_state.cursor())["projection"] == 100
    monkeypatch.setattr(projection_worker.KnowledgeFileRepositoryImpl, "find_permission_reconcile_candidates", original)
    assert await scanner.scan_tenant(7) == 50
    assert publish.call_count == 2
    assert publish.call_args.kwargs["kwargs"]["entry_ids"] == list(range(101, 151))


async def test_small_budget_rotates_branches_so_retirement_is_not_starved(scan_env, scan_state, monkeypatch):
    scanner, conf, _ = scan_env
    conf.projection_scan_max_pages = 1
    retirement = AsyncMock(return_value=[])
    monkeypatch.setattr(scanner.KnowledgeRepositoryImpl, "find_retiring_spaces", retirement)
    for _ in range(3):
        await scanner.scan_tenant(7)
    retirement.assert_awaited_once()
    assert (await scan_state.cursor())["branch"] == 0


async def test_failed_cleanup_rows_do_not_reset_retirement_budget(async_db_session, scan_env, monkeypatch):
    from bisheng.knowledge.domain.models.knowledge import Knowledge

    async_db_session.add(Knowledge(id=20, name="retiring", tenant_id=7, state=5))
    async_db_session.add(_entry(91, approval_instance_id=None, status="active"))
    await async_db_session.commit()
    monkeypatch.setattr(
        projection_worker, "_sweep_container_distribution_entries", AsyncMock(return_value=("stalled", 50))
    )
    progress = {}
    assert (
        await projection_worker._process_knowledge_space_retirement_async(
            tenant_id=7,
            space_id=20,
            scan_progress=progress,
        )
        == "waiting"
    )
    assert "moved" not in progress
    assert progress["fingerprint"]


async def test_retirement_cursor_visits_spaces_after_first_page(async_db_session, scan_env, scan_state, monkeypatch):
    from bisheng.knowledge.domain.models.knowledge import Knowledge

    scanner, _, _ = scan_env
    for space_id in range(1, 103):
        async_db_session.add(Knowledge(id=space_id, name=f"retiring-{space_id}", tenant_id=7, state=5))
    await async_db_session.commit()
    publish = MagicMock()
    monkeypatch.setattr(projection_worker.recover_document_projection_scan_item, "apply_async", publish)
    await scanner.scan_tenant(7)
    assert publish.call_count == 100
    assert (await scan_state.cursor())["retirement"] == 100
    await scanner.scan_tenant(7)
    assert publish.call_count == 102
    assert (await scan_state.cursor())["retirement"] == 0


async def test_approval_recovery_query_checks_current_preparing_state(async_db_session):
    repo = projection_worker.KnowledgeFileRepositoryImpl(async_db_session)
    row = _entry(91, approval_instance_id=101, status="preparing")
    async_db_session.add(row)
    await async_db_session.commit()
    assert await repo.has_preparing_approval_entries(101)
    row.entry_status = "active"
    await async_db_session.commit()
    assert not await repo.has_preparing_approval_entries(101)
