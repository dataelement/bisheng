from unittest.mock import MagicMock

import pytest

from bisheng.common.errcode.role import QuotaConfigInvalidError
from bisheng.role.domain.services.quota_service import QuotaService


def test_role_priority_config_accepts_enum_and_preserves_existing_quota() -> None:
    config = {
        "channel": 10,
        "menu_approval_mode": True,
        "knowledge_file_parse_priority": "high",
    }

    QuotaService.validate_role_quota_config(config)


@pytest.mark.parametrize("value", ["urgent", 3, True, None])
def test_role_priority_config_rejects_invalid_values(value: object) -> None:
    with pytest.raises(QuotaConfigInvalidError):
        QuotaService.validate_role_quota_config({"knowledge_file_parse_priority": value})


def test_tenant_quota_config_rejects_role_priority_key() -> None:
    with pytest.raises(QuotaConfigInvalidError):
        QuotaService.validate_quota_config({"knowledge_file_parse_priority": "high"})


def test_role_service_uses_role_specific_validator() -> None:
    from bisheng.role.domain.schemas.role_schema import RoleCreateRequest
    from bisheng.role.domain.services.role_service import RoleService

    login_user = MagicMock()
    login_user.user_id = 12
    login_user.tenant_id = 3
    login_user.is_admin.return_value = False
    req = RoleCreateRequest(
        role_name="Priority role",
        quota_config={"knowledge_file_parse_priority": "medium"},
    )

    assert req.quota_config == {"knowledge_file_parse_priority": "medium"}
    assert "validate_role_quota_config" in RoleService.create_role.__func__.__code__.co_names
