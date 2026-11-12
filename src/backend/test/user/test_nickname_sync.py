"""AC-25: stale external profile writes cannot undo a manual nickname."""

import pytest
from sqlmodel import Session

from bisheng.common.errcode.user import NicknameValidationError
from bisheng.user.domain.models.user import User
from bisheng.user.domain.repositories.dsh_profile import UserDshProfileRepository
from bisheng.user.domain.schemas.nickname import NicknameActor
from test.user.f011_fixtures import identity_store, nickname_store, old_user  # noqa: F401


def test_sync_read_before_manual_rename_cannot_overwrite_it(nickname_store):  # noqa: F811
    engine, nicknames = nickname_store
    user = old_user(engine)
    with Session(engine) as session:
        stale = session.get(User, user.user_id)
        session.expunge(stale)
    stale.user_name, stale.email = "组织新名", "updated@example.test"
    nicknames.rename(user.user_id, "主动昵称", NicknameActor(user.user_id, user.user_name))
    with Session(engine) as session:
        saved, profile_changed = UserDshProfileRepository.apply_detached_changes(session, stale, from_sync=True)
        session.commit()
        assert saved.user_name == "主动昵称"
        assert saved.nickname_customized is True
        assert saved.email == "updated@example.test"
        assert profile_changed is False


def test_protected_name_ignores_invalid_source_name_but_syncs_email(nickname_store):  # noqa: F811
    engine, nicknames = nickname_store
    user = old_user(engine)
    nicknames.rename(user.user_id, "主动昵称", NicknameActor(user.user_id, user.user_name))
    with Session(engine) as session:
        incoming = session.get(User, user.user_id)
        session.expunge(incoming)
    incoming.user_name, incoming.email, incoming.nickname_customized = "invalid name", "sync@example.test", False
    with Session(engine) as session:
        saved, changed = UserDshProfileRepository.apply_detached_changes(session, incoming, from_sync=True)
        session.commit()
        assert saved.user_name == "主动昵称"
        assert saved.email == "sync@example.test"
        assert saved.nickname_customized is True
        assert changed is False


def test_unchanged_legacy_name_does_not_block_other_sync(nickname_store):  # noqa: F811
    engine, _ = nickname_store
    name = " old name " + "中" * 40
    user = old_user(engine, name=name)
    with Session(engine) as session:
        incoming = session.get(User, user.user_id)
        session.expunge(incoming)
    incoming.email = "sync@example.test"
    with Session(engine) as session:
        saved, changed = UserDshProfileRepository.apply_detached_changes(session, incoming, from_sync=True)
        session.commit()
        assert saved.user_name == name
        assert changed is False


def test_invalid_actual_sync_name_is_rejected(nickname_store):  # noqa: F811
    engine, _ = nickname_store
    user = old_user(engine)
    with Session(engine) as session:
        incoming = session.get(User, user.user_id)
        session.expunge(incoming)
    incoming.user_name = "invalid name"
    with Session(engine) as session, pytest.raises(NicknameValidationError):
        UserDshProfileRepository.apply_detached_changes(session, incoming, from_sync=True)
    with Session(engine) as session:
        assert session.get(User, user.user_id).user_name == user.user_name
