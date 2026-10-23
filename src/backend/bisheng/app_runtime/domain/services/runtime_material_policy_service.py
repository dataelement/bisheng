"""Read-only outbound identity projection of current material authorities."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeNode
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
from bisheng.app_runtime.domain.services.runtime_egress_service import destination
from bisheng.app_runtime.domain.services.runtime_material_protocol import MaterialProtocolError
from bisheng.app_runtime.domain.services.runtime_material_service import RuntimeMaterialService
from bisheng.core.context.tenant import bypass_tenant_filter


class RuntimeMaterialPolicyService:
    def __init__(self, repository, *, materials=None, platform_origin=None, clock=datetime.utcnow):
        self.repo, self.clock = repository, clock
        self.materials = materials or RuntimeMaterialService(repository, clock=clock)
        if platform_origin is None:
            from bisheng.common.services.config_service import settings

            platform_origin = settings.app_runtime.runtime_platform_base_url
        self.platform_origin = platform_origin

    async def policies(self, identity):
        if set(identity.roles) != {"egress"} or not identity.node_id:
            raise RuntimeConflict("independent_egress_identity_required")
        with bypass_tenant_filter():
            rows = await self.repo.material_policy_candidates(identity.node_id, self.clock())
            node = await self.repo.get(RuntimeNode, identity.node_id)
        if not rows:
            return []
        origin = urlsplit(self.platform_origin)
        if (
            origin.scheme != "https"
            or not origin.hostname
            or origin.username
            or origin.password
            or origin.path not in {"", "/"}
            or origin.query
            or origin.fragment
        ):
            raise RuntimeConflict("material_origin_https_required")
        now, result = self.clock(), []
        for row in rows:
            try:
                scope = await self.materials._current(row.id)
            except (MaterialProtocolError, RuntimeConflict):
                continue
            if scope.delegation.node_id != identity.node_id or not re.fullmatch(
                r"[a-f0-9]{64}", row.proxy_credential_hash
            ):
                continue
            destinations = [destination(self.platform_origin, trusted=True)]
            if (
                scope.resource.purpose == "prepare-download"
                and scope.operation.kind == "prepare"
                and not scope.operation.payload.get("offline")
            ):
                for value in (node.capabilities or {}).get("package_sources", []) if node else []:
                    destinations.append(destination(value, trusted=True))
            expiry = min(scope.deadline, now + timedelta(seconds=5)) if scope.deadline else now + timedelta(seconds=5)
            result.append(
                {
                    "principal": "material-" + row.id,
                    "credential_hash": row.proxy_credential_hash,
                    "destinations": destinations,
                    "phase": "material",
                    "policy_epoch": scope.operation.generation,
                    "not_after": expiry.replace(tzinfo=UTC).timestamp(),
                }
            )
        return result
