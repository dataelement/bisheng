"""OpenFGA configuration model."""

from pydantic import BaseModel, Field


class OpenFGAConf(BaseModel):
    """OpenFGA connection and behavior configuration."""

    enabled: bool = Field(default=True, description="Whether to enable OpenFGA integration")
    api_url: str = Field(default="http://openfga:8080", description="OpenFGA HTTP API URL")
    store_name: str = Field(
        default="bisheng",
        description="Stable Store name; development may auto-create it",
    )
    recent_consistency_window_seconds: int = Field(
        default=35,
        ge=1,
        le=300,
        description="Recent-change marker window used to request higher consistency",
    )
    failed_tuple_succeeded_retention_days: int = Field(
        default=30,
        ge=1,
        le=3650,
        description="Days to retain succeeded OpenFGA compensation records",
    )
    force_write_model: bool = Field(
        default=False,
        description="Write a fresh authorization model on startup even when the store already has models",
    )
    timeout: int = Field(default=5, description="HTTP request timeout in seconds")

    # Retired F013 configuration keys remain parseable only so an old deployment
    # fails with an explicit startup error. F048 never constructs a second
    # client, mirrors writes, or permits repinning to the predecessor model.
    dual_model_mode: bool = Field(
        default=False,
        description="Retired; F048 requires false",
    )
    legacy_model_id: str | None = Field(
        default=None,
        description="Retired; F048 requires an empty value",
    )

    def validate_production_runtime(self) -> None:
        """Reject production-only bootstrap and retired runtime modes."""

        if self.force_write_model:
            raise ValueError("OpenFGA production runtime cannot auto-write an authorization model")
        if self.dual_model_mode:
            raise ValueError("OpenFGA production runtime cannot enable dual-model writes")
        if self.legacy_model_id:
            raise ValueError("OpenFGA production runtime cannot configure a legacy model")
