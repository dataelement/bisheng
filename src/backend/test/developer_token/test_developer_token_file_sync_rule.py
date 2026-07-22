from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from bisheng.common.errcode.developer_token import DeveloperTokenInvalidFileSyncRuleError
from bisheng.developer_token.domain.models import DeveloperToken
from bisheng.developer_token.domain.schemas import (
    DeveloperTokenCreate,
    DeveloperTokenFileSyncRule,
    DeveloperTokenUpdate,
)
from bisheng.developer_token.domain.services.developer_token_service import DeveloperTokenService


@pytest.mark.parametrize(
    "payload",
    [
        {
            "category": {"code": " policy ", "subcategory_code": " mgmt-policy "},
            "business_domain": {"mode": "fixed", "code": " sa "},
            "target_space": {"mode": "fixed", "knowledge_id": 118},
            "dynamic_source": None,
        },
        {
            "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY"},
            "business_domain": {"mode": "fixed", "code": "SA"},
            "target_space": {"mode": "dynamic", "knowledge_id": None},
            "dynamic_source": "department_id",
        },
        {
            "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY"},
            "business_domain": {"mode": "dynamic", "code": None},
            "target_space": {"mode": "fixed", "knowledge_id": 118},
            "dynamic_source": "responsible_person_id",
        },
        {
            "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY"},
            "business_domain": {"mode": "dynamic", "code": None},
            "target_space": {"mode": "dynamic", "knowledge_id": None},
            "dynamic_source": "department_id",
        },
    ],
)
def test_rule_schema_accepts_all_mode_combinations_and_normalizes_codes(payload) -> None:
    rule = DeveloperTokenFileSyncRule.model_validate(payload)

    assert rule.category.code == "POLICY"
    assert rule.category.subcategory_code in {"MGMT-POLICY", "MGMT_POLICY"}
    if rule.business_domain.code:
        assert rule.business_domain.code == "SA"


def test_folder_id_is_backward_compatible_and_fixed_target_accepts_a_directory() -> None:
    old_rule = DeveloperTokenFileSyncRule.model_validate(
        {
            "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY"},
            "business_domain": {"mode": "fixed", "code": "SA"},
            "target_space": {"mode": "fixed", "knowledge_id": 118},
            "dynamic_source": None,
        }
    )
    folder_rule = DeveloperTokenFileSyncRule.model_validate(
        {
            "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY"},
            "business_domain": {"mode": "fixed", "code": "SA"},
            "target_space": {"mode": "fixed", "knowledge_id": 118, "folder_id": 4096},
            "dynamic_source": None,
        }
    )

    assert old_rule.target_space.folder_id is None
    assert folder_rule.target_space.folder_id == 4096


def test_dynamic_target_rejects_a_folder_id_with_19813() -> None:
    rule = DeveloperTokenFileSyncRule.model_validate(
        {
            "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY"},
            "business_domain": {"mode": "fixed", "code": "SA"},
            "target_space": {"mode": "dynamic", "knowledge_id": None, "folder_id": 4096},
            "dynamic_source": "department_id",
        }
    )

    with pytest.raises(DeveloperTokenInvalidFileSyncRuleError) as exc_info:
        DeveloperTokenService._normalize_file_sync_rule(rule)

    assert exc_info.value.code == 19813


@pytest.mark.parametrize(
    "payload",
    [
        {
            "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY", "label": "x"},
            "business_domain": {"mode": "fixed", "code": "SA"},
            "target_space": {"mode": "fixed", "knowledge_id": 118},
            "dynamic_source": None,
        },
        {
            "category": {"code": "bad/code", "subcategory_code": "MGMT_POLICY"},
            "business_domain": {"mode": "fixed", "code": "SA"},
            "target_space": {"mode": "fixed", "knowledge_id": 118},
            "dynamic_source": None,
        },
        {
            "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY"},
            "business_domain": {"mode": "fixed", "code": "SA"},
            "target_space": {"mode": "fixed", "knowledge_id": 0},
            "dynamic_source": None,
        },
        {
            "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY"},
            "business_domain": {"mode": "sometimes", "code": "SA"},
            "target_space": {"mode": "fixed", "knowledge_id": 118},
            "dynamic_source": None,
        },
    ],
)
def test_rule_schema_rejects_unknown_fields_invalid_codes_and_types(payload) -> None:
    with pytest.raises(ValidationError):
        DeveloperTokenFileSyncRule.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY"},
            "business_domain": {"mode": "fixed", "code": None},
            "target_space": {"mode": "fixed", "knowledge_id": 118},
            "dynamic_source": None,
        },
        {
            "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY"},
            "business_domain": {"mode": "dynamic", "code": "SA"},
            "target_space": {"mode": "fixed", "knowledge_id": 118},
            "dynamic_source": "department_id",
        },
        {
            "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY"},
            "business_domain": {"mode": "fixed", "code": "SA"},
            "target_space": {"mode": "fixed", "knowledge_id": 118},
            "dynamic_source": "department_id",
        },
        {
            "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY"},
            "business_domain": {"mode": "dynamic", "code": None},
            "target_space": {"mode": "dynamic", "knowledge_id": None},
            "dynamic_source": None,
        },
    ],
)
def test_rule_truth_table_errors_use_19813(payload) -> None:
    rule = DeveloperTokenFileSyncRule.model_validate(payload)

    with pytest.raises(DeveloperTokenInvalidFileSyncRuleError) as exc_info:
        DeveloperTokenService._normalize_file_sync_rule(rule)

    assert exc_info.value.code == 19813


@pytest.mark.asyncio
async def test_fixed_references_and_bidirectional_binding_are_validated(monkeypatch) -> None:
    config = SimpleNamespace(
        portal=SimpleNamespace(
            document_types=[
                SimpleNamespace(
                    code="POLICY",
                    children=[SimpleNamespace(code="MGMT_POLICY")],
                )
            ],
            domains=[SimpleNamespace(code="SA", enabled=True, space_ids=[118])],
        )
    )
    spaces = [SimpleNamespace(id=118, name="安全库", business_domain_codes=["SA"])]
    monkeypatch.setattr(
        DeveloperTokenService,
        "_get_file_sync_portal_config",
        AsyncMock(return_value=config),
    )
    monkeypatch.setattr(
        DeveloperTokenService,
        "_get_file_sync_space",
        AsyncMock(return_value=spaces[0]),
    )
    rule = DeveloperTokenFileSyncRule.model_validate(
        {
            "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY"},
            "business_domain": {"mode": "fixed", "code": "SA"},
            "target_space": {"mode": "fixed", "knowledge_id": 118},
            "dynamic_source": None,
        }
    )

    monkeypatch.setattr(
        DeveloperTokenService,
        "_validate_file_sync_target",
        AsyncMock(return_value=spaces[0]),
        raising=False,
    )
    normalized = await DeveloperTokenService._validate_file_sync_rule(5, 7, rule)

    assert normalized == rule.model_dump(mode="json")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("document_types", "domains", "spaces"),
    [
        ([], [SimpleNamespace(code="SA", enabled=True, space_ids=[118])], [SimpleNamespace(id=118)]),
        (
            [SimpleNamespace(code="POLICY", children=[])],
            [SimpleNamespace(code="SA", enabled=True, space_ids=[118])],
            [SimpleNamespace(id=118)],
        ),
        (
            [SimpleNamespace(code="POLICY", children=[SimpleNamespace(code="MGMT_POLICY")])],
            [],
            [SimpleNamespace(id=118)],
        ),
        (
            [SimpleNamespace(code="POLICY", children=[SimpleNamespace(code="MGMT_POLICY")])],
            [SimpleNamespace(code="SA", enabled=True, space_ids=[118])],
            [],
        ),
        (
            [SimpleNamespace(code="POLICY", children=[SimpleNamespace(code="MGMT_POLICY")])],
            [SimpleNamespace(code="SA", enabled=True, space_ids=[])],
            [SimpleNamespace(id=118, business_domain_codes=["SA"])],
        ),
        (
            [SimpleNamespace(code="POLICY", children=[SimpleNamespace(code="MGMT_POLICY")])],
            [SimpleNamespace(code="SA", enabled=True, space_ids=[118])],
            [SimpleNamespace(id=118, business_domain_codes=[])],
        ),
    ],
)
async def test_invalid_or_unbound_fixed_references_fail_closed(
    monkeypatch,
    document_types,
    domains,
    spaces,
) -> None:
    config = SimpleNamespace(portal=SimpleNamespace(document_types=document_types, domains=domains))
    monkeypatch.setattr(
        DeveloperTokenService,
        "_get_file_sync_portal_config",
        AsyncMock(return_value=config),
    )
    monkeypatch.setattr(
        DeveloperTokenService,
        "_validate_file_sync_target",
        AsyncMock(return_value=spaces[0] if spaces else None),
        raising=False,
    )
    rule = DeveloperTokenFileSyncRule.model_validate(
        {
            "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY"},
            "business_domain": {"mode": "fixed", "code": "SA"},
            "target_space": {"mode": "fixed", "knowledge_id": 118},
            "dynamic_source": None,
        }
    )

    with pytest.raises(DeveloperTokenInvalidFileSyncRuleError):
        await DeveloperTokenService._validate_file_sync_rule(5, 7, rule)


@pytest.mark.asyncio
async def test_fixed_folder_is_validated_for_bound_user_before_persistence(monkeypatch) -> None:
    config = SimpleNamespace(
        portal=SimpleNamespace(
            document_types=[SimpleNamespace(code="POLICY", children=[SimpleNamespace(code="MGMT_POLICY")])],
            domains=[SimpleNamespace(code="SA", enabled=True, space_ids=[118])],
        )
    )
    space = SimpleNamespace(id=118, business_domain_codes=["SA"])
    target_validation = AsyncMock(return_value=space)
    monkeypatch.setattr(
        DeveloperTokenService,
        "_get_file_sync_portal_config",
        AsyncMock(return_value=config),
    )
    monkeypatch.setattr(
        DeveloperTokenService,
        "_validate_file_sync_target",
        target_validation,
        raising=False,
    )
    rule = DeveloperTokenFileSyncRule.model_validate(
        {
            "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY"},
            "business_domain": {"mode": "fixed", "code": "SA"},
            "target_space": {"mode": "fixed", "knowledge_id": 118, "folder_id": 4096},
            "dynamic_source": None,
        }
    )

    normalized = await DeveloperTokenService._validate_file_sync_rule(5, 7, rule)

    target_validation.assert_awaited_once_with(
        tenant_id=5,
        user_id=7,
        knowledge_id=118,
        folder_id=4096,
    )
    assert normalized["target_space"]["folder_id"] == 4096


@pytest.mark.asyncio
async def test_create_persists_normalized_rule(monkeypatch) -> None:
    saved = {}

    class Repo:
        @staticmethod
        async def create_token(token):
            token.id = 1
            saved["token"] = token
            return token

    rule = {
        "category": {"code": " policy ", "subcategory_code": " mgmt_policy "},
        "business_domain": {"mode": "dynamic", "code": None},
        "target_space": {"mode": "dynamic", "knowledge_id": None},
        "dynamic_source": "department_id",
    }
    operator = SimpleNamespace(user_id=10, tenant_id=5)
    monkeypatch.setattr(DeveloperTokenService, "repository", Repo)
    monkeypatch.setattr(DeveloperTokenService, "_resolve_binding_tenant", AsyncMock(return_value=5))
    monkeypatch.setattr(DeveloperTokenService, "_assert_admin_scope", AsyncMock())
    monkeypatch.setattr(
        DeveloperTokenService,
        "_validate_file_sync_rule",
        AsyncMock(side_effect=lambda _tenant_id, _user_id, value: value.model_dump(mode="json")),
    )
    monkeypatch.setattr(DeveloperTokenService, "_audit", AsyncMock())
    monkeypatch.setattr(
        DeveloperTokenService,
        "_to_read",
        AsyncMock(
            return_value={
                "id": 1,
                "tenant_id": 5,
                "user_id": 7,
                "name": "sync",
                "token_prefix": "bst_test",
                "enabled": True,
                "override_ip_whitelist": False,
                "override_rate_limit": False,
            }
        ),
    )

    await DeveloperTokenService.create_token(
        operator,
        DeveloperTokenCreate(name="sync", user_id=7, department_id=20, file_sync_rule=rule),
    )

    assert saved["token"].file_sync_rule["category"] == {
        "code": "POLICY",
        "subcategory_code": "MGMT_POLICY",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "expected_rule"),
    [
        (DeveloperTokenUpdate(name="renamed"), "existing"),
        (DeveloperTokenUpdate(file_sync_rule=None), None),
    ],
)
async def test_update_distinguishes_omitted_rule_from_explicit_null(
    monkeypatch,
    payload,
    expected_rule,
) -> None:
    existing_rule = {
        "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY"},
        "business_domain": {"mode": "fixed", "code": "SA"},
        "target_space": {"mode": "fixed", "knowledge_id": 118},
        "dynamic_source": None,
    }
    existing = DeveloperToken(
        id=1,
        tenant_id=5,
        user_id=7,
        name="sync",
        token_hash="hash",
        token_ciphertext="cipher",
        token_prefix="bst_test",
        file_sync_rule=existing_rule,
    )
    updated_fields = {}

    class Repo:
        @staticmethod
        async def get_token_by_id(_token_id):
            return existing

        @staticmethod
        async def update_token(_token_id, **fields):
            updated_fields.update(fields)
            for key, value in fields.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            return existing

    validate = AsyncMock(
        side_effect=lambda _tenant_id, _user_id, value: (
            value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        )
    )
    monkeypatch.setattr(DeveloperTokenService, "repository", Repo)
    monkeypatch.setattr(DeveloperTokenService, "_assert_admin_scope", AsyncMock())
    monkeypatch.setattr(DeveloperTokenService, "_validate_file_sync_rule", validate)
    monkeypatch.setattr(DeveloperTokenService, "_audit", AsyncMock())
    monkeypatch.setattr(DeveloperTokenService, "_to_read", AsyncMock(return_value=SimpleNamespace(id=1)))

    await DeveloperTokenService.update_token(1, SimpleNamespace(user_id=10), payload)

    if expected_rule == "existing":
        assert "file_sync_rule" not in updated_fields
        assert validate.await_args.args[1:] == (7, existing_rule)
    else:
        assert updated_fields["file_sync_rule"] is None
        assert validate.await_args.args[1:] == (7, None)


@pytest.mark.asyncio
async def test_rebinding_same_tenant_revalidates_existing_target_for_new_user(monkeypatch) -> None:
    existing_rule = {
        "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY"},
        "business_domain": {"mode": "fixed", "code": "SA"},
        "target_space": {"mode": "fixed", "knowledge_id": 118, "folder_id": 4096},
        "dynamic_source": None,
    }
    existing = DeveloperToken(
        id=1,
        tenant_id=5,
        user_id=7,
        name="sync",
        token_hash="hash",
        token_ciphertext="cipher",
        token_prefix="bst_test",
        file_sync_rule=existing_rule,
    )

    class Repo:
        @staticmethod
        async def get_token_by_id(_token_id):
            return existing

        @staticmethod
        async def update_token(_token_id, **fields):
            for key, value in fields.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            return existing

    validate = AsyncMock(return_value=existing_rule)
    monkeypatch.setattr(DeveloperTokenService, "repository", Repo)
    monkeypatch.setattr(DeveloperTokenService, "_assert_admin_scope", AsyncMock())
    monkeypatch.setattr(DeveloperTokenService, "_resolve_binding_tenant", AsyncMock(return_value=5))
    monkeypatch.setattr(DeveloperTokenService, "_validate_file_sync_rule", validate)
    monkeypatch.setattr(DeveloperTokenService, "_audit", AsyncMock())
    monkeypatch.setattr(DeveloperTokenService, "_to_read", AsyncMock(return_value=SimpleNamespace(id=1)))

    await DeveloperTokenService.update_token(
        1,
        SimpleNamespace(user_id=10),
        DeveloperTokenUpdate(user_id=8, department_id=20),
    )

    validate.assert_awaited_once_with(5, 8, existing_rule)


def test_audit_snapshot_contains_only_rule_summary() -> None:
    rule = {
        "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY"},
        "business_domain": {"mode": "fixed", "code": "SA"},
        "target_space": {"mode": "fixed", "knowledge_id": 118},
        "dynamic_source": None,
    }
    token = DeveloperToken(
        id=1,
        tenant_id=5,
        user_id=7,
        name="sync",
        token_hash="hash",
        token_ciphertext="cipher",
        token_prefix="bst_test",
        file_sync_rule=rule,
    )

    snapshot = DeveloperTokenService._non_secret_snapshot(token)

    assert snapshot["file_sync_rule_configured"] is True
    assert snapshot["file_sync_rule_summary"] == {
        "category_code": "POLICY",
        "subcategory_code": "MGMT_POLICY",
        "business_domain_mode": "fixed",
        "target_space_mode": "fixed",
        "dynamic_source": None,
    }
    assert "file_sync_rule" not in snapshot
