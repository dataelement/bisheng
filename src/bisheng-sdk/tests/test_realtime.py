"""Committed state, revisions, idempotency and replay share a real SQLite file."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from bisheng_sdk.realtime import OperationConflict, RealtimeStore, ReplayExpired, RevisionConflict


def write(store, value, revision=0, op="create", actor="alice"):
    return store.write("tasks", "one", value, expected_revision=revision, operation_id=op, actor=actor)


def test_two_users_read_same_committed_result_and_replay(tmp_path):
    path = tmp_path / "app.db"
    alice, bob = RealtimeStore(path), RealtimeStore(path)
    initial = bob.snapshot("tasks")
    result = write(alice, {"status": "done"})
    assert bob.events(initial["cursor"]) == [
        {"seq": result["cursor"], "collection": "tasks", "record_id": "one", "revision": 1}
    ]
    assert bob.snapshot("tasks")["records"][0]["value"] == {"status": "done"}
    assert RealtimeStore(path).snapshot("tasks") == bob.snapshot("tasks")


def test_duplicate_is_idempotent_conflicting_reuse_fails(tmp_path):
    store = RealtimeStore(tmp_path / "app.db")
    first = write(store, {"text": "saved"})
    assert write(store, {"text": "saved"}) == first
    with pytest.raises(OperationConflict):
        write(store, {"text": "different"})
    assert len(store.events(0)) == 1


def test_simultaneous_updates_never_silently_overwrite(tmp_path):
    store = RealtimeStore(tmp_path / "app.db")
    write(store, {"value": 0})

    def attempt(n):
        try:
            return write(store, {"value": n}, revision=1, op=f"change-{n}", actor=f"user-{n}")
        except RevisionConflict:
            return None

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(attempt, range(16)))
    assert len([result for result in results if result]) == 1
    assert store.snapshot("tasks")["records"][0]["revision"] == 2
    assert len(store.events(0)) == 2


def test_delete_keeps_revision_and_replay_expiry_requires_snapshot(tmp_path):
    store = RealtimeStore(tmp_path / "app.db")
    write(store, "one")
    write(store, None, revision=1, op="delete")
    assert store.snapshot("tasks")["records"] == []
    with pytest.raises(RevisionConflict):
        write(store, "stale", op="stale")
    write(store, "restored", revision=2, op="restore")
    before = store.snapshot("tasks")
    store.prune(2)
    with pytest.raises(ReplayExpired):
        store.events(0)
    assert store.events(2)[0]["revision"] == 3
    assert store.snapshot("tasks") == before


def test_bad_serialization_rolls_back_without_event(tmp_path):
    store = RealtimeStore(tmp_path / "app.db")
    with pytest.raises(ValueError):
        write(store, float("nan"))
    assert store.snapshot("tasks") == {"cursor": 0, "records": []}
