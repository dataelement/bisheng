"""覆盖 AC: AC-15、AC-16、AC-33、AC-34、AC-36、AC-37、AC-43、AC-48、AC-50."""

import copy
import hashlib
import json
import sqlite3
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

KEY = Ed25519PrivateKey.from_private_bytes(b"d" * 32)
UID = "22222222-2222-4222-8222-222222222222"
REF = "33333333-3333-4333-8333-333333333333"


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def grant(action="tables", parameters=None, *, request_id=None, now=1000):
    parameters = parameters or {}
    claims = {
        "version": 1,
        "operation_id": "operation-a",
        "request_id": request_id or str(uuid4()),
        "app_id": "app-a",
        "exec_ref": REF,
        "pod_uid": UID,
        "actor_ref": "user:1",
        "action": action,
        "parameters_sha256": hashlib.sha256(encoded(parameters)).hexdigest(),
        "nonce": str(uuid4()),
        "issued_at": now,
        "not_after": now + 5,
        "deadline": now + 60,
    }
    document = {"key_id": "data-key", "claims": claims}
    return {**document, "signature": KEY.sign(b"BISHENG-RUNTIME-DATA-V1\n" + encoded(document)).hex()}


def verify(ticket, params=None, *, now=1001):
    from runtime_manager.data_grant import verify_grant

    return verify_grant(
        ticket,
        params or {},
        {"data-key": KEY.public_key().public_bytes_raw().hex()},
        app_id="app-a",
        exec_ref=REF,
        pod_uid=UID,
        now=now,
    )


@pytest.fixture
def helper(tmp_path):
    from runtime_manager.k8s_data_helper import DataHelper

    business = tmp_path / "business"
    business.mkdir()
    with sqlite3.connect(business / "app.db") as db:
        db.execute("create table items(id integer primary key, name text)")
        db.execute("insert into items values(1, 'old')")
    value = DataHelper(
        tmp_path,
        app_id="app-a",
        exec_ref=REF,
        pod_uid=UID,
        public_keys={"data-key": KEY.public_key().public_bytes_raw().hex()},
        clock=lambda: 1001,
    )
    return value, business / "app.db", tmp_path


def test_public_key_verification_accepts_only_five_second_scoped_grant():
    assert verify(grant())["action"] == "tables"
    from runtime_manager.data_grant import DataGrantError

    with pytest.raises(DataGrantError):
        verify(grant(), now=1006)


@pytest.mark.parametrize(
    "field,value",
    [
        ("app_id", "other"),
        ("exec_ref", str(uuid4())),
        ("pod_uid", str(uuid4())),
        ("action", "sql"),
        ("not_after", 1010),
        ("deadline", 1061),
    ],
)
def test_even_valid_signatures_cannot_widen_scope_or_deadlines(field, value):
    from runtime_manager.data_grant import DataGrantError

    ticket = grant()
    ticket["claims"][field] = value
    body = {key: ticket[key] for key in ("key_id", "claims")}
    ticket["signature"] = KEY.sign(b"BISHENG-RUNTIME-DATA-V1\n" + encoded(body)).hex()
    with pytest.raises(DataGrantError):
        verify(ticket)


def test_parameters_and_signing_key_are_not_substitutable():
    from runtime_manager.data_grant import DataGrantError

    ticket = grant("rows", {"table": "items"})
    with pytest.raises(DataGrantError):
        verify(ticket, {"table": "other"})
    changed = copy.deepcopy(ticket)
    changed["key_id"] = "unknown"
    with pytest.raises(DataGrantError):
        verify(changed, {"table": "items"})


def test_one_row_edit_is_durable_and_same_nonce_replay_is_refused(helper):
    from runtime_manager.data_grant import DataGrantError

    worker, database, root = helper
    parameters = {"table": "items", "key": "1", "values": {"name": "new"}}
    ticket = grant("update", parameters)
    result = worker.submit(ticket, parameters)
    assert result["after"]["name"] == "new"
    with sqlite3.connect(database) as db:
        assert db.execute("select name from items where id=1").fetchone()[0] == "new"
    journal = json.loads((root / "platform/journal" / (ticket["claims"]["request_id"] + ".json")).read_text())
    assert journal["state"] == "done" and journal["parameters_sha256"] == ticket["claims"]["parameters_sha256"]
    assert "signature" not in str(journal)
    with pytest.raises(DataGrantError, match="replayed"):
        worker.submit(ticket, parameters)
    fresh = grant("update", parameters, request_id=ticket["claims"]["request_id"])
    assert worker.submit(fresh, parameters) == result


def test_started_without_done_remains_unknown_and_never_reexecutes(helper):
    worker, database, root = helper
    parameters = {"table": "items", "key": "1", "values": {"name": "must-not-run"}}
    ticket = grant("update", parameters)
    request = ticket["claims"]
    journal = root / "platform/journal" / (request["request_id"] + ".json")
    journal.write_text(
        json.dumps(
            {"state": "started", "action": "update", "parameters_sha256": request["parameters_sha256"], "nonces": []}
        )
    )
    assert worker.submit(ticket, parameters)["state"] == "unknown"
    with sqlite3.connect(database) as db:
        assert db.execute("select name from items").fetchone()[0] == "old"


def test_new_readonly_request_can_query_an_original_result(helper):
    worker, _, _ = helper
    original = grant("tables")
    result = worker.submit(original, {})
    params = {
        "target_request_id": original["claims"]["request_id"],
        "parameters_sha256": original["claims"]["parameters_sha256"],
    }
    queried = worker.submit(grant("result", params), params)
    assert queried["state"] == "done" and queried["result"] == result


def test_same_request_id_cannot_change_action_or_parameters(helper):
    from runtime_manager.data_grant import DataGrantError

    worker, _, _ = helper
    original = grant("tables")
    worker.submit(original, {})
    changed = grant("rows", {"table": "items"}, request_id=original["claims"]["request_id"])
    with pytest.raises(DataGrantError):
        worker.submit(changed, {"table": "items"})


def test_data_sql_and_database_symlinks_are_refused(helper):
    from runtime_manager.data_grant import DataGrantError

    worker, database, root = helper
    with pytest.raises(DataGrantError):
        worker.submit(grant("sql", {"sql": "drop table items"}), {"sql": "drop table items"})
    database.unlink()
    outside = root / "platform/private.sqlite"
    with sqlite3.connect(outside) as db:
        db.execute("create table secret(id integer)")
    database.symlink_to(outside)
    result = worker.submit(grant("tables"), {})
    assert "error" in result and "secret" not in str(result)


def test_export_is_a_bounded_file_result_outside_business_mount(helper):
    worker, _, root = helper
    params = {"table": "items"}
    result = worker.submit(grant("export", params), params)
    path = worker.export_path(result["export"]["request_id"])
    assert path.is_relative_to(root / "platform") and "name" in path.read_text()
    assert result["export"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_crash_after_sqlite_commit_before_done_never_replays_the_write(helper, monkeypatch):
    worker, database, _ = helper
    params = {"table": "items", "key": "1", "values": {"name": "first"}}
    ticket = grant("update", params)
    write = worker._write

    def fail_done(path, document):
        if document.get("state") == "done":
            raise OSError("simulated journal fsync failure")
        return write(path, document)

    monkeypatch.setattr(worker, "_write", fail_done)
    with pytest.raises(OSError):
        worker.submit(ticket, params)
    with sqlite3.connect(database) as db:
        assert db.execute("select name from items").fetchone()[0] == "first"
        db.execute("update items set name='changed-by-app'")
    monkeypatch.setattr(worker, "_write", write)
    retried = worker.submit(grant("update", params, request_id=ticket["claims"]["request_id"]), params)
    assert retried["state"] == "unknown"
    with sqlite3.connect(database) as db:
        assert db.execute("select name from items").fetchone()[0] == "changed-by-app"


def test_action_deadline_terminates_worker_and_preserves_unknown(helper, monkeypatch):
    import time

    worker, _, _ = helper
    worker.clock = lambda: 1004.1
    ticket = grant()
    ticket["claims"]["deadline"] = 1005
    ticket["signature"] = KEY.sign(
        b"BISHENG-RUNTIME-DATA-V1\n" + encoded({key: ticket[key] for key in ("key_id", "claims")})
    ).hex()

    def slow(*args):
        time.sleep(5)
        return {"tables": []}

    monkeypatch.setattr(worker, "_dispatch", slow)
    started = time.monotonic()
    assert worker.submit(ticket, {})["state"] == "unknown"
    assert time.monotonic() - started < 2.5


def test_requests_are_serialized_by_the_volume_lock(helper):
    from runtime_manager.data_grant import DataGrantError

    worker, _, _ = helper
    with worker._locked():
        with pytest.raises(DataGrantError, match="busy"):
            worker.submit(grant(), {})


def test_http_helper_requires_a_grant_and_streams_only_authorized_export(helper):
    from fastapi.testclient import TestClient

    from runtime_manager.k8s_data_helper import create_app

    worker, _, _ = helper
    client = TestClient(create_app(worker))
    assert client.post("/actions", json={"parameters": {}}).status_code == 403
    parameters = {"table": "items"}
    response = client.post("/actions", json={"grant": grant("export", parameters), "parameters": parameters})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv") and b"id,name" in response.content
    assert response.headers["x-content-sha256"] == hashlib.sha256(response.content).hexdigest()


def test_helper_control_state_reveals_no_database_or_journal_contents(helper):
    from fastapi.testclient import TestClient

    from runtime_manager.k8s_data_helper import create_app

    worker, _, _ = helper
    client = TestClient(create_app(worker))
    assert client.get("/healthz").json() == {"status": "ok", "key_ids": ["data-key"]}
    assert client.get("/execution-state").json() == {"idle": True}
    with worker._locked():
        assert client.get("/execution-state").json() == {"idle": False}


def test_public_key_projection_can_rotate_without_changing_a_serving_pod(helper):
    from runtime_manager.data_grant import DataGrantError

    worker, _, _ = helper
    worker.key_loader = lambda: {"next-key": KEY.public_key().public_bytes_raw().hex()}
    with pytest.raises(DataGrantError):
        worker.submit(grant(), {})
