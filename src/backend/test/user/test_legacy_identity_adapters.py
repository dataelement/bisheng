"""AC-26: reachable legacy DAO adapters keep the unified identity contract."""

import pytest
from sqlmodel import Session, select

from bisheng.common.errcode.user import AmbiguousAccountError, NicknameValidationError
from bisheng.user.domain.models.user import User, UserDao
from test.user.f011_fixtures import identity_store, old_user  # noqa: F401


async def test_legacy_local_creation_and_lookup_preserve_exact_case(identity_store):  # noqa: F811
    first = UserDao.create_user(User(user_name="SameNickname", external_id="000Case", password="test-only"))
    second = UserDao.add_user_with_groups_and_roles(
        User(user_name="SameNickname", external_id="000case", password="test-only"),
        [],
        [],
    )
    assert first.account_rule_version == second.account_rule_version == 1
    assert (await UserDao.aget_user_for_login("000Case")).user_id == first.user_id
    assert (await UserDao.aget_by_external_id("000case")).user_id == second.user_id
    assert await UserDao.aget_user_for_login("000CASE") is None


async def test_legacy_external_creation_does_not_apply_local_id_syntax(identity_store):  # noqa: F811
    user = await UserDao.add_user_and_default_role(
        User(
            user_name="ProviderNickname",
            external_id="external id/" + "x" * 80,
            source="generic_api",
            password="test-only",
        )
    )
    assert user.account_rule_version == 0
    assert (await UserDao.aget_by_source_external_id("generic_api", user.external_id)).user_id == user.user_id
    with pytest.raises(NicknameValidationError):
        await UserDao.add_user_and_default_role(User(user_name="x" * 33, external_id="other", source="generic_api"))


async def test_legacy_login_adapter_rejects_multiple_active_identities(identity_store):  # noqa: F811
    engine, _ = identity_store
    old_user(engine, account="LegacyCase", source="one")
    old_user(engine, account="legacycase", source="two")
    with pytest.raises(AmbiguousAccountError):
        await UserDao.aget_user_for_login(" LEGACYCASE ")


def test_scoped_user_search_finds_the_account_and_keeps_the_user_scope(identity_store):  # noqa: F811
    engine, _ = identity_store
    first = old_user(engine, account="000Case01", name="DisplayOnly")
    second = old_user(engine, account="000Case02", name="DifferentDisplay")
    with Session(engine) as session:
        statement = UserDao._filter_users_statement(select(User), [first.user_id], "000Case")
        assert [row.user_id for row in session.exec(statement).all()] == [first.user_id]
        assert second.user_id != first.user_id
