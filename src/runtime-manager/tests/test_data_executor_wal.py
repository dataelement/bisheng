"""WAL readers need sidecar writes while business SQL remains read-only.

覆盖 AC: AC-10、AC-16、AC-34、AC-36、AC-46、AC-55。
Real Docker cases require an explicit opt-in and an already loaded helper image.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest

from runtime_manager.appdb import AppDbService
from runtime_manager.config import Config
from runtime_manager.data_executor import DataExecutor


@pytest.mark.parametrize("action", ["tables", "schema", "rows", "export", "update"])
def test_data_helper_mount_allows_sqlite_wal_sidecar_locks(tmp_path, action):
    """AC-33, AC-46, AC-56: SQL readers still require a writable WAL directory."""
    service = DataExecutor(Config(data_root=tmp_path, host_data_root=Path("/host/test")), None)
    payload = service.payload("app", action, {}, tmp_path / "exports", "image", "operation")
    assert payload["HostConfig"]["Binds"][0] == "/host/test/apps/app/db:/app-data/apps/app/db:rw"
    assert payload["HostConfig"]["NetworkMode"] == "none"
    assert payload["HostConfig"]["ReadonlyRootfs"] is True
    assert payload["User"] == "10001:10001"
    assert payload["HostConfig"]["CapDrop"] == ["ALL"]


def database(config, app):
    path = config.app_data_dir(app) / "app.db"
    path.parent.mkdir(parents=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, value TEXT)")
    connection.executemany("INSERT INTO items VALUES(?,?)", [(1, "initial"), (2, "initial")])
    connection.commit()
    connection.close()
    return path


def test_sql_read_only_connection_cannot_change_business_data(tmp_path):
    """AC-33, AC-50: Writable sidecars do not authorize business SQL writes."""
    config = Config(data_root=tmp_path)
    path = database(config, "app")
    assert not path.with_name("app.db-shm").exists()
    service = AppDbService(config)
    assert service.list_tables("app") == [{"name": "items", "column_count": 2}]
    before = service.rows("app", "items")
    connection = service._connect("app", write=False)
    try:
        with pytest.raises(sqlite3.OperationalError) as failure:
            connection.execute("UPDATE items SET value='must-not-be-written'")
        assert failure.value.sqlite_errorname == "SQLITE_READONLY"
    finally:
        connection.close()
    assert service.rows("app", "items") == before


def test_wal_reader_observes_only_consistent_committed_writer_transactions(tmp_path):
    """AC-33, AC-50: Live WAL reads do not use immutable or a copied database."""
    config = Config(data_root=tmp_path)
    path = database(config, "app")
    service = AppDbService(config)
    opened, commit, finished = threading.Event(), threading.Event(), threading.Event()
    errors = []
    sentinel = uuid4().hex

    def writer():
        connection = sqlite3.connect(path, timeout=5)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("UPDATE items SET value=?", (sentinel,))
            opened.set()
            assert commit.wait(5), "reader failed to release the test writer"
            connection.commit()
        except Exception as error:
            errors.append(type(error).__name__)
        finally:
            connection.close()
            finished.set()

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        assert opened.wait(5)
        during = service.rows("app", "items")
        assert [row["values"]["value"] for row in during["rows"]] == ["initial", "initial"]
    finally:
        commit.set()
        thread.join(5)
    assert finished.is_set() and not errors
    after = service.rows("app", "items")
    assert [row["values"]["value"] for row in after["rows"]] == [sentinel, sentinel]
    assert during["total"] == after["total"] == 2


@pytest.mark.docker
@pytest.mark.parametrize("state", ["clean-wal-no-sidecars", "committed-wal-missing-shm", "committed-wal-with-shm"])
def test_real_helper_reads_latest_wal_and_cleans_only_its_container(tmp_path, state):
    """AC-33, AC-46, AC-56: Execute the actual generated payload on a real Engine."""
    from runtime_manager.docker_backend import _RealDockerBackend

    image = os.environ.get("RTM_TEST_DATA_HELPER_IMAGE")
    if not image:
        pytest.skip("set RTM_TEST_DATA_HELPER_IMAGE to an already loaded native manager image")
    engine = _RealDockerBackend(os.environ.get("RTM_TEST_DOCKER_HOST", ""))
    app = "e2e-f059-wal-" + uuid4().hex
    config = Config(data_root=tmp_path, node_id="e2e-f059-wal-test")
    path = database(config, app)
    expected = "initial"
    if state != "clean-wal-no-sidecars":
        expected = uuid4().hex
        # A genuinely exited writer leaves committed frames outside app.db.
        code = (
            "import os,sqlite3,sys; c=sqlite3.connect(sys.argv[1]); "
            "c.execute('PRAGMA wal_autocheckpoint=0'); "
            "c.execute('UPDATE items SET value=?',(sys.argv[2],)); c.commit(); os._exit(0)"
        )
        subprocess.run([sys.executable, "-c", code, str(path), expected], check=True)
        assert path.with_name("app.db-wal").stat().st_size > 0
        if state == "committed-wal-missing-shm":
            path.with_name("app.db-shm").unlink()
    else:
        assert not path.with_name("app.db-wal").exists()
        assert not path.with_name("app.db-shm").exists()
    # These disposable files have no other host users and only one exact app bind.
    path.parent.chmod(0o777)
    for item in path.parent.iterdir():
        item.chmod(0o666)
    output = tmp_path / "exports"
    output.mkdir(mode=0o777)
    output.chmod(0o777)
    service = DataExecutor(config, engine)
    original_database = path.read_bytes()
    ref = None
    try:
        for action, parameters in [("tables", {}), ("rows", {"table": "items"})]:
            payload = service.payload(app, action, parameters, output, engine.inspect_image(image)["Id"], app)
            ref = engine.create_container(app + "-" + action, payload)
            engine.start_container(ref)
            deadline = time.monotonic() + 20
            while engine.inspect_container(ref)["State"]["Running"]:
                assert time.monotonic() < deadline
                time.sleep(0.05)
            answer = json.loads(engine.container_logs(ref, tail=1, timestamps=False))
            assert engine.inspect_container(ref)["State"]["ExitCode"] == 0
            assert "error" not in answer, "WAL read failed in the real isolated data helper"
            if action == "tables":
                assert answer["result"] == {"tables": [{"name": "items", "column_count": 2}]}
            else:
                assert answer["result"]["total"] == 2
                assert [row["values"]["value"] for row in answer["result"]["rows"]] == [expected, expected]
            assert path.read_bytes() == original_database, "a read action changed the main database bytes"
            engine.remove_container(ref, force=False)
            ref = None
    finally:
        if ref:
            actual = engine.inspect_container(ref)
            assert actual["Config"]["Labels"]["bisheng.app.id"] == app
            assert actual["Config"]["Labels"]["bisheng.runtime.node"] == config.node_id
            if actual["State"]["Running"]:
                engine.stop_container(ref, timeout=5)
            assert not engine.inspect_container(ref)["State"]["Running"]
            engine.remove_container(ref, force=False)
