"""Owner-authorized data sessions; execution effects remain behind manager RPC.

A session shares the serving generation and holds a separate durable mutex.
No transaction stays open while waking, waiting for, or calling the manager.
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta
from urllib.parse import quote
from uuid import uuid4

import httpx
from loguru import logger

from bisheng.app_runtime.domain.models.runtime_delivery import (
    RuntimeAssignment,
    RuntimeNode,
    RuntimeOperation,
    RuntimeRoute,
)
from bisheng.app_runtime.domain.models.runtime_kubernetes import RuntimeExecutionResource
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import (
    TERMINAL,
    RuntimeConflict,
    RuntimeDeliveryRepository,
)
from bisheng.app_runtime.domain.services.orchestrator_client import OrchestratorClient
from bisheng.app_runtime.domain.services.runtime_control_client import RuntimeControlClient
from bisheng.app_runtime.domain.services.runtime_operation_service import RuntimeOperationService
from bisheng.app_runtime.domain.services.runtime_protocol import canonical_json, content_digest, signed_headers
from bisheng.common.errcode.app_factory import (
    AppDataBusyError,
    AppDataInvalidError,
    AppDataNotReadyError,
    AppOrchestratorUnavailableError,
)
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.services.config_service import settings


class _DataTransport:
    async def call(self, app_id, action, parameters, ticket, *, timeout):
        cfg = settings.app_runtime
        prefix = "/v2/apps/" + quote(app_id, safe="") + "/db"
        table = quote(parameters.get("table", ""), safe="")
        paths = {
            "tables": "/tables",
            "schema": f"/tables/{table}/schema",
            "rows": f"/tables/{table}/rows",
            "update": f"/tables/{table}/rows/" + quote(str(parameters.get("key", "")), safe=""),
            "export": "/export",
        }
        if action not in paths:
            raise AppDataInvalidError(reason="data_action_refused")
        method = "PATCH" if action == "update" else "GET"
        query = (
            {key: parameters[key] for key in ("page", "size", "order") if parameters.get(key) is not None}
            if action == "rows"
            else ({"table": parameters["table"]} if action == "export" else {})
        )
        raw = canonical_json({"values": parameters["values"]}) if action == "update" else b""
        request = httpx.Request(method, cfg.manager_base_url.rstrip("/") + prefix + paths[action], params=query)
        headers = signed_headers(
            method, str(request.url), raw, key_id=cfg.runtime_control_key_id, secret=cfg.runtime_control_secret
        )
        headers["X-Runtime-Data-Grant"] = base64.urlsafe_b64encode(canonical_json(ticket)).decode("ascii")
        if raw:
            headers["Content-Type"] = "application/json"
        async with httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, request.url, content=raw, headers=headers)
        if response.status_code == 409:
            try:
                document = response.json()
            except ValueError:
                document = {}
            if document.get("state") == "unknown":
                raise AppDataBusyError(reason="data_result_unknown", request_id=ticket["claims"]["request_id"])
        return OrchestratorClient._unwrap(response, op="db_" + action, as_bytes=action == "export")


class RuntimeDataSessionService:
    def __init__(
        self, repository=None, *, control=None, issuer=None, transport=None, clock=datetime.utcnow, sleep=asyncio.sleep
    ):
        self.repo = repository or RuntimeDeliveryRepository()
        self.control = control or RuntimeControlClient()
        self.issuer, self.transport = issuer, transport or _DataTransport()
        self.clock, self.sleep = clock, sleep

    async def _owner(self, app):
        assignments = await self.repo.find(RuntimeAssignment, app_id=app.id)
        owner = assignments[0] if assignments else None
        node_id = owner.node_id if owner else settings.app_runtime.runtime_default_node_id
        return owner, await self.repo.get(RuntimeNode, node_id) if node_id else None

    async def supports(self, app):
        _, node = await self._owner(app)
        return bool(node and node.executor_kind == "kubernetes")

    @staticmethod
    def _parameters(action, parameters):
        allowed = {
            "tables": set(),
            "schema": {"table"},
            "rows": {"table", "page", "size", "order"},
            "update": {"table", "key", "values"},
            "export": {"table"},
        }
        if action not in allowed or not isinstance(parameters, dict) or set(parameters) - allowed[action]:
            raise AppDataInvalidError(reason="data_parameters_invalid")
        result = dict(parameters)
        if action == "rows":
            result.update(page=result.get("page") or 1, size=result.get("size") or 50, order=result.get("order"))
        if action == "update":
            result["key"] = str(result["key"])
        # This rejects non-finite/non-JSON values before any session or grant.
        try:
            content_digest(result)
        except (ValueError, TypeError):
            raise AppDataInvalidError(reason="data_parameters_invalid") from None
        return result

    async def _start(self, app, actor, action, parameters):
        owner, node = await self._owner(app)
        if owner is None or node is None or node.executor_kind != "kubernetes":
            raise AppDataNotReadyError(app_id=app.id)
        volumes = await self.repo.find(RuntimeExecutionResource, app_id=app.id, kind="PersistentVolumeClaim")
        if not any(
            row.node_id == node.id
            and row.uid
            and row.cleanup_state != "complete"
            and row.purpose in {"serve", "migrate", "restore", "data"}
            for row in volumes
        ):
            raise AppDataNotReadyError(app_id=app.id)
        routes = await self.repo.find(RuntimeRoute, route_key="app:" + app.id)
        route = routes[0] if routes else None
        if route and route.status == "maintenance":
            raise AppDataBusyError(reason="application_under_maintenance")
        online = bool(route and route.status == "serving")
        target = None
        if online:
            target = await self.repo.get(RuntimeExecutionResource, route.exec_ref)
            if (
                target is None
                or not target.uid
                or target.stop_requested_at is not None
                or (target.app_id, target.node_id, target.kind, target.purpose) != (app.id, node.id, "Pod", "serve")
            ):
                raise AppDataBusyError(reason="data_helper_execution_unconfirmed")
        request_id = str(uuid4())
        profile = {"uid": 10001, "gid": 10001, "platform": node.platform}
        if route:
            serving = await self.repo.get(RuntimeOperation, route.operation_id)
            if serving:
                profile.update(serving.payload.get("resolved_delivery", {}).get("profile", {}))
        helper = (node.capabilities or {}).get("helper_image", "")
        payload = {
            "tenant_id": app.tenant_id,
            "request_id": request_id,
            "actor_ref": "user:" + str(actor.user_id),
            "action": action,
            "parameters_digest": content_digest(parameters),
            "online": online,
            "target_exec_ref": target.id if target else "",
            "target_pod_uid": target.uid if target else "",
            "tier": {"memory_mb": 128, "cpu_millicores": 25},
            "resolved_delivery": {
                "mode": "image",
                "image_ref": helper,
                "platform": node.platform,
                "profile": profile,
                "startup": {},
            },
        }
        op = RuntimeOperation(
            tenant_id=app.tenant_id,
            app_id=app.id,
            scope_key=f"{app.tenant_id}/{app.id}",
            idempotency_key="data:" + request_id,
            request_digest=content_digest(
                {"action": action, "parameters": parameters, "actor_ref": payload["actor_ref"]}
            ),
            kind="data",
            node_id=node.id,
            generation=owner.generation,
            owner_epoch=owner.owner_epoch,
            deadline=self.clock() + timedelta(seconds=60),
            payload=payload,
        )
        try:
            return await self.repo.acquire_data_operation(op, offline=not online)
        except RuntimeConflict as exc:
            raise AppDataBusyError(reason=str(exc)) from exc

    async def _wake(self, operation_id):
        try:
            await self.control.wakeup(operation_id)
        except (httpx.HTTPError, AppOrchestratorUnavailableError) as exc:
            # Node polling finds the committed session. Never replay the data action.
            logger.warning("data session wakeup unavailable ({})", type(exc).__name__)

    async def _ready(self, op):
        while True:
            current = await self.repo.get(RuntimeOperation, op.id)
            if current is None or self.clock() >= current.deadline or current.status in TERMINAL:
                raise AppDataBusyError(reason="data_session_not_ready", request_id=op.payload["request_id"])
            if current.stage == "ready":
                document = await RuntimeOperationService(self.repo).describe(current)
                target = document.get("result", {}).get("data_target")
                if isinstance(target, dict) and target.get("exec_ref") and target.get("pod_uid"):
                    return current, target
                raise AppDataBusyError(reason="data_target_unconfirmed")
            await self.sleep(min(0.1, max(0, (current.deadline - self.clock()).total_seconds())))

    async def _finish(self, operation, state):
        async with self.repo.transaction():
            current = await self.repo.get(RuntimeOperation, operation.id, lock=True)
            current.payload = {**current.payload, "data_action_finished": state}
            await self.repo.save(current)
        await self._wake(operation.id)

    async def execute(self, app, actor, action, parameters):
        from bisheng.app_runtime.domain.services.app_data_service import AppDataService

        AppDataService._require_owner(app, actor)
        parameters = self._parameters(action, parameters)
        op = await self._start(app, actor, action, parameters)
        await self._wake(op.id)
        try:
            current, target = await self._ready(op)
            issuer = self.issuer
            if issuer is None:
                from bisheng.app_runtime.domain.services.runtime_data_grant_service import RuntimeDataGrantService

                issuer = RuntimeDataGrantService(self.repo)
            ticket = await issuer.issue(app, actor, current, target, action, parameters)
            remaining = (current.deadline - self.clock()).total_seconds()
            if remaining <= 0:
                raise AppDataBusyError(reason="data_session_expired")
            result = await self.transport.call(app.id, action, parameters, ticket, timeout=remaining)
        except httpx.HTTPError as exc:
            await self._finish(op, "unknown")
            logger.warning("data action result unknown ({})", type(exc).__name__)
            raise AppDataBusyError(reason="data_result_unknown", request_id=op.payload["request_id"]) from exc
        except BaseErrorCode as exc:
            await self._finish(op, "unknown" if exc.kwargs.get("reason") == "data_result_unknown" else "failed")
            raise
        await self._finish(op, "done")
        while True:
            current = await self.repo.get(RuntimeOperation, op.id)
            if current.status in TERMINAL and current.cleanup_status == "complete":
                return result
            if self.clock() >= current.deadline:
                raise AppDataBusyError(reason="data_cleanup_pending", request_id=op.payload["request_id"])
            await self.sleep(min(0.1, (current.deadline - self.clock()).total_seconds()))
