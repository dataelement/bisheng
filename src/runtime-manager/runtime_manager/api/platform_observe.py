"""Runtime observation queries use the platform assignment, never local desired state."""

import asyncio

from fastapi import APIRouter, Depends

from runtime_manager.api.operations import authorized, executor
from runtime_manager.api.readonly import _parse_since
from runtime_manager.container_runner import OP_LABEL, redact
from runtime_manager.errors import NotFoundError
from runtime_manager.platform_client import PlatformError

router = APIRouter(prefix="/v2", dependencies=[Depends(authorized)])


def record(app_id):
    service = executor()
    try:
        scope = service.platform.application(app_id)
    except PlatformError as exc:
        # Only the application's missing assignment means no execution. A
        # resource lookup failure or unavailable platform must remain an error.
        if exc.status == 404 and str(exc) == "application_not_found":
            raise NotFoundError("No registered application execution") from None
        raise
    ref = scope.get("exec_ref")
    if not ref:
        raise NotFoundError("No registered application execution")
    if service.config.executor_kind == "kubernetes":
        row = service.platform.resource(ref)
        if (row.get("app_id"), row.get("node_id"), row.get("operation_id"), row.get("kind")) != (
            app_id,
            service.config.node_id,
            scope.get("operation_id"),
            "Pod",
        ) or not row.get("uid"):
            raise NotFoundError("Execution assignment mismatch")
        return service, scope, {"observation": service.runtime.observe(ref)}
    data = service.docker.inspect_container(ref)
    labels = data.get("Config", {}).get("Labels", {})
    if labels.get("bisheng.runtime.node") != service.config.node_id or labels.get(OP_LABEL) != scope["operation_id"]:
        raise NotFoundError("Execution assignment mismatch")
    return service, scope, data


@router.get("/apps/{app_id}/status")
async def status(app_id: str):
    _service, scope, data = await asyncio.to_thread(record, app_id)
    if "observation" in data:
        observation = data["observation"]
        return {
            "app_id": app_id,
            "phase": "running" if observation.get("ready") else "unhealthy",
            "generation": scope["generation"],
            "instance_id": scope["exec_ref"],
            "health": "healthy" if observation.get("ready") else "unhealthy",
            "restart_count": observation.get("restart_count", 0),
        }
    state = data.get("State", {})
    return {
        "app_id": app_id,
        "phase": "running" if state.get("Running") else "unhealthy",
        "generation": scope["generation"],
        "instance_id": scope["exec_ref"],
        "health": state.get("Health", {}).get("Status"),
        "restart_count": data.get("RestartCount", 0),
    }


@router.get("/apps/{app_id}/logs")
async def logs(app_id: str, tail: int = 100, since: str | None = None, keyword: str | None = None):
    service, scope, _data = await asyncio.to_thread(record, app_id)
    bounded_tail = min(max(tail, 1), 1000)
    parsed_since = _parse_since(since)
    operation = await asyncio.to_thread(service.platform.operation, scope["operation_id"])
    if service.config.executor_kind == "kubernetes":
        text = await asyncio.to_thread(service.runtime.logs, scope["exec_ref"], tail=bounded_tail, since=parsed_since)
        env = operation.get("payload", {}).get("runtime_env", {})
    else:
        text = await asyncio.to_thread(
            service.docker.container_logs, scope["exec_ref"], tail=bounded_tail, since=parsed_since
        )
        env = dict(item.split("=", 1) for item in _data.get("Config", {}).get("Env", []) if "=" in item)
    # Only the application's own output is read; helper identities are never logged.
    text = redact(text, env, operation.get("payload", {}).get("sensitive_env_names", []))
    lines = text[-1024 * 1024 :].splitlines()
    if keyword:
        lines = [line for line in lines if keyword.lower() in line.lower()]
    return {"lines": lines, "app_id": app_id}


def _docker_snapshot():
    from runtime_manager.api.readonly import _data_root_writable, _host_data_root_check
    from runtime_manager.egress import egress_preflight

    service = executor()
    checks = []
    info = {}
    capacity = {
        "readable": False,
        "mem_available_mb": 0,
        "committed_mb": 0,
        "total_mb": 0,
        "cpu": 0,
        "committed_cpu": 0,
        "instances": 0,
        "reserve_mb": service.config.reserve_mb,
        "overcommit_ratio": service.config.overcommit_ratio,
    }
    try:
        info = service.docker.info()
        available = True
    except Exception:
        available = False
    checks.append(
        {
            "name": "orchestration_backend",
            "ok": available,
            "detail": "reachable" if available else "Engine API unavailable",
        }
    )
    try:
        ledger = service.platform.node_snapshot()["capacity"]
        capacity.update(
            readable=True,
            mem_available_mb=max(0, ledger["memory_budget_mb"] - ledger["committed_mb"]),
            total_mb=int(info.get("MemTotal", 0)) // 1024 // 1024,
            cpu=int(info.get("NCPU", 0)),
            committed_mb=ledger["committed_mb"],
            committed_cpu=ledger["committed_cpu"],
            instances=ledger["instances"],
        )
        checks.append({"name": "platform_ledger", "ok": True, "detail": "authoritative capacity available"})
    except Exception:
        checks.append(
            {"name": "platform_ledger", "ok": False, "detail": "platform API unavailable; no local capacity fallback"}
        )
    writable, detail = _data_root_writable(service.config)
    checks.append({"name": "data_root_writable", "ok": writable, "detail": detail})
    checks.append(_host_data_root_check(service.config))
    checks.extend(egress_preflight(service.config, service.docker if available else None))
    checks.append(
        {
            "name": "storage_configured",
            "ok": bool(service.config.platform_base_url),
            "detail": "files use backend; check object storage on backend",
        }
    )
    return {
        "backend_available": available,
        "supported_runtimes": ["python3.11", "node20", "static"],
        "capacity": capacity,
        "preflight": checks,
        "protocol_version": 2,
        "node_id": service.config.node_id,
    }


@router.get("/runtime/status")
async def runtime_status():
    return await asyncio.to_thread(runtime_snapshot)


def runtime_snapshot():
    service = executor()
    if service.config.executor_kind == "docker":
        return _docker_snapshot()
    checks = []
    capacity = {
        "readable": False,
        "mem_available_mb": 0,
        "committed_mb": 0,
        "total_mb": 0,
        "cpu": 0,
        "committed_cpu": 0,
        "instances": 0,
        "reserve_mb": 0,
        "overcommit_ratio": 1.0,
    }
    capabilities = service.runtime.capabilities()
    probe = service.runtime.probe_report()
    available = capabilities.get("orchestration_available") is True
    checks.append(
        {
            "name": "orchestration_backend",
            "ok": available,
            "detail": "reachable" if available else "cluster API unavailable",
        }
    )
    prerequisites = (
        available
        and bool(probe.get("ready"))
        and all(
            capabilities.get(key) is True for key in ("mandatory_isolation", "status_protection", "binding_protection")
        )
    )
    checks.append(
        {
            "name": "runtime_prerequisites",
            "ok": prerequisites,
            "detail": "verified" if prerequisites else "required isolation or protection unavailable",
        }
    )
    try:
        snapshot = service.platform.node_snapshot()
        ledger = snapshot["capacity"]
        capacity.update(
            readable=True,
            mem_available_mb=max(0, ledger["memory_budget_mb"] - ledger["committed_mb"]),
            total_mb=ledger["memory_budget_mb"],
            cpu=service.runtime.descriptor.cpu_budget_millicores / 1000,
            committed_mb=ledger["committed_mb"],
            committed_cpu=ledger["committed_cpu"],
            instances=ledger["instances"],
        )
        checks.append({"name": "platform_ledger", "ok": True, "detail": "authoritative capacity available"})
        ready = prerequisites and snapshot.get("node", {}).get("status") == "ready"
    except Exception:
        checks.append(
            {"name": "platform_ledger", "ok": False, "detail": "platform API unavailable; no local capacity fallback"}
        )
        ready = False
    checks.append(
        {
            "name": "storage_backend",
            "ok": bool(service.runtime.document.get("storage", {}).get("sqlite_compatible")),
            "detail": "installer-verified SQLite filesystem required",
        }
    )
    ready = ready and all(check["ok"] for check in checks)
    return {
        "backend_available": available,
        "ready": ready,
        "executor_kind": "kubernetes",
        "supported_runtimes": ["python3.11", "node20", "static"],
        "capacity": capacity,
        "preflight": checks,
        "protocol_version": 2,
        "node_id": service.config.node_id,
    }


@router.get("/runtime/capabilities")
async def runtime_capabilities():
    service = executor()
    snapshot = await asyncio.to_thread(runtime_snapshot)
    return {
        "capabilities": service.runtime.capabilities(),
        "ready": snapshot.get("ready", snapshot["backend_available"]),
        "preflight": snapshot["preflight"],
        "executor_kind": service.config.executor_kind,
    }
