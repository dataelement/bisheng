"""Every projection idempotency key must fit the column that stores it.

`channel-membership:<32-hex channel>:<user id>:<model key>:<version>` is 67
characters for a six-digit user id, and the column was `String(64)`. DM8
rejected the insert with `[CODE:-6108] String truncated` after the approval had
already been committed, so a channel subscription that was approved ended up
displayed as "处理异常" (`approval_instance.status = execute_failed`). Small user
ids fit, which is why it only appeared once six-digit accounts subscribed.
"""

from __future__ import annotations

import pytest

from bisheng.channel.domain.services.f048_channel_permission import (
    build_channel_membership_idempotency_key,
)
from bisheng.permission.domain.models.projection import PermissionProjectionOperation

_CHANNEL_ID = "70b0130ff3344001b368891803520eee"  # ids are 32 hex characters


def _column_width() -> int:
    column = PermissionProjectionOperation.__table__.c["idempotency_key"]
    return int(column.type.length)


@pytest.mark.parametrize("model_key", ["owner", "manager", "viewer", None])
def test_channel_membership_key_fits_the_column(model_key):
    key = build_channel_membership_idempotency_key(
        resource_id=_CHANNEL_ID,
        subject_user_id=999_999_999,
        model_key=model_key,
        permission_version=999_999,
    )
    assert len(key) <= _column_width(), f"{len(key)} > {_column_width()}: {key}"


def test_the_key_that_broke_production_fits():
    key = build_channel_membership_idempotency_key(
        resource_id=_CHANNEL_ID,
        subject_user_id=150041,
        model_key="viewer",
        permission_version=1,
    )
    assert key == "channel-membership:70b0130ff3344001b368891803520eee:150041:viewer:1"
    assert len(key) == 67
    assert len(key) <= _column_width()


def test_a_removal_still_names_itself():
    key = build_channel_membership_idempotency_key(
        resource_id=_CHANNEL_ID,
        subject_user_id=7,
        model_key=None,
        permission_version=3,
    )
    assert key.endswith(":remove:3")
    assert len(key) <= _column_width()
