"""Document-parse (OCR / ETL) settings payloads.

They live in the knowledge domain, not next to the endpoints: the settings
service validates and persists them, and a domain module must not import the
API layer (constitution C1).
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class DocumentParseConfig(BaseModel):
    """Structured document-parse (OCR / ETL) settings for the admin form.

    Token material is deliberately absent: only the *name* of the environment
    variable is stored, so the secret never reaches the config file, a database
    dump, or this API's payload.
    """

    loader_provider: Literal["etl4lm", "mineru", "mineru_v4", "paddle_ocr"] = Field(
        description="Document parsing provider used by the knowledge pipeline"
    )
    paddle_ocr_url: str = Field(default="", max_length=500, description="PaddleOCR service URL")
    paddle_ocr_model: str = Field(default="", max_length=200, description="PaddleOCR model name (jobs API)")
    paddle_ocr_api_key_env: str = Field(
        default="", max_length=200, description="Environment variable holding the PaddleOCR token"
    )
    paddle_ocr_token: str | None = Field(
        default=None,
        max_length=4000,
        description=(
            "Write-only: a token typed in the form. Stored encrypted; never returned by the "
            "read endpoint. Leave empty to keep the current token."
        ),
    )
    paddle_ocr_clear_token: bool = Field(default=False, description="Write-only: remove the stored token")
    paddle_ocr_service_mode: Literal["auto", "jobs", "sync"] = Field(
        default="auto", description="PaddleOCR serving style; auto detects from the URL"
    )
    paddle_ocr_timeout: int = Field(default=60, ge=1, description="Per-request timeout (sec)")
    paddle_ocr_max_retries: int = Field(default=3, ge=0, description="Retries for transient errors")
    paddle_ocr_retry_backoff: float = Field(default=1.0, ge=0, description="Initial retry delay (sec)")
    paddle_ocr_poll_interval_seconds: float = Field(default=3, gt=0, description="Jobs API poll interval (sec)")
    paddle_ocr_job_timeout_seconds: float = Field(default=1800, gt=0, description="Overall jobs API deadline (sec)")

    # --- etl4lm ---------------------------------------------------------------
    etl4lm_url: str = Field(default="", max_length=500, description="ETL4LM service URL")
    etl4lm_timeout: int = Field(default=600, ge=1, description="ETL4LM request timeout (sec)")
    etl4lm_ocr_sdk_url: str = Field(
        default="", max_length=500, description="Optional high-accuracy OCR SDK address used by ETL4LM"
    )

    # --- mineru (PP-StructureV3 style sync service) ---------------------------
    mineru_url: str = Field(default="", max_length=500, description="MinerU service URL")
    mineru_timeout: int = Field(default=60, ge=1, description="MinerU request timeout (sec)")
    mineru_api_key_header: str = Field(default="x-api-key", max_length=100, description="Header carrying the key")
    mineru_token: str | None = Field(default=None, max_length=4000, description="Write-only API key")
    mineru_clear_token: bool = Field(default=False, description="Write-only: remove the stored key")
    mineru_backend: str = Field(
        default="", max_length=100, description="Parse backend sent as request_kwargs.backend; empty keeps it"
    )

    # --- mineru_v4 (hosted parse-job API) ------------------------------------
    mineru_v4_api_url: str = Field(default="", max_length=500, description="MinerU V4 API root URL")
    mineru_v4_api_key_env: str = Field(
        default="", max_length=200, description="Environment variable holding the MinerU V4 API key"
    )
    mineru_v4_token: str | None = Field(
        default=None, max_length=4000, description="Write-only API key; empty keeps the stored one"
    )
    mineru_v4_clear_token: bool = Field(default=False, description="Write-only: remove the stored key")
    mineru_v4_tier: str = Field(default="standard", max_length=50, description="Requested parse tier")
    mineru_v4_model_version: Literal["pipeline", "vlm"] = Field(
        default="pipeline", description="model_version sent to the hosted mineru.net API"
    )
    mineru_v4_ocr_mode: Literal["auto", "txt", "ocr"] = Field(
        default="auto", description="MinerU V4 OCR mode"
    )
    mineru_v4_request_timeout_seconds: float = Field(default=60, gt=0, description="Per-request timeout (sec)")
    mineru_v4_job_timeout_seconds: float = Field(default=1800, gt=0, description="Overall job deadline (sec)")
    mineru_v4_poll_interval_seconds: float = Field(default=3, gt=0, description="Job poll interval (sec)")

    @field_validator(
        "paddle_ocr_url",
        "paddle_ocr_model",
        "paddle_ocr_api_key_env",
        "paddle_ocr_token",
        "etl4lm_url",
        "etl4lm_ocr_sdk_url",
        "mineru_url",
        "mineru_api_key_header",
        "mineru_token",
        "mineru_backend",
        "mineru_v4_api_url",
        "mineru_v4_api_key_env",
        "mineru_v4_token",
        "mineru_v4_tier",
    )
    @classmethod
    def strip_value(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def require_jobs_fields(self) -> "DocumentParseConfig":
        """Reject a jobs deployment with no model, at save time.

        A token is *not* required here: it may already be stored, or arrive later
        through the environment. The endpoint checks that at least one source
        exists, because only it can see the stored ciphertext.
        """
        if self.loader_provider != "paddle_ocr":
            return self
        if self.paddle_ocr_service_mode == "sync":
            return self
        if not self.paddle_ocr_url.rstrip("/").endswith("/jobs") and self.paddle_ocr_service_mode == "auto":
            return self
        if not self.paddle_ocr_model:
            raise ValueError("Model is required when parsing documents through the PaddleOCR jobs API")
        return self


class DocumentParseTestResult(BaseModel):
    """Outcome of the admin form's "test connection" action."""

    status: Literal[
        "ok", "token_missing", "token_invalid", "model_invalid", "unreachable", "misconfigured", "error"
    ] = Field(description="Machine-readable outcome; the UI localizes it")
    message: str = Field(default="", description="Provider or transport detail for troubleshooting")
    latency_ms: int = Field(default=0, ge=0, description="Round-trip time of the probe")
