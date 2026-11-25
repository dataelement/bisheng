"""History preparation bounds production IO without weakening the frozen facts."""

import asyncio
import tracemalloc
from copy import deepcopy
from pathlib import Path
from stat import S_IMODE
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.permission.domain.models import PermissionGrant, PermissionGrantAssignee, ResourcePermissionMode
from scripts import f118_history_business as business
from scripts import prepare_f118_history as history_script
from scripts.f118_history_snapshot import SnapshotRows, SnapshotStore, snapshot_scope
from test.knowledge_unification import test_prepare_history as fixtures

history, native, resource_native = fixtures.history, fixtures.native, fixtures.resource_native


def legacy_digest(snapshot):
    value = deepcopy(snapshot)
    for table in ("knowledgefile", "knowledge_document"):
        for row in value[table]:
            row.pop("level", None)
            row.pop("update_time", None)
    return history_script.checksum(value)


@pytest.mark.parametrize("changed", [False, True])
def test_disk_snapshot_and_streaming_hash_keep_legacy_plan_exactly(changed):
    snapshot = {name: [] for name in business.models()}
    snapshot.update(_model_names=["模型😀"], _legacy_embedding_names=[])
    snapshot["knowledge"] = [{"id": 1, "tenant_id": 1, "type": 3, "model": "1"}]
    snapshot["knowledgefile"] = [
        {
            "id": 2,
            "tenant_id": 2 if changed else 1,
            "knowledge_id": 1,
            "file_type": 1,
            "file_level_path": "",
            "level": 4,
            "update_time": "then",
            "description": "保留中文 😀",
            "metadata": {"a": [None, False, 1.25]},
        }
    ]
    original = deepcopy(snapshot)
    with SnapshotStore() as store:
        disk = {}
        for name, rows in snapshot.items():
            if name.startswith("_"):
                disk[name] = rows
            else:
                store.append(name, rows)
                disk[name] = store.rows(name)
        assert business.state_digest(disk) == business.state_digest(snapshot) == legacy_digest(snapshot)
        plan, after = business.build(disk)
        expected, expected_after = business.build(snapshot)
        assert plan == expected
        assert {name: list(rows) for name, rows in after.items()} == expected_after
        assert plan["after_digest"] == legacy_digest(expected_after)
        assert isinstance(after["knowledgefile"], SnapshotRows)
    assert snapshot == original


@pytest.mark.parametrize("count", [200, 400])
def test_nested_large_row_hash_preserves_original_canonical_bytes(count):
    snapshot = {name: [] for name in business.models()}
    snapshot.update(_model_names=["模型😀"], _legacy_embedding_names=["legacy"])
    values = [None, True, False, -0.0, 0.1, 1e-300, 1e300, 9007199254740993, "汉字😀"]
    snapshot["flow"] = [
        {
            "id": str(i),
            "tenant_id": 1,
            "data": {"nodes": [{"id": "n", "parameters": {"z": values, "a": [values] * 10}}]},
        }
        for i in range(count)
    ]
    assert business.state_digest(snapshot) == legacy_digest(snapshot)


@pytest.mark.parametrize("failure", [None, RuntimeError, asyncio.CancelledError])
async def test_scratch_is_private_and_removed_on_every_command_exit(failure):
    locations = []

    @snapshot_scope
    async def command():
        store = SnapshotStore()
        directory = Path(store.directory.name)
        locations.append(directory)
        assert S_IMODE(directory.stat().st_mode) == 0o700
        assert S_IMODE((directory / "rows.sqlite").stat().st_mode) == 0o600
        store.append("rows", [{"id": 1, "text": "private"}])
        assert store.rows("rows").by_id()[1]["text"] == "private"
        if failure:
            raise failure()

    if failure:
        with pytest.raises(failure):
            await command()
    else:
        await command()
    assert not locations[0].exists()


class CountId(int):
    conversions = 0

    def __str__(self):
        type(self).conversions += 1
        return super().__str__()


@pytest.mark.parametrize("count", [100, 200])
def test_healthy_member_inventory_builds_root_key_set_once(count):
    snapshot = {name: [] for name in business.models()}
    snapshot["knowledge"] = [{"id": CountId(i), "tenant_id": 1, "type": 3, "model": "1"} for i in range(1, count + 1)]
    snapshot["space_channel_member"] = [
        {"id": i, "business_type": "space", "business_id": str(i)} for i in range(1, count + 1)
    ]
    CountId.conversions = 0
    plan, _ = business.build(snapshot)
    assert not plan["updates"] and not plan["deletes"] and not plan["blocked"]
    assert CountId.conversions == count


@pytest.mark.parametrize("count", [200, 400])
async def test_existence_checks_use_bounded_pk_batches_and_keep_global_presence(history, count):
    # Real SQLite, including a physically present foreign tenant: it must not
    # become a purge candidate merely because normal tenant filtering hides it.
    async with history_script.global_session(history.sessions) as session:
        session.add(KnowledgeFile(id=800, tenant_id=202, knowledge_id=10, file_name="foreign", file_type=1))
    modes = [
        SimpleNamespace(id=i, resource_type="knowledge_file", resource_id=str(i), projection_state="CURRENT")
        for i in range(1000, 1000 + count)
    ]
    modes.append(SimpleNamespace(id=800, resource_type="knowledge_file", resource_id="800", projection_state="CURRENT"))
    statements = []

    def capture(conn, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append((statement, parameters))

    async with history.sessions() as session:
        sa.event.listen(session.bind.sync_engine, "before_cursor_execute", capture)
        try:
            async with history_script.global_session(history.sessions) as scope:
                missing = await history_script.hard_missing_batch(scope, modes)
        finally:
            sa.event.remove(session.bind.sync_engine, "before_cursor_execute", capture)
    assert missing == set(range(1000, 1000 + count))
    assert len(statements) == count // 200 + 1
    assert all(len(params) <= 200 for _, params in statements)


async def test_noop_business_repair_never_requests_write_locks(history, monkeypatch):
    async with history_script.global_session(history.sessions) as session:
        snapshot = await business.read(session)
        plan, _ = business.build(snapshot)
    assert not plan["updates"] and not plan["deletes"]
    original, locks = business.read, []

    async def read(session, *, lock=False):
        locks.append(lock)
        return await original(session, lock=lock)

    monkeypatch.setattr(business, "read", read)
    async with history_script.global_session(history.sessions) as session:
        await business.apply(session, plan)
    assert locks == [False]


async def test_capture_keeps_only_selected_parent_rows_in_memory(history):
    plan = await history_script.capture(history.sessions, history.fga)
    assert [item["before_file"]["id"] for item in plan["parents"]] == [30]
    assert all(isinstance(item, dict) for item in plan["parents"])
    # The temporary indexes have disappeared, while the original plan remains
    # ordinary canonical JSON and can be applied/replayed with the old schema.
    assert history_script.canonical(plan) == plan
    await history_script.apply(
        plan, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7
    )


@pytest.mark.parametrize("count", [100, 200])
@pytest.mark.parametrize("missing", [False, True])
async def test_actual_capture_queries_scale_by_pages_even_for_many_orphans(history, count, missing):
    from bisheng.knowledge.domain.models.knowledge import Knowledge
    from test.knowledge_unification.test_migration_resource_repository import resource

    if not missing:
        await history.db.insert(Knowledge, [resource(i, model=None) for i in range(1000, 1000 + count)])
    await history.db.insert(
        ResourcePermissionMode,
        [
            {
                "id": i,
                "tenant_id": 101,
                "resource_type": "knowledge_library",
                "resource_id": str(i),
                "mode": "INHERIT",
                "version": 1,
                "projection_state": "CURRENT",
            }
            for i in range(1000, 1000 + count)
        ],
    )
    queries = []

    def observe(conn, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append((statement, parameters))

    engine = history.db.engine.sync_engine
    sa.event.listen(engine, "before_cursor_execute", observe)
    try:
        plan = await history_script.capture(history.sessions, history.fga)
    finally:
        sa.event.remove(engine, "before_cursor_execute", observe)
    assert len(plan["purges"]) == (count if missing else 0) + 1
    assert len(queries) < 40 + (count // 50) * 4
    assert all(len(parameters) <= 205 for _, parameters in queries)
    print({"capture_modes": count, "all_missing": missing, "selects": len(queries)}, flush=True)


@pytest.mark.parametrize("count", [250, 500])
def test_complete_digest_does_not_load_large_payload_inventory_into_python_memory(count):
    with SnapshotStore() as store:
        for start in range(0, count, 25):
            store.append("knowledge", [{"id": i, "payload": str(i) + "x" * 65536} for i in range(start, start + 25)])
        tracemalloc.start()
        try:
            digest = business.state_digest({"knowledge": store.rows("knowledge")})
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert len(digest) == 64
        assert peak < 1024 * 1024
        with pytest.raises(ValueError, match="unchanged snapshot"):
            store.rows("knowledge").overlay({}, {0}).grouped(("id",))
        print({"history_rows": count, "payload_bytes": 65536, "digest_python_peak_bytes": peak}, flush=True)


async def test_inventory_upload_has_one_verified_readback_and_rejects_corruption():
    from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
    from bisheng.knowledge.application.unification_artifacts import UnificationArtifactStore
    from bisheng.knowledge.application.unification_inventory import _Pages
    from test.knowledge_unification.test_migration_artifacts import ObjectIO, content

    io = ObjectIO()
    pages = _Pages(UnificationArtifactStore(io), "e2e-f118-run", lambda: None)
    await pages._put(content(), "baseline")
    assert [call[0] for call in io.calls] == ["exists", "put", "get"]
    io.read_corruption = content(records=[{"id": 99}])
    with pytest.raises(ReferenceCoverageNotReadyError):
        await pages._put(content(), "baseline")


@pytest.mark.parametrize("count", [100, 200])
@pytest.mark.parametrize("sql_children", [False, True])
def test_retained_leaf_blocks_entire_chain_without_rescanning_every_candidate(count, sql_children):
    class CountGets(dict):
        calls = 0

        def get(self, *args):
            self.calls += 1
            return super().get(*args)

    purges = [
        {"mode": {"id": i, "resource_type": "folder", "resource_id": str(i)}, "objects": (f"folder:{i}",)}
        for i in range(count)
    ]
    incoming, children = CountGets(), CountGets()
    for i in range(count):
        if sql_children:
            children["folder", str(i)] = {i + 1}
        else:
            incoming[f"folder:{i}"] = [(f"folder:{i}", "parent", f"folder:{i + 1}")]
    assert history_script.fga_blocked_modes(purges, incoming, children, set()) == set(range(count))
    assert incoming.calls == children.calls == count
    # A proven extra parent tuple scheduled for deletion is not a downstream.
    incoming = {"folder:0": [("folder:0", "parent", "live:external")]}
    assert not history_script.fga_blocked_modes(purges[:1], incoming, {}, {incoming["folder:0"][0]})


async def test_large_candidate_buckets_keep_foreign_assignees_and_zero_primary_keys(history):
    await history.db.insert(
        PermissionGrant,
        [
            {
                "id": i,
                "tenant_id": 101,
                "resource_type": "knowledge_file",
                "resource_id": "999",
                "model_key": f"custom-{i}",
            }
            for i in range(401)
        ],
    )
    await history.db.insert(
        PermissionGrantAssignee,
        [
            {
                "id": 0,
                "grant_id": 0,
                "tenant_id": 202,
                "subject_type": "user",
                "subject_id": "7",
                "source_type": "manual",
                "source_ref": "x",
                "source_locator": "x",
                "source_fingerprint": "f" * 64,
                "projected_subject": "user:7",
            }
        ],
    )
    plan = await history_script.capture(history.sessions, history.fga)
    assert not plan["purges"]
    evidence = next(item for item in plan["retained_evidence"] if item.get("reason") == "foreign_assignee")
    assert [row["id"] for row in evidence["sql"]["permission_grant"]] == list(range(401))
    assert [(row["id"], row["tenant_id"]) for row in evidence["sql"]["permission_grant_assignee"]] == [(0, 202)]
