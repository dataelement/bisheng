"""F011: retain deprecated SSO identity names without using new nicknames as IDs."""

import pytest

from bisheng.common.errcode.user import AmbiguousAccountError
from bisheng.user.domain.models.user import User
from bisheng.user.domain.schemas.nickname import NicknameActor
from bisheng.user.domain.services.account_identity_service import AccountIdentityService
from test.user.f011_fixtures import identity_store, nickname_store, old_user  # noqa: F401


def test_old_sso_name_survives_manual_nickname_change(nickname_store):  # noqa: F811
    engine, nicknames = nickname_store
    user = old_user(engine, account="External01", name="OriginalProviderName")
    nicknames.rename(user.user_id, "显示昵称", NicknameActor(user.user_id, user.user_name))
    assert AccountIdentityService.resolve_deprecated_sso(None, "originalprovidername").user_id == user.user_id
    assert AccountIdentityService.resolve_deprecated_sso("External01", "any-display-name").user_id == user.user_id
    assert AccountIdentityService.resolve_deprecated_sso(None, "显示昵称") is None


def test_null_external_id_can_keep_its_old_sso_identifier(nickname_store):  # noqa: F811
    engine, nicknames = nickname_store
    user = old_user(engine, account=None, name="LegacyProviderIdentity")
    nicknames.rename(user.user_id, "新昵称", NicknameActor(user.user_id, user.user_name))
    resolved = AccountIdentityService.resolve_deprecated_sso(None, "LegacyProviderIdentity")
    assert resolved.user_id == user.user_id
    assert resolved.external_id is None


def test_new_nickname_is_not_an_sso_login_alias(identity_store):  # noqa: F811
    created = AccountIdentityService.create_local(
        User(user_name="显示昵称", external_id="Case01", password="test-only"), role_ids=[]
    )
    assert AccountIdentityService.resolve_deprecated_sso(None, "显示昵称") is None
    assert AccountIdentityService.resolve_deprecated_sso(None, "Case01").user_id == created.user_id
    assert AccountIdentityService.resolve_deprecated_sso(None, "case01") is None


def test_ambiguous_old_sso_names_are_rejected(identity_store):  # noqa: F811
    engine, _ = identity_store
    old_user(engine, account="one", name="Duplicate")
    old_user(engine, account="two", name="Duplicate")
    with pytest.raises(AmbiguousAccountError):
        AccountIdentityService.resolve_deprecated_sso(None, "Duplicate")
