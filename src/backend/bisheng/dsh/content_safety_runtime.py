"""Lazy service assembly and shared-HMAC authentication for safety callbacks."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import ValidationError

from bisheng.common.errcode.dsh import (
    DshContentSafetyAuthError,
    DshContentSafetyInvalidEventError,
    DshContentSafetyTooLargeError,
    DshContentSafetyUnavailableError,
)
from bisheng.common.utils.hmac_signature import compare_hmac_signatures, compute_hmac_signature
from bisheng.core.context.tenant import DEFAULT_TENANT_ID
from bisheng.dsh.domain.schemas.content_safety import MAX_EVENT_BYTES, ContentSafetyEnvelope
from bisheng.dsh.domain.services.content_safety_ingest import ContentSafetyIngestService, VerifiedSource

CONTENT_SAFETY_PATH = "/api/v1/internal/dsh/content-safety-events"


@dataclass(frozen=True)
class VerifiedSafetyEnvelope:
    raw_event: dict
    verified_source: VerifiedSource


def get_settings():
    # Loading this module never activates SSO, model admission or model storage.
    from bisheng.common.services.config_service import settings

    return settings


def _session_factory():
    from bisheng.core.database import get_sync_db_session

    return get_sync_db_session()


def get_content_safety_service(*, session_factory=None):
    return ContentSafetyIngestService(_session_factory if session_factory is None else session_factory)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate safety JSON key")
        result[key] = value
    return result


def _invalid_number(_value):
    raise ValueError("Safety JSON requires exact integers")


def verify_source(raw, headers, method, path, *, now=None):
    """Authenticate exact wire bytes before parsing; preserve the original event."""
    if not isinstance(raw, bytes):
        raise DshContentSafetyInvalidEventError()
    if len(raw) > MAX_EVENT_BYTES:
        raise DshContentSafetyTooLargeError()
    if not isinstance(method, str) or method.upper() != "POST" or path != CONTENT_SAFETY_PATH:
        raise DshContentSafetyAuthError()
    settings = get_settings()
    config = getattr(settings, "sso_sync", None)
    secret = getattr(config, "gateway_hmac_secret", None)
    header = getattr(config, "signature_header", None) or "X-Signature"
    if not isinstance(secret, str) or not secret.strip() or not isinstance(header, str):
        raise DshContentSafetyUnavailableError()
    if not isinstance(headers, Mapping):
        raise DshContentSafetyAuthError()
    values = [value for key, value in headers.items() if isinstance(key, str) and key.lower() == header.lower()]
    if len(values) != 1 or not compare_hmac_signatures(compute_hmac_signature(method, path, raw, secret), values[0]):
        raise DshContentSafetyAuthError()
    try:
        payload = json.loads(
            raw.decode("utf8"), object_pairs_hook=_object, parse_float=_invalid_number, parse_constant=_invalid_number
        )
        validated = ContentSafetyEnvelope.model_validate(payload)
        sent_at = datetime.fromisoformat(validated.sent_at.replace("Z", "+00:00"))
    except (ValueError, TypeError, UnicodeError, RecursionError, ValidationError):
        raise DshContentSafetyInvalidEventError() from None
    observed = now if now is not None else datetime.now(UTC)
    if not isinstance(observed, datetime) or observed.tzinfo is None:
        raise DshContentSafetyUnavailableError()
    if abs((observed - sent_at).total_seconds()) > 300:
        raise DshContentSafetyAuthError()
    tenant = int(validated.event.tenant_id)
    if not getattr(getattr(settings, "multi_tenant", None), "enabled", False) and tenant != DEFAULT_TENANT_ID:
        raise DshContentSafetyAuthError.tenant_forbidden()
    # Never reserialize the validated DTO: defaults/hint cleaning change the hash.
    return VerifiedSafetyEnvelope(payload["event"], VerifiedSource(validated.event.source_id, tenant))
