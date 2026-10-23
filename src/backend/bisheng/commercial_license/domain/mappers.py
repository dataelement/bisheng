from datetime import UTC, date, datetime
from typing import Any

LICENSE_CODES = frozenset({"gateway", "etl", "dashboard"})
SECRET_EXTRA_KEYS = frozenset(
    {
        "secret",
        "private_key",
        "fingerprint",
        "license_key",
        "ciphertext",
        "token",
        "password",
        "api_key",
    }
)
GATEWAY_EXTRA_KEYS = ("version", "expired", "checked_at")
ETL_EXTRA_KEYS = ("expired", "usable", "disabled", "license_type")


def compute_display_state(
    expire_date: date | None,
    days_remaining: int | None,
    today: date,
) -> str:
    days = _effective_days(expire_date, days_remaining, today)
    if days is None:
        return "normal"
    if days > 30:
        return "normal"
    if days >= 1:
        return "expiring"
    return "expired"


def compute_days_remaining(
    expire_date: date | None,
    days_remaining: int | None,
    today: date,
) -> int | None:
    return _effective_days(expire_date, days_remaining, today)


def _effective_days(
    expire_date: date | None,
    days_remaining: int | None,
    today: date,
) -> int | None:
    if expire_date is not None:
        return (expire_date - today).days
    return days_remaining


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    raise ValueError("invalid expire date")


def _unix_to_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    return datetime.fromtimestamp(int(value), tz=UTC).date()


def _safe_extra(payload: dict[str, Any], allowed: tuple[str, ...]) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    for key in allowed:
        if key in payload and key not in SECRET_EXTRA_KEYS:
            extra[key] = payload[key]
    return extra


def map_gateway_payload(payload: dict[str, Any], *, today: date | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict) or not payload:
        raise ValueError("invalid gateway payload")
    today = today or date.today()
    expire_date = _parse_date(payload.get("expire_day"))
    days_remaining = payload.get("days_remaining")
    if days_remaining is not None:
        days_remaining = int(days_remaining)
    display_state = compute_display_state(expire_date, days_remaining, today)
    return {
        "license_code": "gateway",
        "expire_date": expire_date,
        "days_remaining": days_remaining,
        "display_state": display_state,
        "source_status": payload.get("severity"),
        "extra": _safe_extra(payload, GATEWAY_EXTRA_KEYS),
    }


def map_etl_payload(payload: dict[str, Any], *, today: date | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict) or not payload:
        raise ValueError("invalid etl payload")
    today = today or date.today()
    expire_date = _unix_to_date(payload.get("expiration_time"))
    days_remaining = payload.get("remaining_days")
    if days_remaining is not None:
        days_remaining = int(days_remaining)
    license_type = payload.get("license_type")
    if license_type in {"perpetual", "execution"}:
        expire_date = None
        days_remaining = None
        display_state = "normal"
    else:
        display_state = compute_display_state(expire_date, days_remaining, today)
    return {
        "license_code": "etl",
        "expire_date": expire_date,
        "days_remaining": days_remaining,
        "display_state": display_state,
        "source_status": license_type,
        "extra": _safe_extra(payload, ETL_EXTRA_KEYS),
    }
