from datetime import UTC, date

from bisheng.commercial_license.domain.mappers import (
    compute_display_state,
    map_etl_payload,
    map_gateway_payload,
)

TODAY = date(2026, 9, 14)


def test_remaining_31_is_normal():
    assert compute_display_state(date(2026, 10, 15), 31, TODAY) == "normal"


def test_remaining_30_and_1_are_expiring():
    assert compute_display_state(date(2026, 10, 14), 30, TODAY) == "expiring"
    assert compute_display_state(date(2026, 9, 15), 1, TODAY) == "expiring"


def test_zero_and_gateway_negative_are_expired():
    assert compute_display_state(date(2026, 9, 14), 0, TODAY) == "expired"
    assert compute_display_state(date(2026, 7, 2), -74, TODAY) == "expired"


def test_no_expire_and_no_days_is_normal_perpetual():
    assert compute_display_state(None, None, TODAY) == "normal"


def test_gateway_maps_expire_day_and_strips_secrets():
    mapped = map_gateway_payload(
        {
            "version": "trial",
            "expire_day": "2026-07-02",
            "days_remaining": -74,
            "severity": "expired",
            "expired": True,
            "checked_at": "2026-09-14T10:00:00+08:00",
            "private_key": "should-not-store",
            "fingerprint": "abc",
        },
        today=TODAY,
    )
    assert mapped["license_code"] == "gateway"
    assert mapped["expire_date"] == date(2026, 7, 2)
    assert mapped["days_remaining"] == -74
    assert mapped["display_state"] == "expired"
    assert mapped["source_status"] == "expired"
    assert "private_key" not in mapped["extra"]
    assert "fingerprint" not in mapped["extra"]
    assert mapped["extra"]["version"] == "trial"


def test_gateway_pro_without_expire_is_normal():
    mapped = map_gateway_payload({"version": "pro", "expire_day": None, "days_remaining": None}, today=TODAY)
    assert mapped["display_state"] == "normal"
    assert mapped["expire_date"] is None


def test_etl_unix_expiration_and_zero_remaining():
    from datetime import datetime

    expiration_time = int(datetime(2026, 9, 14, tzinfo=UTC).timestamp())
    mapped = map_etl_payload(
        {
            "license_type": "trial",
            "expiration_time": expiration_time,
            "remaining_days": 0,
            "expired": True,
            "usable": False,
            "disabled": False,
            "secret": "nope",
        },
        today=TODAY,
    )
    assert mapped["license_code"] == "etl"
    assert mapped["expire_date"] == date(2026, 9, 14)
    assert mapped["days_remaining"] == 0
    assert mapped["display_state"] == "expired"
    assert mapped["source_status"] == "trial"
    assert "secret" not in mapped["extra"]
    assert mapped["extra"]["usable"] is False


def test_etl_perpetual_null_expiration_is_normal():
    mapped = map_etl_payload(
        {
            "license_type": "perpetual",
            "expiration_time": None,
            "remaining_days": None,
            "expired": False,
            "usable": True,
        },
        today=TODAY,
    )
    assert mapped["expire_date"] is None
    assert mapped["display_state"] == "normal"
