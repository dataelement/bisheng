from __future__ import annotations

import importlib.util
import json
import sys
from argparse import Namespace
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.database.models.flow import FlowType
from bisheng.database.models.session import MessageSession

_SCRIPT = Path(__file__).parents[2] / "scripts" / "migrate_f068_knowledge_chat_entries.py"
_SPEC = importlib.util.spec_from_file_location("migrate_f068_knowledge_chat_entries", _SCRIPT)
assert _SPEC and _SPEC.loader
migration = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = migration
_SPEC.loader.exec_module(migration)


def _session(
    chat_id: str,
    flow_id: str,
    *,
    tenant_id: int = 7,
    is_delete: bool = False,
    entry_flow_id: str | None = None,
) -> migration.SessionSnapshot:
    return migration.SessionSnapshot(
        tenant_id=tenant_id,
        chat_id=chat_id,
        flow_id=flow_id,
        flow_type=FlowType.KNOLEDGE_SPACE.value,
        is_delete=is_delete,
        entry_flow_id=entry_flow_id,
    )


def test_parse_flow_id_accepts_only_f068_knowledge_entry_grammar():
    assert migration.parse_flow_id("space_12_folder_0") == migration.ParsedFlow(12, "folder", 0)
    assert migration.parse_flow_id("space_12_folder_8") == migration.ParsedFlow(12, "folder", 8)
    assert migration.parse_flow_id("space_12_file_9") == migration.ParsedFlow(12, "file", 9)
    assert migration.parse_flow_id("space_12_file_0") is None
    assert migration.parse_flow_id("space_0_folder_0") is None
    assert migration.parse_flow_id("workflow_12") is None


def test_manifest_classifies_all_resource_facts_and_has_stable_order_and_hash():
    spaces = {
        1: migration.SpaceSnapshot(space_id=1, tenant_id=10),
        2: migration.SpaceSnapshot(space_id=2, tenant_id=10),
        3: migration.SpaceSnapshot(space_id=3, tenant_id=11),
    }
    resources = {
        11: migration.ResourceSnapshot(11, 1, 10, 0),
        12: migration.ResourceSnapshot(12, 2, 10, 1),
        13: migration.ResourceSnapshot(13, 3, 11, 1),
        14: migration.ResourceSnapshot(14, 1, 10, 1),
    }
    sessions = [
        _session("z-root", "space_1_folder_0"),
        _session("present", "space_1_folder_11"),
        _session("missing", "space_1_file_99"),
        _session("moved", "space_1_file_12"),
        _session("deleted-space", "space_404_file_99"),
        _session("soft-deleted", "bad-flow", is_delete=True),
        _session("unparseable", "bad-flow"),
        _session("tenant-conflict", "space_1_file_13"),
        _session("type-conflict", "space_1_folder_14"),
    ]

    manifest = migration.build_manifest(list(reversed(sessions)), spaces, resources)
    categories = {item.chat_id: item.category for item in manifest}
    assert categories == {
        "deleted-space": "deleted_space_skipped",
        "missing": "recoverable_missing",
        "moved": "recoverable_moved",
        "present": "resource_present",
        "soft-deleted": "soft_deleted",
        "tenant-conflict": "cross_tenant_conflict",
        "type-conflict": "resource_type_conflict",
        "unparseable": "unparseable",
        "z-root": "native_root",
    }
    assert [item.chat_id for item in manifest] == sorted(item.chat_id for item in manifest)

    first_hash = migration.manifest_sha256(manifest)
    sessions_with_entries = [
        migration.SessionSnapshot(**{**session.__dict__, "entry_flow_id": "space_1_folder_0"}) for session in sessions
    ]
    assert migration.manifest_sha256(migration.build_manifest(sessions_with_entries, spaces, resources)) == first_hash


def test_entry_validation_and_report_mask_sensitive_values(monkeypatch):
    valid = _session("chat-123456", "space_1_file_3", entry_flow_id="space_1_folder_0")
    bad_grammar = _session("bad-entry", "space_1_file_3", entry_flow_id="space_1_folder_2")
    cross_space = _session("cross-entry", "space_1_file_3", entry_flow_id="space_2_folder_0")
    assert migration.validate_entry(valid) == (0, 0)
    assert migration.validate_entry(bad_grammar) == (1, 0)
    assert migration.validate_entry(cross_space) == (0, 1)

    monkeypatch.setattr(
        migration,
        "settings",
        SimpleNamespace(database_url="mysql+pymysql://user:secret@db:3306/bisheng"),
    )
    scan = migration.ScanResult(
        sessions=(valid,),
        manifest=(
            migration.ManifestItem(
                tenant_id=7,
                chat_id=valid.chat_id,
                flow_id=valid.flow_id,
                flow_type=valid.flow_type,
                is_delete=False,
                category="recoverable_missing",
                source_space_id=1,
                resource_kind="file",
                resource_id=3,
                current_space_id=None,
                current_resource_tenant_id=None,
                current_space_tenant_id=None,
            ),
        ),
        manifest_sha256="abc",
        invalid_non_knowledge_entry_count=0,
        invalid_entry_grammar_count=0,
        cross_space_entry_count=0,
    )
    report = migration.report_for_scan(scan, mode="dry-run")
    serialized = json.dumps(report)
    assert "secret" not in serialized
    assert "chat-123456" not in serialized
    assert "cha...456" in serialized


def test_checkpoint_resume_keeps_same_manifest_hash(tmp_path):
    sessions = (
        _session("chat-a", "space_1_file_1"),
        _session("chat-b", "space_1_file_2"),
    )
    manifest = tuple(
        migration.ManifestItem(
            tenant_id=item.tenant_id,
            chat_id=item.chat_id,
            flow_id=item.flow_id,
            flow_type=item.flow_type,
            is_delete=False,
            category="recoverable_missing",
            source_space_id=1,
            resource_kind="file",
            resource_id=index,
            current_space_id=None,
            current_resource_tenant_id=None,
            current_space_tenant_id=None,
        )
        for index, item in enumerate(sessions, start=1)
    )
    scan = migration.ScanResult(sessions, manifest, "stable", 0, 0, 0)
    checkpoint = tmp_path / "checkpoint.json"
    migration.save_checkpoint(checkpoint, "stable", (7, "chat-a"))
    assert migration.load_checkpoint(checkpoint)["manifest_sha256"] == "stable"
    assert [item.chat_id for item in migration.recoverable_items(scan, (7, "chat-a"))] == ["chat-b"]


@pytest.mark.asyncio
async def test_apply_recovery_updates_only_active_null_entry_rows_and_is_idempotent(
    monkeypatch,
    tmp_path,
):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(MessageSession.__table__.create)

    created_at = datetime(2026, 1, 2, 3, 4, 5)
    async with AsyncSession(engine, expire_on_commit=False) as db:
        db.add_all(
            [
                MessageSession(
                    chat_id="recover-me",
                    name="recover",
                    flow_id="space_1_file_10",
                    flow_type=FlowType.KNOLEDGE_SPACE.value,
                    flow_name="knowledge",
                    user_id=1,
                    tenant_id=7,
                    is_delete=False,
                    create_time=created_at,
                    update_time=created_at,
                ),
                MessageSession(
                    chat_id="sticky",
                    name="sticky",
                    flow_id="space_1_file_11",
                    entry_flow_id="space_1_folder_0",
                    flow_type=FlowType.KNOLEDGE_SPACE.value,
                    flow_name="knowledge",
                    user_id=1,
                    tenant_id=7,
                    is_delete=False,
                    create_time=created_at,
                    update_time=created_at,
                ),
            ]
        )
        await db.commit()

    @asynccontextmanager
    async def _session_factory():
        async with AsyncSession(engine, expire_on_commit=False) as db:
            yield db

    monkeypatch.setattr(migration, "get_async_db_session", _session_factory)
    snapshots = (
        _session("recover-me", "space_1_file_10"),
        _session("sticky", "space_1_file_11", entry_flow_id="space_1_folder_0"),
    )
    manifest = tuple(
        migration.ManifestItem(
            tenant_id=item.tenant_id,
            chat_id=item.chat_id,
            flow_id=item.flow_id,
            flow_type=item.flow_type,
            is_delete=False,
            category="recoverable_missing",
            source_space_id=1,
            resource_kind="file",
            resource_id=10 + index,
            current_space_id=None,
            current_resource_tenant_id=None,
            current_space_tenant_id=None,
        )
        for index, item in enumerate(snapshots)
    )
    scan = migration.ScanResult(snapshots, manifest, "stable", 0, 0, 0)
    checkpoint = tmp_path / "checkpoint.json"

    assert await migration.apply_recovery(scan, 1, checkpoint) == 1
    async with AsyncSession(engine, expire_on_commit=False) as db:
        rows = (await db.exec(select(MessageSession).order_by(MessageSession.chat_id))).all()
    assert [(row.chat_id, row.flow_id, row.entry_flow_id, row.create_time) for row in rows] == [
        ("recover-me", "space_1_file_10", "space_1_folder_0", created_at),
        ("sticky", "space_1_file_11", "space_1_folder_0", created_at),
    ]
    assert await migration.apply_recovery(scan, 1, checkpoint) == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_apply_recovery_rejects_checkpoint_cursor_outside_manifest(tmp_path):
    session = _session("chat-a", "space_1_file_1")
    item = migration.ManifestItem(
        tenant_id=7,
        chat_id="chat-a",
        flow_id=session.flow_id,
        flow_type=session.flow_type,
        is_delete=False,
        category="recoverable_missing",
        source_space_id=1,
        resource_kind="file",
        resource_id=1,
        current_space_id=None,
        current_resource_tenant_id=None,
        current_space_tenant_id=None,
    )
    scan = migration.ScanResult((session,), (item,), "stable", 0, 0, 0)
    checkpoint = tmp_path / "checkpoint.json"
    migration.save_checkpoint(checkpoint, "stable", (7, "not-in-manifest"))

    with pytest.raises(ValueError, match="cursor does not exist"):
        await migration.apply_recovery(scan, 10, checkpoint)


@pytest.mark.asyncio
async def test_run_requires_reviewed_sha_and_refuses_blockers(monkeypatch, tmp_path, capsys):
    session = _session("bad", "bad-flow")
    item = migration.ManifestItem(
        tenant_id=7,
        chat_id="bad",
        flow_id="bad-flow",
        flow_type=FlowType.KNOLEDGE_SPACE.value,
        is_delete=False,
        category="unparseable",
        source_space_id=None,
        resource_kind=None,
        resource_id=None,
        current_space_id=None,
        current_resource_tenant_id=None,
        current_space_tenant_id=None,
    )
    blocked = migration.ScanResult((session,), (item,), "reviewed", 0, 0, 0)

    async def _scan(_tenant_id, _batch_size):
        return blocked

    monkeypatch.setattr(migration, "scan_database", _scan)
    args = Namespace(
        tenant_id=7,
        batch_size=500,
        checkpoint_file=tmp_path / "checkpoint.json",
        apply=True,
        expected_input_sha256=None,
    )
    assert await migration.run(args) == migration.EXIT_CONFIRMATION_MISMATCH
    args.expected_input_sha256 = "different"
    assert await migration.run(args) == migration.EXIT_CONFIRMATION_MISMATCH
    args.expected_input_sha256 = "reviewed"
    assert await migration.run(args) == migration.EXIT_BLOCKED
    assert "unparseable" in capsys.readouterr().out
