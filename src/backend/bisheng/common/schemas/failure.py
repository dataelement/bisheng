"""Versioned public failure metadata, separate from recovery policy."""

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class FailureCategory(StrEnum):
    DATABASE = "database"
    NETWORK = "network"
    MODEL_SERVICE = "model_service"
    SSO = "sso"
    OBJECT_STORAGE = "object_storage"


class FailureReason(StrEnum):
    CONNECTION_FAILED = "connection_failed"
    TIMEOUT = "timeout"
    INVALID_RESPONSE = "invalid_response"
    SERVICE_UNAVAILABLE = "service_unavailable"
    RATE_LIMIT = "rate_limit"
    AUTHENTICATION_FAILED = "authentication_failed"
    ACCESS_DENIED = "access_denied"
    MODEL_UNAVAILABLE = "model_unavailable"
    BALANCE_EXHAUSTED = "balance_exhausted"
    PLATFORM_QUOTA = "platform_quota"
    CONTEXT_LIMIT = "context_limit"
    CAPABILITY_MISMATCH = "capability_mismatch"
    CONTENT_REJECTED = "content_rejected"
    RETRIEVAL_FAILED = "retrieval_failed"
    PARSE_BUSY = "parse_busy"
    PARSE_FAILED = "parse_failed"
    INVALID_FILE = "invalid_file"
    LOGIN_EXPIRED = "login_expired"
    RESOURCE_MISSING = "resource_missing"
    TOOL_FAILED = "tool_failed"
    UNKNOWN = "unknown"


class FailureInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: int = 1
    failure_id: str
    category: FailureCategory
    occurred_at: str
    service: str | None = None
    service_name: str | None = None
    operation: str | None = None
    trace_id: str | None = None


@dataclass(frozen=True)
class FailureContext:
    """Internal provenance; the exception itself stays on the existing chain."""

    info: dict | None
    reason: FailureReason
    exception_type: str
