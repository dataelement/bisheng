"""Error envelope shared by every intent endpoint.

The manager does **not** own the platform's 161xx error codes (those live in
``bisheng/common/errcode/app_factory.py``); it returns a stable machine code
that the backend's ``orchestrator_client`` maps onto them:

=========================  ==========================================
manager code               backend error code
=========================  ==========================================
``unauthorized``           401 → 16121 (orchestrator unavailable)
``backend_unavailable``    16121 编排器不可用
``unsupported_runtime``    16123 runtime 取值不支持
``capacity_exhausted``     16125 运行环境容量不足
``build_failed``           16122 构建失败
``probe_failed``           16124 启动探活失败
``not_found``              16101 / route 404
=========================  ==========================================
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException


class RuntimeManagerError(HTTPException):
    """HTTPException carrying a structured, machine-readable detail body."""

    code = "internal_error"
    status = 500

    def __init__(self, message: str, **extra: Any) -> None:
        detail: dict[str, Any] = {"code": self.code, "message": message}
        detail.update(extra)
        super().__init__(status_code=self.status, detail=detail)


class UnauthorizedError(RuntimeManagerError):
    code = "unauthorized"
    status = 401


class NotFoundError(RuntimeManagerError):
    code = "not_found"
    status = 404


class InvalidRequestError(RuntimeManagerError):
    """Well-formed JSON, incoherent intent (e.g. a probe naming neither target)."""

    code = "invalid_request"
    status = 400


class UnsupportedRuntimeError(RuntimeManagerError):
    """AC-15: reject and *list the supported values* — never a bare 400."""

    code = "unsupported_runtime"
    status = 400


class CapacityExhaustedError(RuntimeManagerError):
    code = "capacity_exhausted"
    status = 409


class BackendUnavailableError(RuntimeManagerError):
    """dockerd (or the socket proxy in D2-B) is not reachable."""

    code = "backend_unavailable"
    status = 503


class ProbeFailedError(RuntimeManagerError):
    code = "probe_failed"
    status = 409
