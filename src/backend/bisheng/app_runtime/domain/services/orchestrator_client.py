"""Thin HMAC client for runtime-manager — backend's *only* way to orchestrate.

This module is the whole reason ``scripts/arch-guard.sh`` RULE-10 can exist:
backend declares **desired state** over HTTP and never touches an orchestration
backend itself (design K1 / D1). Nothing here knows what a container is; the
vocabulary is ``app_id`` / ``version_id`` / ``image_ref`` / ``tier`` / ``phase``,
so F059 can swap the manager's internals for k8s without this file changing
(INV-33).

Four facts that are easy to get wrong:

* **Sign the bytes you actually send.** The signing string is
  ``METHOD\\nPATH\\nraw_body`` and PATH excludes the query string
  (``contracts-runtime-manager.md`` §1). We serialise the body once and hand
  those same bytes to httpx via ``content=``; letting httpx re-serialise from
  ``json=`` produces a different byte string (separator whitespace) and every
  request fails signature verification for reasons that look like a wrong
  secret.
* **``unauthorized`` and ``invalid_request`` both become 16121**, not 401/400.
  They mean *our* signature was rejected or *we* sent an intent the manager
  could not parse — backend↔manager contract breakage, never something the
  end user did. Answering 401 upwards would make the platform look like it
  logged the caller out (contract §3, ``runtime_manager/errors.py`` docstring).
* **A failed build is a successful RPC.** ``build_status`` returns the payload
  including ``status="failed"``; it does not raise. The publish pipeline needs
  ``stage`` / ``message`` / ``tail`` to build its own failure copy (AC-15), and
  raising here would throw that away. Use :func:`build_failure_error` when a
  caller does want the 16122 shape.
* **Retry only what is safe to repeat.** A connect failure means the peer never
  saw the request, so the attempt is replayed. A read timeout on a write intent
  is *not* replayed — deploy/stop/destroy may already be running, and a second
  deploy would race the first through the manager's readiness gate.

Empty secret is fail-closed (16121), never "unsigned mode": a rollout that
forgot the secret would otherwise hand orchestration to anything that can
reach the manager's port.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from urllib.parse import quote, unquote

import httpx
from loguru import logger

from bisheng.common.errcode.app_factory import (
    AppBuildFailedError,
    AppCapacityInsufficientError,
    AppDataBusyError,
    AppDataInvalidError,
    AppDataNotReadyError,
    AppDataRowNotFoundError,
    AppDataTableNotFoundError,
    AppNotFoundError,
    AppOrchestratorUnavailableError,
    AppProbeFailedError,
    AppRuntimeNotSupportedError,
)
from bisheng.common.services.config_service import settings

#: Manager ``detail.code`` → platform error class (contract §3). ``unauthorized``
#: and ``invalid_request`` fold into the orchestrator-unavailable answer on
#: purpose — see the module docstring. The five ``db_*`` / ``data_*`` codes are
#: the data plane's own (contract §2 data-plane rows): a table that does not
#: exist must not read as "the orchestrator is unavailable".
_ERROR_BY_MANAGER_CODE: dict[str, type] = {
    "backend_unavailable": AppOrchestratorUnavailableError,
    "unauthorized": AppOrchestratorUnavailableError,
    "invalid_request": AppOrchestratorUnavailableError,
    "unsupported_runtime": AppRuntimeNotSupportedError,
    "capacity_exhausted": AppCapacityInsufficientError,
    "probe_failed": AppProbeFailedError,
    "not_found": AppNotFoundError,
    "db_not_found": AppDataNotReadyError,
    "table_not_found": AppDataTableNotFoundError,
    "row_not_found": AppDataRowNotFoundError,
    "data_invalid": AppDataInvalidError,
    "data_busy": AppDataBusyError,
}

#: Per-call read budgets in seconds. ``deploy`` and ``probe`` block on the
#: manager's readiness gate (D4: rebuild + probe ≤ 90 s), so a shared 15 s
#: timeout would turn every cold start into a false "orchestrator unavailable".
#: ``db_export`` streams a whole table, which is bounded by disk, not by us.
_TIMEOUTS: dict[str, float] = {
    "deploy": 300.0,
    "probe": 300.0,
    # A preview goes through the same readiness gate as a deploy, so it gets
    # the same budget; a shared 15 s one would turn every cold start into a
    # false "orchestrator unavailable".
    "preview_start": 300.0,
    "preview_stop": 120.0,
    "stop": 120.0,
    "destroy": 120.0,
    "build": 60.0,
    "db_export": 120.0,
}
_DEFAULT_TIMEOUT = 15.0

#: Attempts for an idempotent call (the first one plus one replay).
_MAX_ATTEMPTS = 2


def compute_signature(method: str, path: str, raw_body: bytes, secret: str) -> str:
    """Canonical HMAC-SHA256 hex digest — byte-identical to the manager's."""
    msg = f"{method.upper()}\n{path}\n".encode() + (raw_body or b"")
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def build_failure_error(payload: dict[str, Any]) -> AppBuildFailedError:
    """16122 from a ``build_status`` payload whose ``status`` is ``failed``.

    A free function rather than a client method: the facade's public surface is
    exactly the seventeen RPC methods (the test fixtures assert that set), and this
    is a translation of an already-fetched answer, not another RPC.
    """
    return AppBuildFailedError(
        msg=str(payload.get("message") or AppBuildFailedError.Msg),
        stage=payload.get("stage"),
        tail=payload.get("tail"),
    )


class OrchestratorClient:
    """One method per manager endpoint, and nothing else.

    Stateless apart from a lazily built ``httpx.AsyncClient``; configuration is
    read per call from ``settings.app_runtime`` so a config reload takes effect
    without re-wiring the singleton.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        secret: str | None = None,
        signature_header: str = "X-Signature",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url
        self._secret = secret
        self._signature_header = signature_header
        self._transport = transport

    # -- intents (write side) ------------------------------------------

    async def build(self, **payload: Any) -> dict[str, Any]:
        """Submit a build intent; returns ``{build_id, status}`` immediately.

        Accepts the payload as keywords rather than a fixed signature: the
        manager's ``BuildRequest`` is the schema of record and the publish
        pipeline composes it there (contract §2). Pinning the arguments here
        would mean two schemas to keep in step.
        """
        return await self._request("POST", "/v1/intents/build", json=payload, op="build")

    async def deploy(self, **payload: Any) -> dict[str, Any]:
        """Declare the desired running state of one app → ``{instance_id, phase, generation}``."""
        return await self._request("POST", "/v1/intents/deploy", json=payload, op="deploy")

    async def stop(self, *, app_id: str) -> dict[str, Any]:
        """Reclaim the execution body. The app's volume and snapshots are untouched (AC-39)."""
        return await self._request("POST", "/v1/intents/stop", json={"app_id": app_id}, op="stop")

    async def destroy(self, *, app_id: str, purge_volume: bool = False) -> dict[str, Any]:
        """Remove the execution body; ``purge_volume=True`` also removes the app's data.

        ``purge_volume`` defaults to False so that a caller who forgets the flag
        destroys less than they meant to, never more (AC-40).
        """
        return await self._request(
            "POST",
            "/v1/intents/destroy",
            json={"app_id": app_id, "purge_volume": purge_volume},
            op="destroy",
        )

    async def probe(self, **payload: Any) -> dict[str, Any]:
        """Readiness of a live app (``app_id``) or of a bare image (``image_ref``) → ``{ready, reason}``."""
        return await self._request("POST", "/v1/intents/probe", json=payload, op="probe")

    async def preview_start(self, **payload: Any) -> dict[str, Any]:
        """F055 AC-26 — an approver's temporary instance → ``{instance_id, upstream, phase}``.

        A separate intent from ``deploy`` rather than ``deploy`` with another
        id: deploy declares an application's desired state, and a preview must
        write no such record — that is what keeps it off the instance quota and
        out of the reconciler's reach. Keyed by ``session_id``; the app and
        version ids ride along as labels only.
        """
        return await self._request("POST", "/v1/intents/preview", json=payload, op="preview_start")

    async def preview_stop(self, *, session_id: str) -> dict[str, Any]:
        """Reclaim one preview → ``{reclaimed: bool}``. Idempotent, and it has to be:
        terminal approval, the approver's button and the timeout sweep can all
        fire for the same session (AC-28)."""
        return await self._request(
            "POST", "/v1/intents/preview/stop", json={"session_id": session_id}, op="preview_stop"
        )

    # There is deliberately **no** ``preview_route`` here. ``GET /v1/previews/
    # {session}/route`` exists on the manager, but its only caller is app-proxy,
    # which holds its own manager client — the backend never resolves a preview
    # upstream. A facade method with no caller is dead code, and this facade's
    # method set is asserted lockstep, so a dead one would be copied into two
    # test fixtures forever.

    async def admission(self, *, tier: dict[str, Any] | None = None, purpose: str = "run") -> dict[str, Any]:
        """Capacity gate (AC-19). The verdict **snapshot is passed through verbatim**
        so the "待上线(资源不足)" copy can name the real numbers (AC-65)."""
        body: dict[str, Any] = {"purpose": purpose}
        if tier is not None:
            body["tier"] = tier
        return await self._request("POST", "/v1/admission", json=body, op="admission")

    # -- read side ------------------------------------------------------

    async def build_status(self, *, build_id: str) -> dict[str, Any]:
        """Poll one build. ``status="failed"`` is returned, not raised — see the module docstring."""
        return await self._request("GET", f"/v1/builds/{build_id}", op="build_status")

    async def status(self, *, app_id: str) -> dict[str, Any]:
        """Instance phase / health / restarts. 404 (no instance) raises 16101; a dead
        orchestration backend raises 16121 — the two must stay distinguishable
        or a dockerd restart reads as "the app was deleted" (contract §2)."""
        return await self._request("GET", f"/v1/apps/{app_id}/status", op="status")

    async def logs(
        self,
        *,
        app_id: str,
        tail: int | None = None,
        since: str | None = None,
        keyword: str | None = None,
    ) -> dict[str, Any]:
        """Recent output of one app. ``keyword`` filters *after* ``tail``, so a
        keyword search may return fewer lines than asked — by design (contract §2)."""
        params = {key: value for key, value in (("tail", tail), ("since", since), ("keyword", keyword)) if value}
        return await self._request("GET", f"/v1/apps/{app_id}/logs", params=params, op="logs")

    async def runtime_status(self) -> dict[str, Any]:
        """Deployment self-check. Answers 200 even when the orchestration backend is
        down (``backend_available=false``) — that is its most useful answer."""
        return await self._request("GET", "/v1/runtime/status", op="runtime_status")

    # -- data plane (AC-56, design D10-C) -------------------------------
    #
    # The app's SQLite lives on the manager's host; backend never opens it.
    # These five are the whole vocabulary — table list, table shape, keyed
    # rows, one-row update, CSV export. No method carries SQL, so there is no
    # DDL to refuse. The sole caller is ``AppDataService`` (owner narrowing +
    # audit live there); the F052 MCP data tools go through that service too.

    async def db_tables(self, *, app_id: str) -> dict[str, Any]:
        """``{tables: [{name, column_count}]}``. 16163 while the app has not created its database."""
        return await self._request("GET", f"/v1/apps/{app_id}/db/tables", op="db_tables")

    async def db_schema(self, *, app_id: str, table: str) -> dict[str, Any]:
        """``{table, columns[], key{column, kind}, editable}``."""
        return await self._request("GET", f"/v1/apps/{app_id}/db/tables/{table}/schema", op="db_schema")

    async def db_rows(
        self,
        *,
        app_id: str,
        table: str,
        page: int | None = None,
        size: int | None = None,
        order: str | None = None,
    ) -> dict[str, Any]:
        """One page — ``{rows: [{key, values}], total, page, size, order}`` — in a stable order."""
        params = {key: value for key, value in (("page", page), ("size", size), ("order", order)) if value}
        return await self._request("GET", f"/v1/apps/{app_id}/db/tables/{table}/rows", params=params, op="db_rows")

    async def db_update_row(self, *, app_id: str, table: str, key: str, values: dict[str, Any]) -> dict[str, Any]:
        """Change exactly one row → ``{table, key, before, after}`` for the audit trail.

        ``key`` is whatever the app stored in a TEXT primary key — ``a?b``,
        ``100%``, a space — so it is percent-encoded for the wire; left raw, a
        ``?`` would turn the rest of the key into a query string and address a
        different row. The signature still covers the decoded path (see
        ``_request``).
        """
        return await self._request(
            "PATCH",
            f"/v1/apps/{app_id}/db/tables/{table}/rows/{quote(key, safe='')}",
            json={"values": values},
            op="db_update_row",
        )

    async def db_export(self, *, app_id: str, table: str) -> bytes:
        """The whole table as CSV bytes; the platform streams them on as a download."""
        return await self._request(
            "GET", f"/v1/apps/{app_id}/db/export", params={"table": table}, op="db_export", as_bytes=True
        )

    # -- transport ------------------------------------------------------

    def _config(self) -> tuple[str, str]:
        conf = settings.app_runtime
        base_url = (self._base_url if self._base_url is not None else conf.manager_base_url) or ""
        secret = self._secret if self._secret is not None else conf.manager_hmac_secret
        return base_url.rstrip("/"), secret or ""

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        op: str,
        as_bytes: bool = False,
    ) -> Any:
        base_url, secret = self._config()
        if not secret:
            logger.error("app_runtime.orchestrator op={} rejected: manager_hmac_secret is empty (fail-closed)", op)
            raise AppOrchestratorUnavailableError(msg="运行环境管理器未配置共享密钥", reason="hmac_secret_missing")

        raw = self._encode(json)
        # The manager verifies against the *decoded* request path (Starlette's
        # ``request.url.path``), so the signature covers the decoded form even
        # when the wire carries a percent-encoded segment (a row key).
        headers = {self._signature_header: compute_signature(method, unquote(path), raw, secret)}
        if json is not None:
            headers["Content-Type"] = "application/json"

        # Replaying a write whose response we never saw could double-apply it;
        # only reads and never-connected attempts are retried (module docstring).
        idempotent = method.upper() == "GET"
        timeout = _TIMEOUTS.get(op, _DEFAULT_TIMEOUT)
        last_error: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                async with httpx.AsyncClient(base_url=base_url, timeout=timeout, transport=self._transport) as client:
                    response = await client.request(
                        method,
                        path,
                        content=raw if json is not None else None,
                        params=params or None,
                        headers=headers,
                    )
                return self._unwrap(response, op=op, as_bytes=as_bytes)
            except httpx.ConnectError as exc:
                last_error = exc  # peer never saw it — safe to replay whatever the verb
            except httpx.HTTPError as exc:
                last_error = exc
                if not idempotent:
                    break
            if attempt + 1 < _MAX_ATTEMPTS:
                logger.warning("app_runtime.orchestrator op={} attempt={} retrying: {}", op, attempt + 1, last_error)

        logger.error("app_runtime.orchestrator op={} unreachable: {}", op, last_error)
        raise AppOrchestratorUnavailableError(
            msg="无法连接运行环境管理器",
            reason="transport_error",
            detail=str(last_error),
        )

    @staticmethod
    def _encode(payload: dict[str, Any] | None) -> bytes:
        if payload is None:
            return b""
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    @staticmethod
    def _unwrap(response: httpx.Response, *, op: str, as_bytes: bool = False) -> Any:
        """JSON body on success, 161xx on failure; ``as_bytes=True`` hands back the bytes.

        The error envelope is JSON either way — a failed export is a
        ``{"detail": {...}}`` document, never a partial CSV — so the failure
        branch does not depend on ``as_bytes``.
        """
        if as_bytes and response.status_code < 400:
            return response.content
        try:
            body = response.json()
        except ValueError:
            body = None
        if response.status_code < 400:
            return body if isinstance(body, dict) else {}

        detail = body.get("detail") if isinstance(body, dict) else None
        detail = detail if isinstance(detail, dict) else {}
        code = str(detail.get("code") or "")
        message = str(detail.get("message") or "") or f"HTTP {response.status_code}"
        error_cls = _ERROR_BY_MANAGER_CODE.get(code, AppOrchestratorUnavailableError)
        extras = {key: value for key, value in detail.items() if key not in ("code", "message")}
        logger.warning("app_runtime.orchestrator op={} manager_code={} http={}", op, code or "?", response.status_code)
        raise error_cls(msg=message, manager_code=code or "unknown", **extras)


#: Process-wide facade. Seventeen public methods (ten orchestration + two
#: preview + five data plane), no more: the F054/F055 test
#: fixtures assert this set so that a newly added method cannot silently fall
#: through to real HTTP against runtime-manager in a unit test.
orchestrator_client = OrchestratorClient()
