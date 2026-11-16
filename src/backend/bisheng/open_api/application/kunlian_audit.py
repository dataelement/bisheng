"""Minimal durable audit boundary: intent failure denies; result failure alerts."""

import re

from loguru import logger

from bisheng.open_api.domain.repositories.kunlian_audit import KunlianAuditRepository
from bisheng.open_api.domain.services.kunlian_credential import KunlianAccessError


def _text(value, limit, *, optional=False):
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > limit or any(ord(char) < 32 for char in value):
        raise KunlianAccessError("INVALID_INPUT")
    return value


class KunlianAuditService:
    def __init__(self, repository=None):
        self.repository = repository if repository is not None else KunlianAuditRepository()

    async def begin(self, access, method, route, target_id, trace_id):
        """Call before business effects; route must be a server-owned route template.

        No request object, headers, query parameters, body or exception text is
        serialized. Identifiers must come from verified access and server facts.
        """
        method = _text(method, 16)
        route = _text(route, 256)
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"} or not re.fullmatch(
            r"/[A-Za-z0-9_/{}/.:-]*", route
        ):
            raise KunlianAccessError("INVALID_INPUT")
        target_id = _text(target_id, 64, optional=True)
        trace_id = _text(trace_id, 128, optional=True)
        credential, user = access.credential, access.user
        if any(
            type(value) is not int or value <= 0 for value in (credential.credential_id, user.tenant_id, user.user_id)
        ):
            raise KunlianAccessError("INVALID_INPUT")
        metadata = {
            "credential_id": credential.credential_id,
            "integration_id": _text(credential.integration_id, 128),
            "external_tenant_id": _text(access.external_tenant_id, 128),
            "tenant_id": user.tenant_id,
            "user_id": user.user_id,
            "method": method,
            "route": route,
            "target_id": target_id,
            "trace_id": trace_id,
            "state": "INTENT",
        }
        values = {
            "tenant_id": user.tenant_id,
            "operator_tenant_id": user.tenant_id,
            "operator_id": user.user_id,
            "operator_name": None,
            "action": "open_api.kunlian.request",
            "target_type": "workflow",
            "target_id": target_id,
            "audit_metadata": metadata,
        }
        try:
            return await self.repository.begin(values)
        except Exception:
            # Driver errors can contain bound values. Never log their text/trace.
            logger.error("Kunlian audit intent persistence failed; request denied")
            raise KunlianAccessError("UNAVAILABLE") from None

    async def begin_control(self, user, method, route, target_id, trace_id):
        """Persist only after the control dependency verifies current super facts."""
        from bisheng.core.context.tenant import tenant_execution_scope

        method, route = _text(method, 16), _text(route, 256)
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"} or not re.fullmatch(
            r"/[A-Za-z0-9_/{}/.:-]*", route
        ):
            raise KunlianAccessError("INVALID_INPUT")
        if type(user.user_id) is not int or user.user_id <= 0:
            raise KunlianAccessError("INVALID_INPUT")
        target_id, trace_id = _text(target_id, 64, optional=True), _text(trace_id, 128, optional=True)
        metadata = {
            "control_plane": True,
            "tenant_id": 1,
            "user_id": user.user_id,
            "method": method,
            "route": route,
            "target_id": target_id,
            "trace_id": trace_id,
            "state": "INTENT",
        }
        values = {
            "tenant_id": 1,
            "operator_tenant_id": 1,
            "operator_id": user.user_id,
            "operator_name": None,
            "action": "open_api.kunlian.request",
            "target_type": "kunlian_credential",
            "target_id": target_id,
            "audit_metadata": metadata,
        }
        try:
            with tenant_execution_scope(1):
                return await self.repository.begin(values)
        except Exception:
            logger.error("Kunlian control audit intent persistence failed; request denied")
            raise KunlianAccessError("UNAVAILABLE") from None

    async def finish(self, audit_id, http_status):
        if (
            not isinstance(audit_id, str)
            or not audit_id
            or type(http_status) is not int
            or not 100 <= http_status <= 599
        ):
            raise KunlianAccessError("INVALID_INPUT")
        try:
            await self.repository.finish(audit_id, http_status)
        except Exception:
            # The committed intent remains discoverable for repair. Do not alter
            # the HTTP business result or claim its side effects were rolled back.
            logger.error("Kunlian audit completion failed; durable intent requires reconciliation")
            return False
        return True


async def begin(access, method, route, target_id, trace_id):
    return await KunlianAuditService().begin(access, method, route, target_id, trace_id)


async def finish(audit_id, http_status):
    return await KunlianAuditService().finish(audit_id, http_status)


async def begin_control(user, method, route, target_id, trace_id):
    return await KunlianAuditService().begin_control(user, method, route, target_id, trace_id)
