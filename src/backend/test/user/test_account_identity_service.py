"""F011 account resolution chooses an identity before any password check."""

import pytest

from bisheng.common.errcode.user import AmbiguousAccountError, UserForbiddenError
from bisheng.user.domain.models.user import User
from bisheng.user.domain.services.account_identity_service import AccountIdentityService
from test.user.f011_fixtures import identity_store, old_user  # noqa: F401


def test_new_accounts_resolve_exactly(identity_store):  # noqa: F811
    """AC-09, AC-12: no nickname or differently-cased fallback for new accounts."""
    upper = AccountIdentityService.create_local(
        User(user_name="同名", external_id="Test01", password="test-only"), role_ids=[]
    )
    lower = AccountIdentityService.create_local(
        User(user_name="同名", external_id="test01", password="test-only"), role_ids=[]
    )
    assert AccountIdentityService.resolve_login("Test01").user_id == upper.user_id
    assert AccountIdentityService.resolve_login("test01").user_id == lower.user_id
    assert AccountIdentityService.resolve_login("TEST01") is None
    assert AccountIdentityService.resolve_login(" Test01 ") is None
    assert AccountIdentityService.resolve_login("同名") is None


def test_legacy_login_keeps_original_comparison(identity_store):  # noqa: F811
    """AC-11: original trim and DB comparison, including long IDs."""
    engine, _ = identity_store
    old = old_user(engine, account="Old" + "A" * 80)
    assert AccountIdentityService.resolve_login(" old" + "a" * 80 + " ").user_id == old.user_id


def test_multiple_active_candidates_are_rejected(identity_store):  # noqa: F811
    """AC-13: password cannot be used to choose among identities."""
    engine, _ = identity_store
    old_user(engine, source="feishu")
    old_user(engine, source="wecom")
    with pytest.raises(AmbiguousAccountError) as error:
        AccountIdentityService.resolve_login("legacy01")
    assert error.value.code == 10615


def test_disabled_identity_is_not_login_eligible(identity_store):  # noqa: F811
    """AC-15: disabled result uses the same account matching contract."""
    engine, _ = identity_store
    old_user(engine, disabled=1)
    with pytest.raises(UserForbiddenError):
        AccountIdentityService.resolve_login("legacy01")
    active = old_user(engine, source="wecom")
    assert AccountIdentityService.resolve_login("legacy01").user_id == active.user_id


def test_external_adoption_is_exact_for_new_accounts(identity_store):  # noqa: F811
    """AC-25: legacy source matching remains; v1 never case-folds to another user."""
    created = AccountIdentityService.create_local(
        User(user_name="昵称", external_id="Sync01", password="test-only"), role_ids=[]
    )
    assert AccountIdentityService.resolve_external("Sync01").user_id == created.user_id
    assert AccountIdentityService.resolve_external("sync01") is None
