"""AC-08..14/32: execute the real account repository against isolated SQL."""

import pytest
from sqlalchemy import event
from sqlmodel import Session, select

from bisheng.common.errcode.user import AccountAlreadyExistsError
from bisheng.database.models.user_role import UserRole
from bisheng.user.domain.models.account_identity import UserAccountReservation
from bisheng.user.domain.models.user import User
from test.user.f011_fixtures import identity_store, old_user  # noqa: F401


def create(repository, account, **kwargs):
    return repository.create(
        User(user_name="新昵称", external_id=account, password="test-only"),
        exact=True,
        role_ids=[],
        group_ids=[],
        **kwargs,
    )


def test_case_variants_remain_separate(identity_store):  # noqa: F811
    """AC-09: independent exact accounts despite NOCASE external_id column."""
    _, repository = identity_store
    upper = create(repository, "AB001")
    lower = create(repository, "ab001")
    assert upper.user_id != lower.user_id
    assert [u.user_id for u in repository.login_candidates("AB001")] == [upper.user_id]
    assert [u.user_id for u in repository.login_candidates("ab001")] == [lower.user_id]
    assert repository.login_candidates("Ab001") == []
    assert repository.login_candidates(" AB001 ") == []


@pytest.mark.parametrize(("source", "disabled"), [("local", 0), ("feishu", 0), ("local", 1), ("wecom", 1)])
def test_legacy_occupancy_is_global(identity_store, source, disabled):  # noqa: F811
    """AC-08, AC-10: all sources and retained disabled/deleted rows reserve IDs."""
    engine, repository = identity_store
    old = old_user(engine, source=source, disabled=disabled)
    with pytest.raises(AccountAlreadyExistsError):
        create(repository, "legacy01")
    assert repository.login_candidates(" Legacy01 ")[0].user_id == old.user_id


def test_duplicate_exact_key_is_rejected(identity_store):  # noqa: F811
    """AC-14: one persisted identity and reservation after duplicate writes."""
    engine, repository = identity_store
    create(repository, "New01")
    with pytest.raises(AccountAlreadyExistsError):
        create(repository, "New01")
    with Session(engine) as session:
        assert len(session.exec(select(User)).all()) == 1
        assert len(session.exec(select(UserAccountReservation)).all()) == 1


def test_ambiguous_legacy_candidates_are_not_collapsed(identity_store):  # noqa: F811
    """AC-13: the service must see every eligible legacy identity."""
    engine, repository = identity_store
    first = old_user(engine, account="old01", source="feishu")
    second = old_user(engine, account="OLD01", source="wecom")
    assert {u.user_id for u in repository.login_candidates("Old01")} == {first.user_id, second.user_id}


def test_external_lookup_filters_new_case_variants(identity_store):  # noqa: F811
    """AC-25: new identity adoption cannot use a collation's arbitrary first row."""
    _, repository = identity_store
    first = create(repository, "Sync01")
    create(repository, "sync01")
    assert [u.user_id for u in repository.find_external("Sync01")] == [first.user_id]
    assert repository.find_external("sYnc01") == []


def test_binding_failure_rolls_back_identity_and_reservation(identity_store):  # noqa: F811
    """AC-14: identity and child bindings commit together."""
    engine, repository = identity_store

    def fail_binding(_mapper, _connection, _target):
        raise RuntimeError("injected binding failure")

    event.listen(UserRole, "before_insert", fail_binding)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            repository.create(
                User(user_name="新昵称", external_id="Rollback01", password="test-only"),
                exact=True,
                role_ids=[2],
                group_ids=[],
            )
    finally:
        event.remove(UserRole, "before_insert", fail_binding)
    with Session(engine) as session:
        assert session.exec(select(User)).all() == []
        assert session.exec(select(UserAccountReservation)).all() == []


def test_original_columns_and_values_are_preserved(identity_store):  # noqa: F811
    """AC-06, AC-32: metadata defaults do not shorten or normalize history."""
    engine, _ = identity_store
    original = old_user(engine, account="000" + "A" * 80, name=" old name " + "中" * 40)
    with Session(engine) as session:
        saved = session.get(User, original.user_id)
        assert saved.user_name == original.user_name
        assert saved.external_id == original.external_id
        assert saved.account_rule_version == 0
        assert saved.account_match_key == "legacy"
    assert User.__table__.c.user_name.type.length == 128
    assert User.__table__.c.external_id.type.length == 255
