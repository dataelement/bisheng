"""Issue hashed, operation-bound outbound handles; proxies receive read projections only."""

import base64
import hashlib
import hmac
import re
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeEgressPolicy
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict


def destination(value, *, trusted=False):
    text = value if "://" in value else "https://" + value
    parsed = urlsplit(text)
    host = parsed.hostname
    if (
        not host
        or parsed.scheme not in {"http", "https"}
        or not re.fullmatch(r"\.?[A-Za-z0-9.-]+", host)
        or (not trusted and (parsed.username or parsed.password))
    ):
        raise RuntimeConflict("egress_destination_invalid")
    return {
        "host": host.lower(),
        "ports": [parsed.port or (80 if parsed.scheme == "http" else 443)],
        "trusted": trusted,
    }


class RuntimeEgressService:
    def __init__(self, repository):
        self.repo = repository

    async def issue(self, op, *, phase, declared=(), platform_base="", package_sources=()):
        if phase not in {"build", "runtime"}:
            raise RuntimeConflict("egress_phase_invalid")
        destinations = [destination(value) for value in declared]
        if platform_base:
            destinations.append(destination(platform_base, trusted=True))
        if phase == "build":
            destinations.extend(destination(value, trusted=True) for value in package_sources if value)
        if phase == "runtime" and op.payload.get("sealed_env"):
            from bisheng.app_runtime.domain.services.runtime_payload import unseal

            environment = unseal(op.payload["sealed_env"])
            for name in (
                "BISHENG_PLATFORM_API_BASE",
                "BISHENG_API_BASE_URL",
                "BISHENG_APP_STORAGE_ENDPOINT",
                "OPENAI_BASE_URL",
                "BISHENG_MODEL_BASE_URL",
            ):
                if environment.get(name):
                    destinations.append(destination(environment[name], trusted=True))
        principal = f"{phase}-{op.id}"
        from bisheng.app_runtime.domain.services.runtime_payload import cipher
        from bisheng.common.services.config_service import settings

        cipher()  # Validate the deployment key before deriving an operation-bound credential.
        key = base64.urlsafe_b64decode(settings.app_runtime.runtime_payload_key)
        token = hmac.new(key, b"runtime-egress-v2\0" + principal.encode(), hashlib.sha256).hexdigest()
        async with self.repo.transaction():
            rows = await self.repo.find(RuntimeEgressPolicy, principal_id=principal, lock=True)
            row = (
                rows[0]
                if rows
                else RuntimeEgressPolicy(
                    tenant_id=op.tenant_id,
                    app_id=op.app_id,
                    version_id=op.version_id,
                    operation_id=op.id,
                    phase=phase,
                    principal_id=principal,
                    not_after=op.deadline,
                    credential_hash="",
                )
            )
            row.credential_hash = hashlib.sha256(token.encode()).hexdigest()
            row.destinations = destinations
            row.revoked_at = None
            row.not_after = (
                datetime.utcnow() + timedelta(days=3650)
                if phase == "runtime" and op.kind in {"deploy", "restore"}
                else op.deadline
            )
            row.policy_epoch += 1
            await self.repo.save(row)
        return {"principal": principal, "token": token}
