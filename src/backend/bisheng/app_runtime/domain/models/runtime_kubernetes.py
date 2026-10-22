"""Tenant-scoped execution evidence and workload material public identities.

Private workload keys and cluster credentials never belong in these records.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, UniqueConstraint
from sqlmodel import Field

from bisheng.app_runtime.domain.models.runtime_delivery import ScopedRuntimeRecord
from bisheng.core.database.dialect_helpers import JsonType


class RuntimeExecutionResource(ScopedRuntimeRecord, table=True):
    __tablename__ = "runtime_execution_resource"
    __table_args__ = (UniqueConstraint("cluster_id", "namespace", "kind", "uid", name="uq_rt_resource_uid"),)
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True, max_length=36)
    operation_id: str = Field(index=True, max_length=36)
    node_id: str = Field(index=True, max_length=64)
    cluster_id: str = Field(max_length=64)
    namespace: str = Field(max_length=63)
    name: str = Field(max_length=63)
    uid: str | None = Field(default=None, max_length=64)
    kind: str = Field(max_length=32)
    purpose: str = Field(max_length=24)
    generation: int
    owner_epoch: int
    controller_epoch: int
    spec_digest: str = Field(max_length=64)
    # For Secrets this contains only approved metadata and the content digest.
    approved_template: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    status_policy_revision: str = Field(max_length=64)
    protected_since_creation: bool = False
    binding_policy_verified: bool = False
    node_name: str = Field(default="", max_length=253)
    stop_state: str = Field(default="held", max_length=24)
    stop_requested_at: datetime | None = None
    stop_evidence: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    cleanup_state: str = Field(default="pending", max_length=24)
    observed_at: datetime | None = None
    # Narrow observed endpoint facts, never a raw Pod/Secret/API response.
    observed_state: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))


class RuntimeMaterialDelegation(ScopedRuntimeRecord, table=True):
    __tablename__ = "runtime_material_delegation"
    __table_args__ = (UniqueConstraint("key_id", name="uq_rt_material_key"),)
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True, max_length=36)
    scope_kind: str = Field(max_length=24)
    version_id: str = Field(default="", max_length=36)
    delivery_id: str = Field(default="", max_length=36)
    operation_id: str = Field(index=True, max_length=36)
    node_id: str = Field(index=True, max_length=64)
    generation: int
    owner_epoch: int
    exec_ref: str = Field(max_length=36)
    pod_uid: str = Field(default="", max_length=64)
    key_id: str = Field(max_length=64)
    public_key: str = Field(max_length=64)
    allowed_artifacts: list = Field(default_factory=list, sa_column=Column(JsonType, nullable=False))
    allowed_actions: list = Field(default_factory=list, sa_column=Column(JsonType, nullable=False))
    # Per-authority declarations remain immutable even when bytes are deduplicated.
    upload_declarations: dict = Field(default_factory=dict, sa_column=Column(JsonType, nullable=False))
    proxy_credential_hash: str = Field(default="", max_length=64)
    # None means current deployment ownership is revalidated on every request.
    expires_at: datetime | None = None
    revoked_at: datetime | None = None


KUBERNETES_TABLES = (RuntimeExecutionResource, RuntimeMaterialDelegation)
