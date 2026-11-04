"""Durable F086 control records; global catalogs are separate from tenant data."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import BigInteger, Column, String, UniqueConstraint, text
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType


class RuntimeRecord(SQLModelSerializable):
    id: str = Field(default_factory=lambda: uuid4().hex, primary_key=True, max_length=36)
    create_time: datetime = Field(
        default_factory=datetime.utcnow, sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")}
    )
    update_time: datetime = Field(
        default_factory=datetime.utcnow, sa_column_kwargs={"server_default": UPDATE_TIME_SERVER_DEFAULT}
    )


class ScopedRuntimeRecord(RuntimeRecord):
    tenant_id: int | None = Field(default=None, nullable=False, index=True)
    app_id: str = Field(index=True, max_length=36)


def _transfer_authorization(context):
    """New legacy inserts acquire a scope; historical rows stay NULL until ops backfill."""
    return context.get_current_parameters().get("operation_id")


class RuntimeProfile(RuntimeRecord, table=True):
    __tablename__ = "runtime_profile"
    __table_args__ = (UniqueConstraint("code", "revision", name="uq_runtime_profile_revision"),)
    code: str = Field(max_length=64, index=True)
    revision: int
    language: str = Field(max_length=32)
    contract_version: int = 1
    status: str = Field(default="active", max_length=24)
    created_by: int
    definition: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    content_digest: str = Field(max_length=64)


class RuntimeProfileDefault(RuntimeRecord, table=True):
    __tablename__ = "runtime_profile_default"
    __table_args__ = (UniqueConstraint("language", name="uq_runtime_profile_default"),)
    language: str = Field(max_length=32)
    profile_id: str = Field(max_length=36)
    generation: int = 1


class RuntimeArtifact(ScopedRuntimeRecord, table=True):
    __tablename__ = "runtime_artifact"
    __table_args__ = (UniqueConstraint("scope_key", "kind", "sha256", name="uq_runtime_artifact_content"),)
    scope_key: str = Field(max_length=128)
    kind: str = Field(max_length=32)
    visibility: str = Field(default="private", max_length=16)
    sha256: str = Field(max_length=64)
    size_bytes: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, default=0))
    object_key: str = Field(default="", max_length=512)
    platform: str = Field(default="", max_length=64)
    producer_operation_id: str = Field(default="", max_length=36)
    state: str = Field(default="uploading", max_length=24)
    retained_until: datetime | None = None
    confirmed_at: datetime | None = None
    metadata_: dict = Field(default_factory=dict, sa_column=Column("metadata", JsonType, nullable=False))


class RuntimeDelivery(ScopedRuntimeRecord, table=True):
    __tablename__ = "runtime_delivery"
    __table_args__ = (UniqueConstraint("version_id", name="uq_runtime_delivery_version"),)
    version_id: str = Field(max_length=36)
    execution_mode: str = Field(max_length=24)
    profile_id: str = Field(default="", max_length=36)
    resolved_platform: str = Field(default="", max_length=64)
    delivery_digest: str = Field(max_length=64)
    content: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))


class RuntimeOperation(ScopedRuntimeRecord, table=True):
    __tablename__ = "runtime_operation"
    __table_args__ = (UniqueConstraint("scope_key", "idempotency_key", name="uq_runtime_operation_request"),)
    scope_key: str = Field(max_length=128)
    idempotency_key: str = Field(max_length=128)
    request_digest: str = Field(max_length=64)
    deployment_id: str = Field(default="", max_length=36)
    version_id: str = Field(default="", max_length=36)
    kind: str = Field(max_length=24)
    node_id: str = Field(max_length=64, index=True)
    generation: int = 1
    owner_epoch: int = 1
    stage: str = Field(default="queued", max_length=32)
    status: str = Field(default="pending", max_length=24)
    cleanup_status: str = Field(default="pending", max_length=24)
    deadline: datetime
    payload: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    failure: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    diagnostics_until: datetime | None = Field(default=None, index=True)


class RuntimeAssignment(ScopedRuntimeRecord, table=True):
    __tablename__ = "runtime_assignment"
    __table_args__ = (UniqueConstraint("app_id", name="uq_runtime_assignment_app"),)
    node_id: str = Field(max_length=64)
    generation: int = 0
    owner_epoch: int = 1
    active_operation_id: str = Field(default="", max_length=36)
    data_operation_id: str = Field(default="", max_length=36, sa_column_kwargs={"server_default": ""})


class RuntimeNode(RuntimeRecord, table=True):
    __tablename__ = "runtime_node"
    __table_args__ = (UniqueConstraint("engine_id", name="uq_runtime_node_engine"),)
    engine_id: str = Field(max_length=128)
    platform: str = Field(max_length=64)
    memory_budget_mb: int
    cpu_budget_millicores: int
    heartbeat_at: datetime
    generation: int = 1
    status: str = Field(default="ready", max_length=24)
    executor_kind: str = Field(default="docker", max_length=24, sa_column_kwargs={"server_default": "docker"})
    capabilities: dict | None = Field(default_factory=dict, sa_column=Column(JsonType, nullable=True))
    controller_holder: str = Field(default="", max_length=64, sa_column_kwargs={"server_default": ""})
    controller_epoch: int = Field(default=0, sa_column_kwargs={"server_default": text("0")})
    lease_until: datetime | None = None
    probe_report: dict | None = Field(default_factory=dict, sa_column=Column(JsonType, nullable=True))


class RuntimeCapacityReservation(ScopedRuntimeRecord, table=True):
    __tablename__ = "runtime_capacity_reservation"
    __table_args__ = (UniqueConstraint("operation_id", name="uq_runtime_capacity_operation"),)
    operation_id: str = Field(max_length=36)
    node_id: str = Field(index=True, max_length=64)
    purpose: str = Field(max_length=24)
    memory_mb: int
    cpu_millicores: int
    state: str = Field(default="held", max_length=24)


class RuntimeExecutionFact(ScopedRuntimeRecord, table=True):
    __tablename__ = "runtime_execution_fact"
    __table_args__ = (UniqueConstraint("operation_id", "sequence", name="uq_runtime_fact_sequence"),)
    operation_id: str = Field(max_length=36)
    sequence: int
    node_id: str = Field(max_length=64)
    generation: int
    owner_epoch: int
    exec_ref: str = Field(default="", max_length=128)
    phase: str = Field(max_length=32)
    detail: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))


class RuntimeCredentialBinding(ScopedRuntimeRecord, table=True):
    __tablename__ = "runtime_credential_binding"
    __table_args__ = (UniqueConstraint("operation_id", name="uq_runtime_credential_operation"),)
    operation_id: str = Field(max_length=36)
    version_id: str = Field(max_length=36)
    credential_id: int = Field(index=True)
    state: str = Field(default="staged", max_length=24)


class RuntimeRoute(ScopedRuntimeRecord, table=True):
    __tablename__ = "runtime_route"
    __table_args__ = (UniqueConstraint("route_key", name="uq_runtime_route_key"),)
    operation_id: str = Field(default="", max_length=36)
    route_key: str = Field(max_length=128)
    version_id: str = Field(max_length=36)
    node_id: str = Field(max_length=64)
    exec_ref: str = Field(max_length=128)
    generation: int
    owner_epoch: int
    route_epoch: int = 1
    status: str = Field(default="maintenance", max_length=24)
    target: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))


class RuntimeEgressPolicy(ScopedRuntimeRecord, table=True):
    __tablename__ = "runtime_egress_policy"
    __table_args__ = (UniqueConstraint("principal_id", name="uq_runtime_policy_principal"),)
    principal_id: str = Field(max_length=128)
    version_id: str = Field(default="", max_length=36)
    operation_id: str = Field(default="", max_length=36)
    phase: str = Field(max_length=24)
    policy_epoch: int = 1
    not_after: datetime
    revoked_at: datetime | None = None
    credential_hash: str = Field(max_length=64)
    destinations: list = Field(default_factory=list, sa_column=Column(JsonType, nullable=False))


class RuntimeTransfer(ScopedRuntimeRecord, table=True):
    __tablename__ = "runtime_transfer"
    __table_args__ = (
        UniqueConstraint(
            "authorization_kind", "authorization_id", "artifact_id", "action", name="uq_rt_transfer_authority"
        ),
    )
    operation_id: str = Field(max_length=36)
    authorization_kind: str = Field(
        default="operation", max_length=24, sa_column_kwargs={"server_default": "operation"}
    )
    authorization_id: str | None = Field(
        default=None, sa_column=Column(String(36), nullable=True, default=_transfer_authorization)
    )
    artifact_id: str = Field(max_length=36)
    node_id: str = Field(max_length=64)
    action: str = Field(max_length=16)
    ticket_hash: str = Field(max_length=64)
    expires_at: datetime
    offset: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, default=0))
    parts: list = Field(default_factory=list, sa_column=Column(JsonType, nullable=False))
    state: str = Field(default="open", max_length=24)


class RuntimeStorageBinding(ScopedRuntimeRecord, table=True):
    __tablename__ = "runtime_storage_binding"
    __table_args__ = (UniqueConstraint("credential_hash", name="uq_runtime_storage_credential"),)
    version_id: str = Field(max_length=36)
    operation_id: str = Field(max_length=36)
    namespace: str = Field(max_length=128)
    object_prefix: str = Field(max_length=512)
    credential_hash: str = Field(max_length=64)
    state: str = Field(default="staged", max_length=24)
    expires_at: datetime | None = None


class RuntimeDependencyPlan(ScopedRuntimeRecord, table=True):
    __tablename__ = "runtime_dependency_plan"
    __table_args__ = (UniqueConstraint("scope_key", "input_key", name="uq_runtime_dependency_input"),)
    scope_key: str = Field(max_length=128)
    input_key: str = Field(max_length=64)
    operation_id: str = Field(max_length=36)
    artifact_id: str = Field(default="", max_length=36)
    state: str = Field(default="claimed", max_length=24)


RUNTIME_TABLES = (
    RuntimeProfile,
    RuntimeProfileDefault,
    RuntimeArtifact,
    RuntimeDelivery,
    RuntimeOperation,
    RuntimeAssignment,
    RuntimeNode,
    RuntimeCapacityReservation,
    RuntimeExecutionFact,
    RuntimeRoute,
    RuntimeEgressPolicy,
    RuntimeTransfer,
    RuntimeStorageBinding,
    RuntimeDependencyPlan,
    RuntimeCredentialBinding,
)
