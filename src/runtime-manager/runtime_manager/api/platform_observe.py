"""Runtime observation queries use the platform assignment, never local desired state."""

import asyncio

from fastapi import APIRouter, Depends

from runtime_manager.api.operations import authorized, executor
from runtime_manager.api.readonly import _parse_since
from runtime_manager.container_runner import OP_LABEL, redact
from runtime_manager.errors import NotFoundError

router = APIRouter(prefix="/v2", dependencies=[Depends(authorized)])


def record(app_id):
    service = executor()
    scope = service.platform.application(app_id)
    ref = scope.get("exec_ref")
    if not ref:
        raise NotFoundError("No registered application execution")
    data = service.docker.inspect_container(ref)
    labels = data.get("Config", {}).get("Labels", {})
    if labels.get("bisheng.runtime.node") != service.config.node_id or labels.get(OP_LABEL) != scope["operation_id"]:
        raise NotFoundError("Execution assignment mismatch")
    return service, scope, data


@router.get("/apps/{app_id}/status")
async def status(app_id: str):
    _service, scope, data = await asyncio.to_thread(record, app_id)
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
    text = await asyncio.to_thread(
        service.docker.container_logs, scope["exec_ref"], tail=min(max(tail, 1), 1000), since=_parse_since(since)
    )
    # Runtime tokens are not printed by this service. Bound log output even for a malicious app.
    env = dict(item.split("=", 1) for item in _data.get("Config", {}).get("Env", []) if "=" in item)
    text = redact(text, env)
    lines = text[-1024 * 1024 :].splitlines()
    if keyword:
        lines = [line for line in lines if keyword.lower() in line.lower()]
    return {"lines": lines, "app_id": app_id}


def runtime_snapshot():
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
        ledger = service.platform.node_plan()["capacity"]
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
