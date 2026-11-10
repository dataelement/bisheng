"""Tenant-owned publication of existing capabilities to Desktop Work."""

from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable


class DshWorkPublication(SQLModelSerializable, table=True):
    __tablename__ = "dsh_work_publication"

    key: str = Field(primary_key=True, max_length=100)
    tenant_id: int = Field(index=True)
    kind: str = Field(max_length=16)
    resource_id: int
    enabled: bool = False
