"""覆盖 AC: AC-11、AC-15、AC-33、AC-35、AC-36、AC-43、AC-48、AC-49、AC-50、AC-52."""

import base64
import copy
import hashlib
import json
from threading import Lock
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from starlette.requests import Request

from runtime_manager.errors import DataBusyError
from tests.test_kubernetes_executor import HELPER
from tests.test_kubernetes_executor import runtime as runtime


def data_operation(runtime, *, online=False, original=None):
    _executor, platform, _, serving, _, clock = runtime
    op = copy.deepcopy(serving)
    op.update(operation_id=uuid4().hex, kind="data", deadline=clock.iso(60), stage="admitted")
    op["payload"] = {
        "online": online,
        "request_id": str(uuid4()),
        "actor_ref": "user:1",
        "action": "tables",
        "parameters_digest": hashlib.sha256(b"{}").hexdigest(),
        "tier": {"memory_mb": 128, "cpu_millicores": 25},
        "resolved_delivery": {
            "mode": "image",
            "image_ref": HELPER,
            "platform": "linux/amd64",
            "profile": {"uid": 10001, "gid": 10001},
            "startup": {},
        },
        "target_exec_ref": original["exec_ref"] if original else "",
        "target_pod_uid": original["pod_uid"] if original else "",
    }
    platform.operations[op["operation_id"]] = op
    return op


def ready_session(runtime, *, online=False):
    from runtime_manager.k8s_data_executor import KubernetesDataExecutor

    executor, platform, cluster, serving, events, _ = runtime
    previous = executor.launch(serving)
    if not online:
        executor.request_stop(previous["exec_ref"], serving)
        assert executor.confirm_stopped(previous["exec_ref"])["stopped"]
        assert executor.cleanup(serving)["complete"]
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/healthz":
            return httpx.Response(200, json={"status": "ok", "key_ids": ["data-key"]})
        if request.url.path == "/execution-state":
            return httpx.Response(200, json={"idle": True})
        body = json.loads(request.content)
        assert "fixture-control-hmac" not in request.content.decode()
        assert "private_key" not in request.content.decode()
        return httpx.Response(200, json={"tables": [], "request_id": body["grant"]["claims"]["request_id"]})

    driver = KubernetesDataExecutor(executor, transport=httpx.MockTransport(handler))
    executor.data_transport = driver
    op = data_operation(runtime, online=online, original=previous)
    target = driver.prepare_session(op)
    platform.operations[op["operation_id"]].update(stage="ready", result={"data_target": target})
    op = copy.deepcopy(platform.operations[op["operation_id"]])
    ticket = {
        "key_id": "data-key",
        "claims": {
            "operation_id": op["operation_id"],
            "request_id": op["payload"]["request_id"],
            "app_id": op["app_id"],
            "exec_ref": target["exec_ref"],
            "pod_uid": target["pod_uid"],
            "action": "tables",
            "parameters_sha256": hashlib.sha256(b"{}").hexdigest(),
        },
        "signature": "a" * 128,
    }
    op["data_grant"] = ticket
    return driver, executor, platform, cluster, op, target, requests, events


def test_offline_data_uses_the_fixed_slot_and_retains_the_original_volume(runtime):
    driver, _, platform, cluster, op, target, _, _ = ready_session(runtime)
    assert target["online"] is False
    rows = [row for row in platform.rows.values() if row["operation_id"] == op["operation_id"]]
    assert [row["kind"] for row in rows] == ["Pod"]
    pod = cluster.objects["pods", platform.rows[target["exec_ref"]]["name"]]
    assert [c["name"] for c in pod["spec"]["containers"]] == ["data-helper"]
    assert pod["spec"]["activeDeadlineSeconds"] <= 60
    assert not any("secret" in volume for volume in pod["spec"]["volumes"])
    assert driver.request(op, "tables", {})["tables"] == []
    assert driver.cleanup_session(op)["complete"] is True
    assert any(kind == "persistentvolumeclaims" for kind, _ in cluster.objects)


def test_online_data_reuses_the_same_uid_without_creating_a_second_pod(runtime):
    driver, _, platform, cluster, op, target, _, _ = ready_session(runtime, online=True)
    assert target["online"] is True and target["exec_ref"] == op["payload"]["target_exec_ref"]
    assert len([1 for kind, _ in cluster.objects if kind == "pods"]) == 1
    assert not platform.resources(op["operation_id"])
    assert driver.request(op, "tables", {})["tables"] == []
    op["payload"]["data_action_finished"] = "done"
    platform.operations[op["operation_id"]]["payload"]["data_action_finished"] = "done"
    assert driver.cleanup_session(op)["complete"] is True
    assert len([1 for kind, _ in cluster.objects if kind == "pods"]) == 1


def test_forwarded_owner_grant_is_unchanged_and_not_a_manager_signature(runtime):
    driver, _, _, _, op, _, requests, _ = ready_session(runtime)
    driver.request(op, "tables", {})
    forwarded = json.loads(requests[-1].content)
    assert forwarded == {"grant": op["data_grant"], "parameters": {}}
    assert "X-Signature" not in requests[-1].headers


def test_unconfirmed_old_writer_never_gets_an_offline_data_replacement(runtime):
    from runtime_manager.k8s_data_executor import KubernetesDataExecutor

    executor, platform, cluster, serving, _, _ = runtime
    original = executor.launch(serving)
    op = data_operation(runtime, original=original)
    driver = KubernetesDataExecutor(executor, transport=httpx.MockTransport(lambda _: pytest.fail("no helper request")))
    with pytest.raises(DataBusyError):
        driver.prepare_session(op)
    assert len([1 for kind, _ in cluster.objects if kind == "pods"]) == 1
    assert not any(row["purpose"] == "data" for row in platform.rows.values())


def test_online_helper_failure_cannot_fall_back_to_a_second_mount(runtime):
    from runtime_manager.k8s_data_executor import KubernetesDataExecutor

    executor, _, cluster, serving, _, _ = runtime
    original = executor.launch(serving)
    op = data_operation(runtime, online=True, original=original)
    driver = KubernetesDataExecutor(executor, transport=httpx.MockTransport(lambda _: httpx.Response(503)))
    with pytest.raises(DataBusyError):
        driver.prepare_session(op)
    assert len([1 for kind, _ in cluster.objects if kind == "pods"]) == 1


def test_wrong_action_parameters_or_uid_are_refused_before_the_helper(runtime):
    driver, _, _, cluster, op, target, requests, _ = ready_session(runtime)
    count = len(requests)
    with pytest.raises(DataBusyError):
        driver.request(op, "tables", {"unexpected": True})
    with pytest.raises(DataBusyError):
        driver.request(op, "update", {})
    row = driver.runtime.platform.resource(target["exec_ref"])
    cluster.objects["pods", row["name"]]["metadata"]["uid"] = str(uuid4())
    with pytest.raises(DataBusyError):
        driver.request(op, "tables", {})
    assert len(requests) == count


async def test_k8s_data_api_requires_the_owner_grant_and_avoids_the_local_app_lock(runtime, monkeypatch):
    from runtime_manager.api import platform_data as api

    _driver, executor, platform, _, op, _, _, _ = ready_session(runtime, online=True)
    service = SimpleNamespace(config=executor.config, platform=platform, runtime=executor, _guard=Lock(), _apps={})
    monkeypatch.setattr(api, "executor", lambda: service)

    async def authorized(request):
        return None

    monkeypatch.setattr(api, "authorized", authorized)
    monkeypatch.setattr(api, "DataExecutor", lambda *args: pytest.fail("K8s initialized Docker data worker"))
    header = base64.urlsafe_b64encode(json.dumps(op["data_grant"]).encode())
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/v2/apps/app-a/db/tables",
        "path_params": {"app_id": "app-a"},
        "headers": [(b"x-runtime-data-grant", header)],
    }
    context = api.scoped_data(Request(scope))
    worker = await anext(context)
    try:
        assert worker.call("app-a", "tables", {})["tables"] == []
    finally:
        await context.aclose()
    missing = api.scoped_data(Request({**scope, "headers": []}))
    with pytest.raises(DataBusyError):
        await anext(missing)


def test_unknown_online_action_keeps_the_mutex_until_old_grants_expire(runtime):
    driver, _, platform, _, op, _, requests, _ = ready_session(runtime, online=True)
    clock = driver.runtime.clock
    platform.operations[op["operation_id"]]["payload"].update(
        data_action_finished="unknown", data_grant_not_after=clock.time() + 5
    )
    count = len(requests)
    assert driver.cleanup_session(op)["complete"] is False
    assert len(requests) == count
    clock.sleep(6)
    assert driver.cleanup_session(op)["complete"] is True


def test_data_error_codes_keep_the_existing_public_semantics(runtime):
    from runtime_manager.errors import DatabaseNotFoundError

    driver, _, _, _, op, _, _, _ = ready_session(runtime)
    driver.http.close()
    driver.http = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                404, json={"error": {"code": "db_not_found", "message": "private database path"}, "status_code": 404}
            )
        ),
        trust_env=False,
    )
    with pytest.raises(DatabaseNotFoundError) as caught:
        driver.request(op, "tables", {})
    assert "private database path" not in str(caught.value.detail)


def test_json_response_limit_stops_streaming_before_full_materialization(runtime):
    driver, _, _, _, op, _, _, _ = ready_session(runtime)
    consumed = []

    class Oversized(httpx.SyncByteStream):
        def __iter__(self):
            for index in range(40):
                consumed.append(index)
                yield b"x" * 1024**2

    driver.http.close()
    driver.http = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Oversized())), trust_env=False
    )
    with pytest.raises(DataBusyError):
        driver.request(op, "tables", {})
    assert len(consumed) <= 18


def test_export_is_streamed_to_a_short_cache_and_verified(runtime):
    import shutil

    driver, _, platform, _, op, _, _, _ = ready_session(runtime)
    params = {"table": "items"}
    digest = hashlib.sha256(json.dumps(params, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    op["payload"].update(action="export", parameters_digest=digest)
    platform.operations[op["operation_id"]]["payload"].update(action="export", parameters_digest=digest)
    op["data_grant"]["claims"].update(action="export", parameters_sha256=digest)
    content = b"id,name\n1,fixture\n"
    driver.http.close()
    driver.http = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                content=content,
                headers={"content-length": str(len(content)), "x-content-sha256": hashlib.sha256(content).hexdigest()},
            )
        ),
        trust_env=False,
    )
    path, root = driver.request(op, "export", params)
    try:
        assert path.read_bytes() == content and path.is_relative_to(root)
    finally:
        shutil.rmtree(root)


def test_absolute_deadline_with_timezone_offset_cannot_extend_a_data_session(runtime):
    from datetime import datetime, timedelta, timezone

    driver, _, platform, _, op, _, _, _ = ready_session(runtime)
    clock = driver.runtime.clock
    deadline = datetime.fromtimestamp(clock.time() + 60, timezone(timedelta(hours=8))).isoformat()
    platform.operations[op["operation_id"]]["deadline"] = deadline
    op["deadline"] = deadline
    clock.sleep(61)
    with pytest.raises(DataBusyError):
        driver.request(op, "tables", {})


async def test_owner_grant_cannot_redirect_the_manager_operation_lookup(runtime, monkeypatch):
    from runtime_manager.api import platform_data as api

    _, executor, platform, _, op, _, _, _ = ready_session(runtime, online=True)
    service = SimpleNamespace(config=executor.config, platform=platform, runtime=executor)
    monkeypatch.setattr(api, "executor", lambda: service)

    async def authorized(request):
        return None

    monkeypatch.setattr(api, "authorized", authorized)
    monkeypatch.setattr(platform, "operation", lambda value: pytest.fail("invalid lookup reached backend"))
    ticket = copy.deepcopy(op["data_grant"])
    ticket["claims"]["operation_id"] = "../outside"
    header = base64.urlsafe_b64encode(json.dumps(ticket).encode())
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/v2/apps/app-a/db/tables",
        "path_params": {"app_id": "app-a"},
        "headers": [(b"x-runtime-data-grant", header)],
    }
    context = api.scoped_data(Request(scope))
    with pytest.raises(DataBusyError):
        await anext(context)


def test_lost_export_response_cleanup_reclaims_only_old_short_caches(runtime, tmp_path):
    import os

    driver, _, _, _, _, _, _, _ = ready_session(runtime)
    driver.cache_root = tmp_path / "exports"
    old, recent = driver.cache_root / "export-fixture-old", driver.cache_root / "export-fixture-new"
    old.mkdir(parents=True)
    recent.mkdir()
    (old / "export.csv").write_text("old export")
    (recent / "export.csv").write_text("active export")
    database = tmp_path / "business/app.db"
    database.parent.mkdir()
    database.write_bytes(b"database")
    now = driver.runtime.clock.time()
    os.utime(old, (now - 1000, now - 1000))
    os.utime(recent, (now, now))
    driver.cleanup_exports()
    assert not old.exists() and recent.exists()
    assert database.read_bytes() == b"database"
