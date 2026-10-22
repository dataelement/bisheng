"""覆盖 AC: AC-33、AC-34、AC-35、AC-46、AC-49、AC-50、AC-51、AC-52."""

import copy
import hashlib
import os
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from runtime_manager.container_runner import ExecutionError
from tests.test_kubernetes_executor import runtime as runtime


class Materials:
    def __init__(self):
        self.confirmed = True
        self.content = {}
        self.uploads = []

    def describe(self, artifact_id):
        raw = self.content[artifact_id]
        return {"kind": "snapshot", "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}

    def upload(self, path, *, kind, metadata):
        assert kind == "snapshot" and metadata["integrity_result"] == "ok"
        raw = Path(path).read_bytes()
        key = str(uuid4())
        self.content[key] = raw
        self.uploads.append(key)
        return {"artifact_id": key, "state": "verified", "confirmed_at": "now" if self.confirmed else None}

    def download(self, artifact_id, target, **expected):
        assert expected["expected_sha256"] == hashlib.sha256(self.content[artifact_id]).hexdigest()
        assert expected["expected_size"] == len(self.content[artifact_id])
        target.write_bytes(self.content[artifact_id])
        return self.describe(artifact_id)


def setup(tmp_path):
    volume = tmp_path / "volume"
    (volume / "business").mkdir(parents=True)
    path = volume / "business/app.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE data (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO data VALUES (1,'before')")
    operation = {
        "operation_id": str(uuid4()),
        "app_id": "app-a",
        "payload": {"resolved_delivery": {"profile": {"uid": os.getuid(), "gid": os.getgid()}}},
    }
    return volume, path, operation, Materials()


def run(volume, operation, client, action, **parameters):
    from runtime_manager.k8s_appdb import run_maintenance

    return run_maintenance(
        {"operation": copy.deepcopy(operation), "action": action, "parameters": parameters}, client, volume=volume
    )


def test_snapshot_confirmation_precedes_destructive_ddl(tmp_path):
    volume, path, operation, client = setup(tmp_path)
    client.confirmed = False
    with pytest.raises(ExecutionError, match="snapshot_confirmation"):
        run(volume, operation, client, "backup")
    with pytest.raises(ExecutionError, match="snapshot_confirmation"):
        run(volume, operation, client, "migrate", plan=[{"op": "drop_table", "table": "data"}], snapshot=None)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT value FROM data").fetchone()[0] == "before"


def test_volume_snapshot_migration_and_restart_are_idempotent(tmp_path):
    volume, path, operation, client = setup(tmp_path)
    snapshot = run(volume, operation, client, "backup")
    plan = [{"op": "drop_table", "table": "data"}]
    first = run(volume, operation, client, "migrate", plan=plan, snapshot=snapshot)
    assert first["applied"]
    assert run(volume, operation, client, "migrate", plan=plan, snapshot=snapshot) == first
    assert len(client.uploads) == 1
    assert list((volume / "platform/protected-backups/app-a").glob("*.sqlite"))
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='data'").fetchone() is None
        assert connection.execute("SELECT COUNT(*) FROM _bisheng_runtime_migrations").fetchone()[0] == 1
    with pytest.raises(ExecutionError, match="maintenance_plan_conflict"):
        run(volume, operation, client, "migrate", plan=[], snapshot=snapshot)


def test_restore_protects_current_before_replacement_and_replay(tmp_path):
    volume, path, operation, client = setup(tmp_path)
    old = run(volume, operation, client, "backup")["artifact_id"]
    operation["operation_id"] = str(uuid4())
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE data SET value='newer'")
    result = run(volume, operation, client, "restore", snapshot_id=old)
    protected = result["protected_snapshot"]["artifact_id"]
    protected_path = tmp_path / "protected.sqlite"
    protected_path.write_bytes(client.content[protected])
    with sqlite3.connect(protected_path) as connection:
        assert connection.execute("SELECT value FROM data").fetchone()[0] == "newer"
    assert run(volume, operation, client, "restore", snapshot_id=old) == result
    assert len(client.uploads) == 2
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT value FROM data").fetchone()[0] == "before"


@pytest.mark.parametrize("name", ["business", "business/app.db", "platform", "platform/maintenance"])
def test_volume_links_are_rejected_before_io(tmp_path, name):
    volume, path, operation, client = setup(tmp_path)
    target = tmp_path / "unrelated"
    target.mkdir()
    selected = volume / name
    selected.parent.mkdir(parents=True, exist_ok=True)
    if selected == path:
        selected.unlink()
    elif selected.exists():
        path.unlink()
        selected.rmdir()
    selected.symlink_to(target, target_is_directory=True)
    with pytest.raises(ExecutionError, match="link"):
        run(volume, operation, client, "backup")
    assert list(target.iterdir()) == []


def test_manager_maintenance_persists_result_before_cleanup_and_reuses_it(runtime):
    import json

    from runtime_manager.k8s_data_executor import KubernetesDataExecutor

    executor, platform, cluster, operation, events, _ = runtime
    operation["stage"] = "maintenance"
    operation["payload"]["migration_plan"] = [{"op": "drop_table", "table": "data"}]
    create = cluster.create

    def completed(resource, document):
        result = create(resource, document)
        if resource == "pods":
            stored = cluster.objects[resource, document["metadata"]["name"]]
            stored["status"]["phase"] = "Succeeded"
            for item in stored["status"]["containerStatuses"]:
                item["state"] = {"terminated": {"exitCode": 0}}
        return result

    def logs(name, **kwargs):
        pod = cluster.objects["pods", name]
        assert [c["name"] for c in pod["spec"]["containers"]] == ["maintenance"]
        assert not any(v["name"] == "data-keys" for v in pod["spec"]["volumes"])
        document = json.loads(
            next(e["value"] for e in pod["spec"]["containers"][0]["env"] if e["name"] == "MATERIAL_PLAN")
        )
        result = (
            {"artifact_id": "snap", "confirmed_at": "now", "state": "verified"}
            if document["action"] == "backup"
            else {"applied": ["data"], "skipped": []}
        )
        return "BISHENG_RUNTIME_RESULT " + json.dumps(result)

    cluster.create, cluster.logs = completed, logs
    driver = KubernetesDataExecutor(executor)
    snapshot = driver.request(operation, "backup", {})
    before = len([x for x in events if x[0] == "create"])
    assert driver.request(operation, "backup", {}) == snapshot
    assert len([x for x in events if x[0] == "create"]) == before
    result = driver.request(
        operation, "migrate", {"plan": operation["payload"]["migration_plan"], "snapshot": snapshot}
    )
    assert result["applied"] == ["data"]
    assert len([r for r in platform.rows.values() if r["kind"] == "Pod"]) == 2
    assert all(
        r["stop_state"] == "confirmed" and r["cleanup_state"] == "complete"
        for r in platform.rows.values()
        if r["kind"] == "Pod"
    )
    assert not any(kind in {"pods", "services", "secrets"} for kind, _ in cluster.objects)
    assert (
        platform.operation(operation["operation_id"])["result"]["maintenance_progress"]["backup"]["result"] == snapshot
    )
