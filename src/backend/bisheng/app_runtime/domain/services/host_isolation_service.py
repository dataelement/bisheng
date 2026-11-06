"""Host reporter uses its own node-bound service identity."""

from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeNode
from bisheng.app_runtime.domain.repositories.host_isolation_repository import HostIsolationRepository
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import (
    RuntimeConflict,
    RuntimeDeliveryRepository,
)
from bisheng.app_runtime.domain.services.runtime_protocol import content_digest
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import bypass_tenant_filter


class HostIsolationService:
    async def accept(self, identity, body):
        if set(identity.roles) != {"host-isolation"} or not identity.node_id:
            raise RuntimeConflict("host_isolation_identity_refused")
        expected = settings.app_runtime.runtime_host_isolation_nodes.get(identity.node_id) or {}
        descriptor = expected.get("descriptor") or {}
        if descriptor.get("node_id") != identity.node_id or content_digest(descriptor) != expected.get("config_digest"):
            raise RuntimeConflict("host_isolation_binding_mismatch")
        return await HostIsolationRepository().accept(identity, body, expected)

    async def current(self, identity):
        if set(identity.roles) != {"manager"} or not identity.node_id:
            raise RuntimeConflict("host_isolation_identity_refused")
        repo = RuntimeDeliveryRepository()
        with bypass_tenant_filter():
            async with repo.transaction() as session:
                node = await repo.get(RuntimeNode, identity.node_id)
                expected = settings.app_runtime.runtime_host_isolation_nodes.get(identity.node_id)
                if node is None and expected:
                    node = RuntimeNode(
                        id=identity.node_id,
                        engine_id=expected["engine_id"],
                        platform="linux/amd64",
                        executor_kind="docker",
                    )
                row = await HostIsolationRepository.require(session, node, expected)
                return {
                    "node_id": node.id,
                    "revision": row.revision,
                    "valid_until": row.valid_until,
                    "engine_id": row.engine_id,
                    "network_id": row.network_id,
                    "config_digest": row.config_digest,
                    "descriptor": expected["descriptor"],
                }
