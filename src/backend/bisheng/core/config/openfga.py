"""OpenFGA configuration model."""


from pydantic import BaseModel, Field

_SHA256_PATTERN = r'^[0-9a-f]{64}$'


class OpenFGAConf(BaseModel):
    """OpenFGA connection and behavior configuration."""

    enabled: bool = Field(default=True, description='Whether to enable OpenFGA integration')
    api_url: str = Field(default='http://openfga:8080', description='OpenFGA HTTP API URL')
    store_name: str = Field(default='bisheng', description='Store name (auto-created if not exists)')
    store_id: str | None = Field(default=None, description='Existing store ID (skip auto-create)')
    model_id: str | None = Field(default=None, description='Existing model ID (skip auto-write)')
    model_checksum: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
        description='Lowercase SHA-256 of the single runtime authorization model',
    )
    current_catalog_release_id: int | None = Field(
        default=None,
        gt=0,
        description='SQL identifier of the only current permission Catalog release',
    )
    current_catalog_checksum: str | None = Field(
        default=None,
        pattern=_SHA256_PATTERN,
        description='Lowercase SHA-256 of the current permission Catalog release',
    )
    recent_consistency_window_seconds: int = Field(
        default=35,
        ge=1,
        le=300,
        description='Recent-change marker window used to request higher consistency',
    )
    force_write_model: bool = Field(
        default=False,
        description='Write a fresh authorization model on startup even when the store already has models',
    )
    timeout: int = Field(default=5, description='HTTP request timeout in seconds')

    # Retired F013 configuration keys remain parseable only so an old deployment
    # fails with an explicit startup error. F048 never constructs a second
    # client, mirrors writes, or permits repinning to the predecessor model.
    dual_model_mode: bool = Field(
        default=False,
        description='Retired; F048 requires false',
    )
    legacy_model_id: str | None = Field(
        default=None,
        description='Retired; F048 requires an empty value',
    )

    def validate_production_runtime_pin(self) -> None:
        """Reject startup unless the F048 production runtime is fully pinned.

        Development and migration commands may still construct a partially
        configured object. Production startup calls this explicit gate before
        constructing an OpenFGA client.
        """

        missing = [
            field
            for field, value in (
                ('store_id', self.store_id),
                ('model_id', self.model_id),
                ('model_checksum', self.model_checksum),
                ('current_catalog_release_id', self.current_catalog_release_id),
                ('current_catalog_checksum', self.current_catalog_checksum),
            )
            if value is None
        ]
        if missing:
            raise ValueError(f"OpenFGA production runtime pin is incomplete: {', '.join(missing)}")
        if self.force_write_model:
            raise ValueError('OpenFGA production runtime cannot auto-write an authorization model')
        if self.dual_model_mode:
            raise ValueError('OpenFGA production runtime cannot enable dual-model writes')
        if self.legacy_model_id:
            raise ValueError('OpenFGA production runtime cannot configure a legacy model')
