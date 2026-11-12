"""F016 tenant credit settings: defaults, validation, optimistic locking, audit and isolation."""

import pytest
from pydantic import ValidationError
from sqlmodel import Session, select

from bisheng.common.errcode.dsh import DshOperationConflictError
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.database.models.tenant import Tenant
from bisheng.dsh.domain.models.credit_setting import DshCreditSetting
from bisheng.dsh.domain.models.unified_policy import UnifiedPolicyAudit
from bisheng.dsh.domain.repositories.credit_setting import DshCreditSettingRepository
from bisheng.dsh.domain.schemas.pricing import (
    DEFAULT_CREDIT_VALUE_MICRO,
    DEFAULT_USD_CNY_RATE_MICRO,
    CreditSettingInput,
    CreditSettingState,
    format_micro,
)
from test.dsh.test_subject_policy import subject_store as subject_store


@pytest.fixture
def store(subject_store, monkeypatch):
    for model in (DshCreditSetting, UnifiedPolicyAudit):
        model.__table__.create(subject_store)
    from bisheng.core.database import tenant_filter

    tenant_filter.register_tenant_filter_events()
    # Another fixture can leave the filter initialized with a partial table set when its
    # external variant fails during setup; pin the tables this test relies on.
    monkeypatch.setattr(
        tenant_filter,
        "_tenant_aware_tables",
        tenant_filter._tenant_aware_tables | {"dsh_credit_setting", "dsh_unified_policy_audit"},
    )
    return subject_store


def settings(**changes):
    values = {"version": 0, "currency": "CNY", "credit_value": "0.01", "usd_cny_rate": "7.2", "base_model_id": None}
    values.update(changes)
    return CreditSettingInput.model_validate(values)


def test_missing_row_reads_as_defaults(store):
    with Session(store) as session:
        state = DshCreditSettingRepository(session).effective()
    assert state == CreditSettingState()
    assert state.currency == "CNY"
    assert state.credit_value_micro == DEFAULT_CREDIT_VALUE_MICRO == 10_000
    assert state.usd_cny_rate_micro == DEFAULT_USD_CNY_RATE_MICRO
    assert state.base_model_id is None and state.version == 0


def test_save_creates_versioned_row_and_audit(store):
    with Session(store) as session, session.begin():
        repo = DshCreditSettingRepository(session)
        after = repo.save(20, settings(currency="USD", credit_value="0.001389", usd_cny_rate="7.1", base_model_id=7))
        assert after["version"] == 1
        assert after["currency"] == "USD"
        assert after["credit_value"] == "0.001389"
        assert after["usd_cny_rate"] == "7.1"
        assert after["base_model_id"] == 7
        state = repo.effective()
        assert (state.credit_value_micro, state.usd_cny_rate_micro, state.version) == (1_389, 7_100_000, 1)
        row = session.exec(select(DshCreditSetting)).one()
        assert row.tenant_id == 2 and row.updated_by == 20
        audit = session.exec(select(UnifiedPolicyAudit)).one()
        assert audit.resource == "credit-settings"
        assert audit.before_values["version"] == 0 and audit.after_values["version"] == 1


def test_stale_version_conflicts_and_keeps_committed_value(store):
    with Session(store) as session, session.begin():
        repo = DshCreditSettingRepository(session)
        repo.save(20, settings(credit_value="0.02"))
        with pytest.raises(DshOperationConflictError):
            repo.save(20, settings(version=0, credit_value="0.05"))
        assert repo.effective().credit_value_micro == 20_000
        repo.save(20, settings(version=1, credit_value="0.05"))
        assert repo.effective().credit_value_micro == 50_000


def test_settings_are_private_to_each_tenant(store):
    with Session(store) as session, session.begin():
        DshCreditSettingRepository(session).save(20, settings(credit_value="0.02"))
        session.add(Tenant(id=3, tenant_code="tenant-3", tenant_name="Other"))
    token = set_current_tenant_id(3)
    try:
        with Session(store) as session, session.begin():
            repo = DshCreditSettingRepository(session)
            assert repo.effective() == CreditSettingState()
            repo.save(30, settings(credit_value="0.5"))
            assert repo.effective().credit_value_micro == 500_000
    finally:
        current_tenant_id.reset(token)
    with Session(store) as session:
        assert DshCreditSettingRepository(session).effective().credit_value_micro == 20_000


@pytest.mark.parametrize(
    "changes",
    [
        {"credit_value": "0.00009"},
        {"credit_value": "100.000001"},
        {"credit_value": "0"},
        {"credit_value": "0.0000001"},
        {"credit_value": 0.01},
        {"usd_cny_rate": "0.009"},
        {"usd_cny_rate": "100.5"},
        {"currency": "EUR"},
        {"version": -1},
        {"base_model_id": 0},
        {"credit_multiplier": "1"},
    ],
)
def test_input_validation(changes):
    with pytest.raises(ValidationError):
        settings(**changes)


def test_input_bounds_are_inclusive():
    assert settings(credit_value="0.0001", usd_cny_rate="0.01").credit_value_micro == 100
    assert settings(credit_value="100", usd_cny_rate="100").usd_cny_rate_micro == 100_000_000


@pytest.mark.parametrize(
    ("micro", "text"),
    [(10_000, "0.01"), (7_200_000, "7.2"), (1, "0.000001"), (100_000_000, "100"), (1_389, "0.001389")],
)
def test_format_micro(micro, text):
    assert format_micro(micro) == text


def test_credit_setting_table_is_tenant_aware():
    from bisheng.core.database import tenant_filter

    assert "bisheng.dsh.domain.models.credit_setting" in tenant_filter._TENANT_AWARE_MODEL_MODULES
    tenant_filter._force_import_all_models()
    assert "dsh_credit_setting" in tenant_filter._discover_tenant_aware_tables()
