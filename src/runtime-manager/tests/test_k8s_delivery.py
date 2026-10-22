"""覆盖 AC: AC-08、AC-24、AC-25、AC-26、AC-27、AC-28、AC-29、AC-42、AC-43、AC-44、AC-45、AC-46、AC-54."""

import copy
import json
import sqlite3

import pytest

from runtime_manager.executors.protocol import ExecutorError
from tests.test_kubernetes_executor import IMAGE
from tests.test_kubernetes_executor import runtime as runtime


def test_full_image_preparation_keeps_frozen_digest_command_and_platform(runtime):
    executor, platform, cluster, operation, _, _ = runtime
    operation.update(kind="prepare", stage="admitted")
    operation["payload"]["delivery"] = {
        "mode": "image",
        "image": IMAGE,
        "startup": {"command": ["python", "server.py"]},
    }
    operation["payload"]["platform"] = "linux/amd64"
    result = executor.prepare(operation)
    assert result["mode"] == "image" and result["image_ref"] == IMAGE
    assert result["platform"] == "linux/amd64" and result["startup"]["command"] == ["python", "server.py"]
    assert not cluster.objects and not platform.rows
    operation["payload"]["delivery"]["image"] = "example/python:latest"
    with pytest.raises(ExecutorError, match="digest"):
        executor.prepare(operation)


def test_runtime_port_database_and_base_path_are_platform_owned(runtime):
    executor, _, cluster, operation, _, _ = runtime
    operation["payload"].update(port=8765, slug="fixture", base_path="/apps/fixture", health={})
    operation["payload"]["runtime_env"].update(PORT="1", BISHENG_APP_DB_URL="wrong", BISHENG_APP_TOKEN="app-token")
    result = executor.launch(operation)
    row = executor.platform.resource(result["exec_ref"])
    pod = cluster.objects["pods", row["name"]]
    app = next(c for c in pod["spec"]["containers"] if c["name"] == "app")
    literals = {e["name"]: e["value"] for e in app["env"] if "value" in e}
    assert literals["PORT"] == literals["BISHENG_APP_PORT"] == "8765"
    assert literals["BISHENG_APP_DB_URL"] == "sqlite:////data/app.db"
    assert literals["BISHENG_APP_BASE_PATH"] == "/apps/fixture"
    assert app["readinessProbe"]["httpGet"]["path"] == "/"
    assert not any(e["name"] in literals and "valueFrom" in e for e in app["env"])
    token = next(e for e in app["env"] if e["name"] == "BISHENG_APP_TOKEN")
    assert "valueFrom" in token


def test_runtime_and_preparer_receive_distinct_scoped_proxy_credentials(runtime):
    executor, platform, cluster, operation, _, _ = runtime
    platform.egress = lambda operation_id, phase, **kwargs: {"principal": "runtime-actor", "token": "runtime-token"}
    result = executor.launch(operation)
    pod = cluster.objects["pods", platform.resource(result["exec_ref"])["name"]]
    app = next(c for c in pod["spec"]["containers"] if c["name"] == "app")
    assert any(e["name"] == "HTTPS_PROXY" and "valueFrom" in e for e in app["env"])
    assert not any(
        e["name"] in {"HTTPS_PROXY", "BISHENG_APP_TOKEN"} for c in pod["spec"]["initContainers"] for e in c["env"]
    )


def test_probe_uses_its_isolated_schema_and_no_production_volume(runtime):
    executor, platform, cluster, operation, _, _ = runtime
    operation.update(kind="probe")
    operation["payload"]["migration_plan"] = [
        {"op": "create_table", "table": "items", "columns": [{"name": "id", "type": "INTEGER", "primary_key": True}]}
    ]
    result = executor.launch(operation)
    pod = cluster.objects["pods", platform.resource(result["exec_ref"])["name"]]
    assert not any("persistentVolumeClaim" in v for v in pod["spec"]["volumes"])
    init = next(c for c in pod["spec"]["initContainers"] if c["name"] == "schema-init")
    document = json.loads(next(e["value"] for e in init["env"] if e["name"] == "SCHEMA_PLAN"))
    assert document["plan"] == operation["payload"]["migration_plan"]
    assert not any("secret" in v for v in init["volumeMounts"])


def test_isolated_schema_initialization_reuses_validated_database_logic(tmp_path):
    from runtime_manager.k8s_appdb import initialize_schema

    plan = [
        {"op": "create_table", "table": "items", "columns": [{"name": "id", "type": "INTEGER", "primary_key": True}]}
    ]
    for _ in range(2):
        initialize_schema({"app_id": "app-a", "plan": plan}, volume=tmp_path)
    with sqlite3.connect(tmp_path / "business/app.db") as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='items'").fetchone()
    assert not list(tmp_path.rglob("*.sqlite"))


def test_source_image_uses_bundle_preparation_then_the_restricted_assembler(runtime, monkeypatch):
    executor, _platform, _, operation, _, _ = runtime
    operation.update(kind="prepare", stage="preparing")
    operation["payload"]["source_artifact_id"] = "source-a"
    operation["payload"]["delivery"] = {"mode": "source-image", "dependencies": {}}
    operation["payload"]["profile"] = copy.deepcopy(operation["payload"]["resolved_delivery"]["profile"])
    operation["payload"].pop("resolved_delivery")
    seen = []
    executor._phase = lambda op, stage, purpose, doc: (
        {"input_key": "c" * 64}
        if stage == "inputs"
        else (
            {"mode": "bundle", "dependency_artifact_id": "dep", "compiled_artifact_id": "compiled"}
            if stage == "upload"
            else {}
        )
    )
    executor.assemble = lambda op, delivery: (
        seen.append(delivery) or {"mode": "source-image", "image_ref": IMAGE, "platform": "linux/amd64"}
    )
    result = executor.prepare(operation)
    assert result["mode"] == "source-image" and seen[0]["mode"] == "bundle"


def test_package_download_honors_offline_mode_without_running_install_code(tmp_path, monkeypatch):
    import os

    from runtime_manager.k8s_helper import prepare_download
    from tests.test_k8s_helper import setup as _fixture

    client, document, _, root = _fixture.__wrapped__(tmp_path)
    work = root / "work"
    result = prepare_download(client, document, work=work)
    document.update(
        phase="resolve",
        offline=True,
        package_environment={"PIP_INDEX_URL": "https://packages.example/simple"},
        dependency_resolution={"input_key": result["input_key"], "artifact_id": ""},
    )
    client.package_proxy = "http://material:token@10.0.0.1:3128"

    def resolver(doc, source, offline, output):
        assert os.environ["PIP_NO_INDEX"] == "1"
        assert os.environ["HTTPS_PROXY"] == client.package_proxy
        output.mkdir()
        (output / "runtime.lock").write_text("")

    prepare_download(client, document, work=work, resolver=resolver)


def test_startup_failure_keeps_bounded_redacted_diagnostics(runtime):
    executor, platform, cluster, operation, _, _ = runtime
    cluster.endpoints_ready = False
    cluster.logs = lambda *args, **kwargs: (
        "fixture-business-token https://user:password@registry.example/path failed\n" * 1000
    )
    with pytest.raises(ExecutorError) as caught:
        executor.launch(operation)
    assert caught.value.tail and len(caught.value.tail.encode()) <= 16384
    assert "fixture-business-token" not in caught.value.tail and "user:password" not in caught.value.tail
    assert platform.rows


def test_restarted_app_logs_include_previous_and_current_same_uid(runtime):
    executor, platform, cluster, operation, _, _ = runtime
    result = executor.launch(operation)
    pod = cluster.objects["pods", platform.resource(result["exec_ref"])["name"]]
    next(c for c in pod["status"]["containerStatuses"] if c["name"] == "app")["restartCount"] = 1
    calls = []

    def logs(name, **kwargs):
        calls.append(kwargs)
        return "previous crash" if kwargs.get("previous") else "current app"

    cluster.logs = logs
    result = executor.logs(result["exec_ref"], tail=20)
    assert "previous crash" in result and "current app" in result
    assert {c.get("previous", False) for c in calls} == {True, False}
    assert all(c["container"] == "app" for c in calls)
