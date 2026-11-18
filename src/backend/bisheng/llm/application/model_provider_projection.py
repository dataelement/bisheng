"""Business-owned binding of provider projection journals to the original Plan.

The request index is immutable and rebuilt from actual persisted execution
facts. It is not a second ledger or a process-global authority registry.
"""

from dataclasses import dataclass
from types import MappingProxyType

from sqlalchemy import inspect as inspect_orm

from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge_operation_plan import KnowledgeOperationPlan
from bisheng.llm.domain.repositories.model_provider_operation_repository import ModelProviderOperationRepository
from bisheng.permission.application.model_sharing_projection import MODEL_SHARING_SCOPE, ProjectionScopeDeferred
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository


def _blocked():
    raise PermissionPublishNotReadyError(msg="Model projection is not bound to its exact provider operation")


def execution_metadata(row):
    metadata = row.model_execution_metadata
    if not isinstance(metadata, dict) or set(metadata) != {
        "version",
        "purpose",
        "parent_confirmation_id",
        "sharing",
        "reserved_target_revisions",
        "ack",
        "force",
    }:
        _blocked()
    if (
        type(metadata["version"]) is not int
        or metadata["version"] != 1
        or type(metadata["force"]) is not bool
        or metadata["purpose"]
        not in {"model_share_server", "model_delete_prepare", "model_update_server", "model_delete_server"}
        or metadata["purpose"] not in {row.operation, "model_delete_prepare"}
        or (metadata["purpose"] == "model_delete_prepare" and row.operation != "model_share_server")
        or not isinstance(metadata["reserved_target_revisions"], dict)
        or (
            metadata["parent_confirmation_id"] is not None
            and (
                not isinstance(metadata["parent_confirmation_id"], str) or len(metadata["parent_confirmation_id"]) != 36
            )
        )
    ):
        _blocked()
    expected = {f"model:{item['target_id']}" for item in row.target_manifest}
    revisions = metadata["reserved_target_revisions"]
    if row.model_execution_state not in {"PREPARING", "COMPLETED"} and set(revisions) != expected:
        _blocked()
    if any(
        not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value)
        for value in revisions.values()
    ):
        _blocked()
    return metadata


@dataclass(frozen=True, slots=True, init=False)
class ModelProjectionBinding:
    confirmation_id: str
    tenant_id: int
    server_id: int
    operation: str
    operation_id: str
    actor_user_id: int
    request_hash: str
    plan_digest: str
    store_id: str
    model_id: str
    batches: object

    @classmethod
    def from_plan(cls, row, repository):
        if type(row) is not KnowledgeOperationPlan:
            _blocked()
        state = inspect_orm(row)
        if not state.persistent or state.session is None or state.modified:
            _blocked()
        repository.validate(row)
        metadata = execution_metadata(row)
        sharing = metadata["sharing"]
        if row.model_execution_state not in {"RESERVED", "SHARING_COMPLETE"} or not isinstance(sharing, dict):
            _blocked()
        if set(sharing) != {"server_id", "store_id", "model_id", "before", "after", "batches"}:
            _blocked()
        if sharing["server_id"] != row.model_server_id or type(sharing["batches"]) is not list:
            _blocked()
        batches = {}
        for item in sharing["batches"]:
            if (
                not isinstance(item, dict)
                or set(item) != {"id", "checksum"}
                or type(item["id"]) is not int
                or item["id"] <= 0
                or item["id"] in batches
                or not isinstance(item["checksum"], str)
                or len(item["checksum"]) != 64
                or any(ch not in "0123456789abcdef" for ch in item["checksum"])
            ):
                _blocked()
            batches[item["id"]] = item["checksum"]
        value = object.__new__(cls)
        for name, item in zip(
            cls.__dataclass_fields__,
            (
                row.id,
                row.tenant_id,
                row.model_server_id,
                row.operation,
                row.operation_id,
                row.actor_user_id,
                row.request_hash,
                row.plan_digest,
                sharing["store_id"],
                sharing["model_id"],
                MappingProxyType(batches),
            ),
            strict=True,
        ):
            object.__setattr__(value, name, item)
        return value

    def check_scalar(self, value):
        if (
            value.id != self.confirmation_id
            or value.tenant_id != self.tenant_id
            or value.operation != self.operation
            or value.operation_id != self.operation_id
            or value.actor_user_id != self.actor_user_id
            or value.model_server_id != self.server_id
            or value.request_hash != self.request_hash
            or value.plan_digest != self.plan_digest
            or value.model_execution_state not in {"RESERVED", "SHARING_COMPLETE"}
        ):
            _blocked()


class ModelProviderProjectionScope:
    def __init__(self, *, session_factory=get_async_db_session, repository=None, binding=None, guard=None):
        self.session_factory = session_factory
        self.repository = repository if repository is not None else ModelProviderOperationRepository()
        if binding is not None and type(binding) is not ModelProjectionBinding:
            raise TypeError("actual typed execution facts are required")
        self.binding, self.guard = binding, guard

    def check_request(self):
        tenant = ReferenceRepository.current_tenant_id()
        if self.binding is not None and tenant != self.binding.tenant_id:
            _blocked()
        if self.guard is not None:
            self.guard()

    async def _require(self, plan, operation_id):
        self.check_request()
        if plan.scope_type != MODEL_SHARING_SCOPE or type(operation_id) is not int or operation_id <= 0:
            _blocked()
        parts = plan.scope_key.split(":")
        if len(parts) != 3 or parts[0] != "llm_server" or not parts[1].isascii() or not parts[1].isdecimal():
            _blocked()
        server_id, confirmation_id = int(parts[1]), parts[2]
        if str(server_id) != parts[1] or server_id <= 0 or len(confirmation_id) != 36:
            _blocked()
        binding = self.binding
        async with self.session_factory() as session:
            async with session.begin():
                if binding is None:
                    row = await self.repository.aread_plan(session, confirmation_id=confirmation_id)
                    if row.operation_id is None or row.model_execution_state in {None, "PREPARING"}:
                        raise ProjectionScopeDeferred(msg="Model journal is awaiting its actual business binding")
                    binding = ModelProjectionBinding.from_plan(row, self.repository)
                scalar = await self.repository.ascalar_pin(session, confirmation_id=confirmation_id)
                binding.check_scalar(scalar)
        self.check_request()
        if (
            server_id != binding.server_id
            or confirmation_id != binding.confirmation_id
            or plan.tenant_id != binding.tenant_id
            or plan.operation_type != binding.operation
            or plan.operator_id != binding.actor_user_id
            or (plan.store_id, plan.model_id) != (binding.store_id, binding.model_id)
            or (plan.expected_version, plan.target_version) != (1, 2)
            or operation_id not in binding.batches
        ):
            _blocked()
        # Reuse the permission module's original immutable-plan checksum.
        from bisheng.permission.application.model_sharing_projection import projection_request_checksum

        if projection_request_checksum(plan) != binding.batches[operation_id]:
            _blocked()
        return binding

    async def reserve(self, plan, operation_id):
        await self._require(plan, operation_id)

    async def is_expected_version(self, plan, operation_id):
        await self._require(plan, operation_id)
        return True

    async def is_failed_closed_recovery_scope(self, plan, operation_id):
        return False

    async def finalize(self, plan, operation_id):
        # The journal's FINALIZED only acknowledges this batch. The provider
        # fence remains until its Owner atomically commits all business SQL.
        await self._require(plan, operation_id)

    async def fail_closed(self, plan, reason):
        self.check_request()
        del reason
        confirmation_id = plan.scope_key.split(":")[-1]
        async with self.session_factory() as session:
            async with session.begin():
                row = await self.repository.aread_plan(session, confirmation_id=confirmation_id)
                await self.repository.alock_provider(session, server_id=row.model_server_id)
                row = await self.repository.aread_plan(session, confirmation_id=confirmation_id, lock=True)
                if row.model_execution_state == "FAILED_CLOSED":
                    return
                if self.binding is not None:
                    self.binding.check_scalar(await self.repository.ascalar_pin(session, confirmation_id=row.id))
                await self.repository.aset_state(session, row=row, expected="RESERVED", target="FAILED_CLOSED")
        self.check_request()


def get_model_provider_projection_scope():
    return ModelProviderProjectionScope()
