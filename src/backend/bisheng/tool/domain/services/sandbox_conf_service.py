"""Page-level sandbox address and token. Execution reads the cache; this module writes it."""

from __future__ import annotations

import json
from urllib.parse import urlparse

import httpx
from loguru import logger

from bisheng.api.services.audit_log import AuditLogService
from bisheng.common.errcode.sandbox import SandboxEndpointInvalidError
from bisheng.common.models.config import ConfigDao, ConfigKeyEnum
from bisheng.common.services.config_service import (
    settings,
    write_sandbox_endpoint_cache,
)
from bisheng.core.config.settings import decrypt_token, encrypt_token

SANDBOX_TOKEN_MASK = "********"
_PROBE_TIMEOUT_S = 5.0
_MAX_ENDPOINTS = 32


def _source(page_set: bool, deployment_set: bool) -> str:
    if page_set:
        return "page"
    if deployment_set:
        return "deployment"
    return "default"


def _payload_ok(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    endpoints = value.get("endpoints")
    token_enc = value.get("token_enc")
    if not isinstance(endpoints, list) or any(not isinstance(item, str) for item in endpoints):
        return False
    return isinstance(token_enc, str)


def _empty_payload() -> dict:
    return {"endpoints": [], "token_enc": ""}


def _read_stored_payload() -> dict | None:
    """Stored page payload, or None when the row is missing or unreadable."""
    try:
        row = ConfigDao.get_config(ConfigKeyEnum.SANDBOX_ENDPOINT)
    except Exception:
        logger.error("sandbox endpoint config unreadable; using deployment config")
        return None
    if row is None or not row.value:
        return None
    try:
        parsed = json.loads(row.value)
    except Exception:
        logger.error("sandbox endpoint config unreadable; using deployment config")
        return None
    if not _payload_ok(parsed):
        logger.error("sandbox endpoint config unreadable; using deployment config")
        return None
    return {"endpoints": list(parsed["endpoints"]), "token_enc": parsed["token_enc"]}


def normalize_sandbox_endpoints(endpoints: list[str]) -> list[str]:
    """Validate and strip trailing slashes. Empty list is allowed (clears the page)."""
    if len(endpoints) > _MAX_ENDPOINTS:
        raise SandboxEndpointInvalidError()
    seen: list[str] = []
    for raw in endpoints:
        if not isinstance(raw, str):
            raise SandboxEndpointInvalidError()
        url = raw.strip().rstrip("/")
        if not url:
            raise SandboxEndpointInvalidError()
        try:
            parsed = urlparse(url)
            port = parsed.port
        except ValueError:
            raise SandboxEndpointInvalidError() from None
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise SandboxEndpointInvalidError()
        if port is not None and not 1 <= port <= 65535:
            raise SandboxEndpointInvalidError()
        if url in seen:
            raise SandboxEndpointInvalidError()
        seen.append(url)
    return seen


def _ciphertext(token: str) -> str:
    encrypted = encrypt_token(token)
    return encrypted.decode() if isinstance(encrypted, bytes) else encrypted


def _change_note(previous: dict, payload: dict) -> str:
    parts: list[str] = []
    if list(previous.get("endpoints") or []) != payload["endpoints"]:
        parts.append("endpoints")
    if (previous.get("token_enc") or "") != payload["token_enc"]:
        parts.append("已修改")
    return ",".join(parts)


class SandboxConfService:
    @staticmethod
    def get() -> dict:
        stored = _read_stored_payload()
        page_endpoints = stored["endpoints"] if stored else []
        page_token = stored["token_enc"] if stored else ""
        deployment = settings.sandbox_conf
        deployment_endpoints = [str(url) for url in (deployment.endpoints or [])]
        deployment_token = deployment.token or ""
        return {
            "endpoints": list(page_endpoints),
            "token": SANDBOX_TOKEN_MASK if page_token else "",
            "address_source": _source(bool(page_endpoints), bool(deployment_endpoints)),
            "token_source": _source(bool(page_token), bool(deployment_token)),
            "deployment_address": ",".join(deployment_endpoints),
        }

    @staticmethod
    async def save(endpoints: list[str], token: str, user, ip: str) -> None:
        normalized = normalize_sandbox_endpoints(endpoints)
        previous = _read_stored_payload() or _empty_payload()
        if token == SANDBOX_TOKEN_MASK:
            token_enc = previous["token_enc"]
        elif token == "":
            token_enc = ""
        else:
            token_enc = _ciphertext(token)
        payload = {"endpoints": normalized, "token_enc": token_enc}
        await ConfigDao.insert_or_update_config(
            ConfigKeyEnum.SANDBOX_ENDPOINT.value,
            json.dumps(payload, ensure_ascii=False),
        )
        try:
            write_sandbox_endpoint_cache(payload)
        except Exception:
            logger.error("sandbox endpoint cache write failed")
        AuditLogService.update_sandbox_conf(user, ip, _change_note(previous, payload))

    @staticmethod
    async def test(endpoints: list[str], token: str) -> dict:
        if endpoints:
            urls = normalize_sandbox_endpoints(endpoints)
        else:
            deployment_endpoints = [str(url) for url in (settings.sandbox_conf.endpoints or [])]
            if not deployment_endpoints:
                return {"results": []}
            urls = normalize_sandbox_endpoints(deployment_endpoints)
        bearer = _probe_token(token)
        logger.info("sandbox endpoint probe count={}", len(urls))
        results = []
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as client:
            for url in urls:
                results.append(await _probe_one(client, url, bearer))
        return {"results": results}


def _probe_token(token: str) -> str:
    if token != SANDBOX_TOKEN_MASK:
        return token
    stored = _read_stored_payload()
    if stored and stored["token_enc"]:
        try:
            return decrypt_token(stored["token_enc"])
        except Exception:
            logger.error("sandbox endpoint config unreadable; using deployment config")
    return settings.sandbox_conf.token or ""


async def _probe_one(client: httpx.AsyncClient, url: str, token: str) -> dict:
    try:
        health = await client.get(f"{url}/health", timeout=_PROBE_TIMEOUT_S)
    except Exception:
        return {"url": url, "status": "unreachable"}
    if health.status_code != 200:
        return {"url": url, "status": "unreachable"}
    try:
        created = await client.post(
            f"{url}/v1/sessions",
            headers={"Authorization": f"Bearer {token}"},
            timeout=_PROBE_TIMEOUT_S,
        )
    except Exception:
        return {"url": url, "status": "unreachable"}
    if created.status_code == 401:
        return {"url": url, "status": "token_rejected"}
    if created.status_code == 503:
        return {"url": url, "status": "busy"}
    if created.status_code != 200:
        return {"url": url, "status": "unreachable"}
    session_id = ""
    lease = ""
    try:
        body = created.json()
    except Exception:
        body = None
    if isinstance(body, dict):
        session_id = str(body.get("session_id") or "")
        lease = str(body.get("lease_token") or "")
    if session_id and lease:
        try:
            await client.delete(
                f"{url}/v1/sessions/{session_id}",
                headers={"x-lease-token": lease},
                timeout=_PROBE_TIMEOUT_S,
            )
        except Exception:
            logger.info("sandbox endpoint probe release failed url={}", url)
    return {"url": url, "status": "ok"}
