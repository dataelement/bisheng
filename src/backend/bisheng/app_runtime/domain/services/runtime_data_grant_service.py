"""Backend-only owner action signing; managers receive no signing endpoint."""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from bisheng.app_runtime.domain.models.runtime_delivery import (
    RuntimeAssignment,
    RuntimeNode,
    RuntimeOperation,
    RuntimeRoute,
)
from bisheng.app_runtime.domain.models.runtime_kubernetes import RuntimeExecutionResource
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeDeliveryRepository
from bisheng.app_runtime.domain.services.runtime_protocol import canonical_json, content_digest
from bisheng.common.errcode.app_factory import AppDataBusyError

_DOMAIN = b"BISHENG-RUNTIME-DATA-V1\n"
_KEY_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _refused(reason="data_grant_scope_refused"):
    raise AppDataBusyError(reason=reason)


class RuntimeDataGrantService:
    def __init__(self, repository=None, *, keyring=None, clock=datetime.utcnow):
        self.repo = repository or RuntimeDeliveryRepository()
        self._keyring, self.clock = keyring, clock

    def _keys(self):
        document = self._keyring
        if document is None:
            path = Path(os.environ.get("BISHENG_RUNTIME_DATA_SIGNING_KEY_FILE", "/run/runtime-data-signing/keys.json"))
            try:
                metadata = path.stat()
                if metadata.st_mode & 0o007 or metadata.st_mode & 0o020 or metadata.st_size > 16384:
                    raise ValueError()
                if metadata.st_mode & 0o040 and metadata.st_gid not in {os.getegid(), *os.getgroups()}:
                    raise ValueError()
                document = json.loads(path.read_text())
            except (OSError, ValueError, UnicodeError):
                _refused("data_signing_key_unavailable")
        try:
            if set(document) != {"active_key_id", "private_keys"}:
                raise ValueError()
            raw = document["private_keys"]
            active = document["active_key_id"]
            if not isinstance(raw, dict) or not 1 <= len(raw) <= 8 or active not in raw:
                raise ValueError()
            keys = {}
            for key_id, private in raw.items():
                if not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id):
                    raise ValueError()
                if not isinstance(private, str) or not re.fullmatch(r"[a-f0-9]{64}", private):
                    raise ValueError()
                keys[key_id] = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private))
            return active, keys
        except (ValueError, TypeError, KeyError):
            _refused("data_signing_key_invalid")

    def public_keys(self):
        _, keys = self._keys()
        return {
            key_id: key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
            for key_id, key in keys.items()
        }

    async def issue(self, app, actor, operation, target, action, parameters):
        from bisheng.app_runtime.domain.services.app_data_service import AppDataService

        now = self.clock()
        active, keys = self._keys()
        async with self.repo.transaction():
            fresh_app = await self.repo.get_application(app.id)
            if fresh_app is None or fresh_app.state == "deleted" or fresh_app.tenant_id != app.tenant_id:
                _refused()
            AppDataService._require_owner(fresh_app, actor)
            current = await self.repo.get(RuntimeOperation, operation.id, lock=True)
            if current is None:
                _refused()
            node = await self.repo.get(RuntimeNode, current.node_id, lock=True)
            assignments = await self.repo.find(RuntimeAssignment, app_id=app.id, lock=True)
            owner = assignments[0] if assignments else None
            expected = (app.tenant_id, app.id, current.node_id, current.generation, current.owner_epoch)
            if (
                current.kind != "data"
                or current.status != "running"
                or current.stage != "ready"
                or current.deadline <= now
                or node is None
                or node.executor_kind != "kubernetes"
                or node.status != "ready"
                or current.app_id != app.id
                or current.tenant_id != app.tenant_id
                or current.payload.get("data_action_finished")
                or current.payload.get("cancel_requested")
                or owner is None
                or owner.data_operation_id != current.id
                or (owner.tenant_id, owner.app_id, owner.node_id, owner.generation, owner.owner_epoch) != expected
                or current.payload.get("actor_ref") != "user:" + str(actor.user_id)
                or action not in {"tables", "schema", "rows", "update", "export", "result"}
                or current.payload.get("action") != action
                or current.payload.get("parameters_digest") != content_digest(parameters)
            ):
                _refused()
            resource = await self.repo.get(RuntimeExecutionResource, target.get("exec_ref", ""))
            if (
                resource is None
                or resource.kind != "Pod"
                or not resource.uid
                or (resource.tenant_id, resource.app_id, resource.node_id, resource.generation, resource.owner_epoch)
                != expected
                or resource.uid != target.get("pod_uid")
                or resource.stop_requested_at is not None
                or resource.cleanup_state == "complete"
                or resource.stop_state == "confirmed"
                or node.engine_id != resource.cluster_id + "/" + resource.namespace
                or target.get("online") is not current.payload.get("online")
                or active not in target.get("key_ids", [])
            ):
                _refused("data_execution_unconfirmed")
            if current.payload["online"]:
                routes = await self.repo.find(RuntimeRoute, route_key="app:" + app.id, app_id=app.id)
                if (
                    not routes
                    or routes[0].status != "serving"
                    or routes[0].exec_ref != resource.id
                    or resource.purpose != "serve"
                ):
                    _refused("data_execution_changed")
            elif resource.operation_id != current.id or resource.purpose != "data":
                _refused("data_execution_changed")
            try:
                for value in (current.payload["request_id"], resource.id, resource.uid):
                    if str(UUID(value)) != value:
                        raise ValueError()
            except (ValueError, TypeError, AttributeError):
                _refused()
            issued = int((now.replace(tzinfo=UTC) if now.tzinfo is None else now).timestamp())
            expires = min(issued + 5, int(current.deadline.replace(tzinfo=UTC).timestamp()))
            if expires <= issued:
                _refused("data_session_expired")
            claims = {
                "version": 1,
                "operation_id": current.id,
                "request_id": current.payload["request_id"],
                "app_id": app.id,
                "exec_ref": resource.id,
                "pod_uid": resource.uid,
                "actor_ref": current.payload["actor_ref"],
                "action": action,
                "parameters_sha256": content_digest(parameters),
                "nonce": str(uuid4()),
                "issued_at": issued,
                "not_after": expires,
                "deadline": min(issued + 60, int(current.deadline.replace(tzinfo=UTC).timestamp())),
            }
            # Commit acceptance expiry before handing the ticket to any process.
            current.payload = {
                **current.payload,
                "data_grant_not_after": max(expires, current.payload.get("data_grant_not_after", 0)),
            }
            await self.repo.save(current)
            document = {"key_id": active, "claims": claims}
            return {**document, "signature": keys[active].sign(_DOMAIN + canonical_json(document)).hex()}
