"""Durable provenance for a first installation interrupted before Alembic."""

from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable


class InstallationBootstrap(SQLModelSerializable, table=True):
    __tablename__ = "installation_bootstrap"

    id: int = Field(primary_key=True)
    state: str = Field(max_length=16)
