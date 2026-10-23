"""覆盖 AC: AC-33、AC-35、AC-46、AC-49、AC-50、AC-52.

Run the real operation/data/maintenance chain through PlatformClient.fact and
FastAPI validation of the actual backend schema. Only control persistence and
Kubernetes I/O use doubles; the purge itself executes against a private volume.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from runtime_manager.executors.kubernetes import KubernetesExecutor
from runtime_manager.k8s_appdb import run_maintenance
from runtime_manager.k8s_data_executor import KubernetesDataExecutor
from runtime_manager.operations import OperationExecutor
from runtime_manager.platform_client import PREFIX, PlatformClient, PlatformError
from tests.test_kubernetes_executor import runtime as runtime

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "backend/bisheng/app_runtime/domain/schemas/runtime_delivery.py"
_SCHEMA_SPEC = importlib.util.spec_from_file_location("_f059_real_backend_delivery_schema", _SCHEMA_PATH)
_SCHEMA = importlib.util.module_from_spec(_SCHEMA_SPEC)
sys.modules[_SCHEMA_SPEC.name] = _SCHEMA
_SCHEMA_SPEC.loader.exec_module(_SCHEMA)
ExecutionFactInput = _SCHEMA.ExecutionFactInput


class ManagerCrash(BaseException):
    """A lost process cannot run the executor's normal exception cleanup."""


class FactBoundary:
    """The actual wire encoder and schema; no duplicated phase enumeration."""

    def __init__(self, platform, config, events):
        self.platform, self.events = platform, events
        self.fault = self.target = None
        self.after_commit = None
        self.fired = False
        self.accepted = []
        self.responses = []
        self.persist = platform.fact
        api = FastAPI()

        @api.post(PREFIX + "/operations/{operation_id}/facts")
        def fact(operation_id: str, body: ExecutionFactInput):
            document = body.model_dump(mode="json")
            progress = document["detail"].get("maintenance_progress", {}).get("purge")
            is_target = self.matches(document, progress)
            if is_target and self.fault == "reject":
                self.fired = True
                return JSONResponse({"error": {"reason": "fixture_fact_unavailable"}}, status_code=503)
            operation = platform.operation(operation_id)
            self.persist(
                operation, body.sequence, body.phase, exec_ref=body.exec_ref, detail=copy.deepcopy(body.detail)
            )
            # Project only acknowledged validated facts for later real executor reads.
            current = platform.operations[operation_id]
            current["stage"] = body.phase
            if body.phase in {"completed", "failed", "cancelled", "timed_out"}:
                current["status"] = body.phase
                current["cleanup_status"] = "complete" if body.detail.get("cleanup_complete") else "pending"
                current["failure"] = {} if body.phase == "completed" else copy.deepcopy(body.detail)
            self.accepted.append(copy.deepcopy(document))
            self.events.append(("fact-committed", body.phase, bool(progress)))
            if self.after_commit is not None:
                self.after_commit(document)
            return {"operation_id": operation_id, "phase": body.phase, "sequence": body.sequence}

        self.api = TestClient(api)
        self.client = PlatformClient(config, transport=httpx.MockTransport(self.send))
        platform.fact = self.client.fact

    def matches(self, document, progress):
        return not self.fired and (
            (self.target == "maintenance" and document["phase"] == "maintenance" and not progress)
            or (self.target == "result" and progress)
            or (self.target == "completed" and document["phase"] == "completed")
        )

    def send(self, request):
        document = json.loads(request.content)
        progress = document["detail"].get("maintenance_progress", {}).get("purge")
        selected = self.matches(document, progress)
        if selected and self.fault in {"lost-before-commit", "crash-before-commit"}:
            self.fired = True
            if self.fault == "crash-before-commit":
                raise ManagerCrash()
            raise httpx.ReadError("fixture_reply_unknown", request=request)
        response = self.api.request(request.method, request.url.path, content=request.content, headers=request.headers)
        self.responses.append((document["phase"], response.status_code))
        if selected and self.fault == "lost-after-commit":
            self.fired = True
            raise httpx.ReadError("fixture_reply_unknown", request=request)
        return httpx.Response(response.status_code, content=response.content)

    def close(self):
        self.client.close()
        self.api.close()


@pytest.fixture
def destroy(runtime, tmp_path):
    kube, platform, cluster, original, events, clock = runtime
    # The existing stopped application's stable volume belongs to its old deploy.
    plan = kube._plan(original, "serve")
    kube._volume(original, plan)
    original.update(status="completed", stage="completed", cleanup_status="complete")
    operation = {
        **copy.deepcopy(original),
        "operation_id": uuid4().hex,
        "generation": original["generation"] + 1,
        "kind": "destroy",
        "version_id": "",
        "status": "pending",
        "stage": "admitted",
        "fact_sequence": 0,
        "cleanup_status": "pending",
        "result": {},
        "payload": {"purge_volume": True},
    }
    platform.operations[operation["operation_id"]] = operation
    platform.claim = lambda ident: platform.operations[ident].update(status="running")
    platform.application = lambda app: {"app_id": app, "node_id": original["node_id"], "exec_ref": None}
    boundary = FactBoundary(platform, kube.config, events)
    volume = tmp_path / "production-volume"
    (volume / "business").mkdir(parents=True)
    database = volume / "business/app.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO items VALUES(1, 'retained-until-owner-purge')")
    backups = volume / "platform/protected-backups"
    backups.mkdir(parents=True)
    (backups / "previous.sqlite").write_bytes(b"private-backup-fixture")
    create = cluster.create
    helper_runs = []

    def finished(kind, template):
        obj = create(kind, template)
        if kind == "pods":
            events.append(("purge-pod-create", platform.operation(operation["operation_id"])["stage"]))
            stored = cluster.objects[kind, template["metadata"]["name"]]
            stored["status"]["phase"] = "Succeeded"
            for container in stored["status"]["containerStatuses"]:
                container["state"] = {"terminated": {"exitCode": 0}}
        return obj

    def logs(name, **kwargs):
        pod = cluster.objects["pods", name]
        container = pod["spec"]["containers"][0]
        document = json.loads(next(row["value"] for row in container["env"] if row["name"] == "MATERIAL_PLAN"))
        assert container["name"] == "maintenance" and document["action"] == "purge"
        helper_runs.append(document["operation"]["operation_id"])
        return "BISHENG_RUNTIME_RESULT " + json.dumps(run_maintenance(document, None, volume=volume))

    cluster.create, cluster.logs = finished, logs
    executors, transports = [], []

    def manager(*, fresh=False):
        selected = kube
        if fresh:
            clock.sleep(31)  # The old process's controller lease expires naturally.
            selected = KubernetesExecutor(kube.config, kube.settings, platform=platform, client=cluster, clock=clock)
        data = KubernetesDataExecutor(selected)
        selected.data_transport = data
        transports.append(data)
        worker = OperationExecutor(kube.config, platform=platform, runtime=selected, clock=clock)
        executors.append(worker)
        return worker

    value = SimpleNamespace(
        kube=kube,
        platform=platform,
        cluster=cluster,
        operation=operation,
        events=events,
        boundary=boundary,
        manager=manager,
        helper_runs=helper_runs,
        database=database,
        backups=backups,
        volume=volume,
    )
    yield value
    for worker in executors:
        worker.close()
    for transport in transports:
        transport.close()
    boundary.close()


def pvc_deletes(case):
    return [row for row in case.events if row[:2] == ("delete", "persistentvolumeclaims")]


def assert_completed(case):
    operation = case.platform.operation(case.operation["operation_id"])
    assert operation["status"] == operation["stage"] == "completed"
    assert operation["cleanup_status"] == "complete"
    assert operation["result"]["maintenance_progress"]["purge"]["result"] == {"purged": True}
    assert all(status == 200 for _, status in case.boundary.responses)
    assert len(case.helper_runs) == len(pvc_deletes(case)) == 1
    assert not case.database.exists() and not case.backups.exists()
    assert not any(kind in {"pods", "persistentvolumeclaims"} for kind, _ in case.cluster.objects)


def test_admitted_destroy_uses_real_fact_schema_before_purge_and_ack_before_cleanup(destroy):
    destroy.manager().execute(destroy.operation["operation_id"])
    # Old code reaches this assertion with actual FastAPI422 for phase=admitted.
    assert ("admitted", 422) not in destroy.boundary.responses
    assert_completed(destroy)
    before = destroy.events.index(("fact-committed", "maintenance", False))
    pod = destroy.events.index(("purge-pod-create", "maintenance"))
    progress = destroy.events.index(("fact-committed", "maintenance", True))
    cleanup = next(i for i, row in enumerate(destroy.events) if row[0] == "stop")
    pvc = next(i for i, row in enumerate(destroy.events) if row[:2] == ("delete", "persistentvolumeclaims"))
    completed = destroy.events.index(("fact-committed", "completed", True))
    assert before < pod < progress < cleanup < pvc < completed


@pytest.mark.parametrize("phase", ["admitted", "stopping"])
def test_actual_backend_schema_rejects_internal_non_fact_stages(destroy, phase):
    current = destroy.platform.operation(destroy.operation["operation_id"])
    with pytest.raises(PlatformError) as refused:
        destroy.boundary.client.fact(current, 1, phase, detail={"controller": destroy.kube._controller()})
    assert refused.value.status == 422
    assert destroy.boundary.responses == [(phase, 422)]
    assert not destroy.boundary.accepted
    assert destroy.database.exists() and not pvc_deletes(destroy)


def test_actual_backend_schema_accepts_existing_maintenance_fact(destroy):
    current = destroy.platform.operation(destroy.operation["operation_id"])
    receipt = destroy.boundary.client.fact(current, 1, "maintenance", detail={"controller": destroy.kube._controller()})
    assert receipt["phase"] == "maintenance"
    assert destroy.boundary.responses == [("maintenance", 200)]
    assert destroy.platform.operation(current["operation_id"])["stage"] == "maintenance"
    assert destroy.database.exists() and not pvc_deletes(destroy)


@pytest.mark.parametrize("fault", ["reject", "lost-before-commit", "lost-after-commit"])
def test_unacknowledged_maintenance_fact_never_starts_purge_or_deletes_volume(destroy, fault):
    destroy.boundary.target, destroy.boundary.fault = "maintenance", fault
    destroy.manager().execute(destroy.operation["operation_id"])
    assert destroy.boundary.fired
    assert not destroy.helper_runs and not pvc_deletes(destroy)
    assert destroy.database.exists() and destroy.backups.exists()
    assert not any(row[0] == "purge-pod-create" for row in destroy.events)
    assert not any(row["phase"] == "completed" for row in destroy.boundary.accepted)


@pytest.mark.parametrize("change", ["cancel", "deadline", "owner-epoch"])
def test_fresh_checkpoint_after_maintenance_ack_prevents_purge(destroy, change):
    changed = []

    def after_commit(document):
        if changed or document["phase"] != "maintenance":
            return
        changed.append(change)
        current = destroy.platform.operations[destroy.operation["operation_id"]]
        if change == "cancel":
            current["cancel_requested"] = True
        elif change == "deadline":
            current["deadline"] = destroy.kube.clock.iso()
        else:
            current["owner_epoch"] += 1

    destroy.boundary.after_commit = after_commit
    destroy.manager().execute(destroy.operation["operation_id"])
    assert changed == [change]
    assert not destroy.helper_runs and not pvc_deletes(destroy)
    assert destroy.database.exists() and destroy.backups.exists()
    assert not any(row[0] == "purge-pod-create" for row in destroy.events)
    assert not any(row["phase"] == "completed" for row in destroy.boundary.accepted)


def test_rejected_purge_result_never_completes_or_removes_the_retained_pvc(destroy):
    destroy.boundary.target, destroy.boundary.fault = "result", "reject"
    destroy.manager().execute(destroy.operation["operation_id"])
    assert destroy.boundary.fired and len(destroy.helper_runs) == 1
    assert not pvc_deletes(destroy)
    assert any(kind == "persistentvolumeclaims" for kind, _ in destroy.cluster.objects)
    assert not any(row["phase"] == "completed" for row in destroy.boundary.accepted)
    assert not destroy.platform.operation(destroy.operation["operation_id"])["result"].get("maintenance_progress")


def test_lost_result_ack_uses_readback_of_the_same_committed_purge_result(destroy):
    destroy.boundary.target, destroy.boundary.fault = "result", "lost-after-commit"
    destroy.manager().execute(destroy.operation["operation_id"])
    assert destroy.boundary.fired
    assert_completed(destroy)
    progress = destroy.events.index(("fact-committed", "maintenance", True))
    cleanup = next(i for i, row in enumerate(destroy.events) if row[0] == "stop")
    assert progress < cleanup


@pytest.mark.parametrize("cut", ["before-finish", "before-completed-fact"])
def test_restart_uses_saved_progress_without_rerunning_purge_or_deleting_twice(destroy, monkeypatch, cut):
    request_stop = destroy.kube.request_stop
    if cut == "before-finish":

        def crash(reference, operation):
            raise ManagerCrash()

        monkeypatch.setattr(destroy.kube, "request_stop", crash)
    else:
        destroy.boundary.target, destroy.boundary.fault = "completed", "crash-before-commit"
    with pytest.raises(ManagerCrash):
        destroy.manager().execute(destroy.operation["operation_id"])
    current = destroy.platform.operation(destroy.operation["operation_id"])
    assert current["status"] == "running" and current["stage"] == "maintenance"
    assert current["result"]["maintenance_progress"]["purge"]["result"] == {"purged": True}
    assert len(destroy.helper_runs) == 1
    if cut == "before-finish":
        assert not pvc_deletes(destroy)
        monkeypatch.setattr(destroy.kube, "request_stop", request_stop)
    creates = len([row for row in destroy.events if row[0] == "purge-pod-create"])
    destroy.manager(fresh=True).execute(destroy.operation["operation_id"])
    assert_completed(destroy)
    assert len([row for row in destroy.events if row[0] == "purge-pod-create"]) == creates
    after = copy.deepcopy(destroy.events)
    destroy.manager(fresh=True).execute(destroy.operation["operation_id"])
    assert destroy.events == after  # A terminal operation has no further cleanup effects.
