from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from bisheng.knowledge.domain.services.knowledge_migration_service import (
    require_system_admin,
    sanitize_error_summary,
)


class FakeUser:
    def __init__(self, is_admin: bool):
        self._is_admin = is_admin

    def is_admin(self):
        return self._is_admin


def test_system_admin_gate_uses_login_user_admin_role_only():
    user = FakeUser(True)

    assert require_system_admin(user) is user


@pytest.mark.parametrize(
    "user",
    [
        FakeUser(False),
        SimpleNamespace(account="admin", user_role=["管理员"]),
        None,
    ],
)
def test_system_admin_gate_rejects_account_or_display_role_bypass(user):
    with pytest.raises(HTTPException) as exc_info:
        require_system_admin(user)

    assert exc_info.value.status_code == 403


def test_error_summary_redacts_credentials_urls_paths_and_object_keys():
    summary = sanitize_error_summary(
        "copy failed token=abc123 password:secret "
        "Bearer jwt.value at https://storage.local/a "
        "/srv/data/private/file original/123.pdf\nTraceback: hidden"
    )

    assert summary is not None
    assert "abc123" not in summary
    assert "secret" not in summary
    assert "jwt.value" not in summary
    assert "storage.local" not in summary
    assert "/srv/data" not in summary
    assert "original/123.pdf" not in summary
    assert "Traceback" not in summary
