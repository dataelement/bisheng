"""OpenFGA configuration model."""

from typing import Optional

from pydantic import BaseModel, Field


class OpenFGAConf(BaseModel):
    """OpenFGA connection and behavior configuration."""

    enabled: bool = Field(default=True, description='Whether to enable OpenFGA integration')
    api_url: str = Field(default='http://openfga:8080', description='OpenFGA HTTP API URL')
    store_name: str = Field(default='bisheng', description='Store name (auto-created if not exists)')
    store_id: Optional[str] = Field(default=None, description='Existing store ID (skip auto-create)')
    model_id: Optional[str] = Field(default=None, description='Existing model ID (skip auto-write)')
    force_write_model: bool = Field(
        default=False,
        description='Write a fresh authorization model on startup even when the store already has models',
    )
    timeout: int = Field(default=5, description='HTTP request timeout in seconds')

    # F013 (v2.5.1) — Dual-model gray release. During the 2-week window after
    # upgrading the authorization model (e.g. v1 → v2 with tenant.shared_to and
    # the resource viewer narrowing), tuple writes go to BOTH model_id and
    # legacy_model_id, while permission checks still run against model_id only.
    # Operators flip the switch by setting both fields and toggling
    # dual_model_mode=true. Rollback to the legacy model is achieved by setting
    # model_id back to legacy_model_id and disabling dual mode.
    dual_model_mode: bool = Field(
        default=False,
        description='Enable dual-model gray release: tuple writes mirror to legacy_model_id',
    )
    legacy_model_id: Optional[str] = Field(
        default=None,
        description='Previous authorization model id, used during gray period; '
                    'effective only when dual_model_mode=true',
    )


class OpenFgaGuardConf(BaseModel):
    """Overload protection for OpenFGA, editable from the system config page.

    Lives in the DB-backed system config (``initdb_config``) rather than in
    config.yaml so operators can retune the ceiling during an incident without
    restarting the API. Defaults are deliberately generous: the guard exists to
    turn a crash into a "try again shortly" notice, not to police normal usage.
    """

    enabled: bool = Field(default=True, description='Whether to shed load when OpenFGA is saturated')
    max_in_flight: int = Field(
        default=512,
        ge=1,
        description='Max concurrent OpenFGA requests per process. Cluster ceiling is this '
                    'value times the number of API and Celery processes',
    )
    reject_ratio: float = Field(
        default=0.9,
        ge=0.05,
        le=1.0,
        description='Occupancy at which new requests are turned away; also the percentage '
                    'shown in the user-facing notice',
    )
    acquire_timeout: float = Field(
        default=20.0,
        gt=0,
        description='Seconds an outbound call may wait for a free slot before being rejected',
    )
