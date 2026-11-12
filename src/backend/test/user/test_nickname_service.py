"""F011 self target derivation and the final nickname transaction."""

import pytest
from sqlmodel import Session, select

from bisheng.common.errcode.user import UserForbiddenError
from bisheng.database.models.audit_log import AuditLog
from bisheng.user.domain.models.user import User
from bisheng.user.domain.schemas.nickname import NicknameActor
from bisheng.user.domain.services.nickname_service import NicknameService
from test.user.f011_fixtures import identity_store, nickname_store, old_user  # noqa: F401


def test_self_change_does_not_modify_another_user(nickname_store, monkeypatch):  # noqa: F811
    engine, _ = nickname_store
    monkeypatch.setattr(NicknameService, "profile_enabled", staticmethod(lambda: False))
    first = old_user(engine, account="one")
    second = old_user(engine, account="two")
    NicknameService.rename_self(NicknameActor(first.user_id, first.user_name), "新昵称")
    with Session(engine) as session:
        assert session.get(User, first.user_id).user_name == "新昵称"
        assert session.get(User, second.user_id).user_name == second.user_name


def test_non_person_identity_is_rejected():
    with pytest.raises(UserForbiddenError):
        NicknameService.rename_self(NicknameActor(0, "system"), "昵称")


def test_managed_change_rolls_back_its_own_nickname_transaction(nickname_store, monkeypatch):  # noqa: F811
    engine, repository = nickname_store
    monkeypatch.setattr(NicknameService, "profile_enabled", staticmethod(lambda: True))
    user = old_user(engine)

    def fail_audit(_rows):
        raise RuntimeError("audit failure")

    monkeypatch.setattr(repository, "stamp", staticmethod(fail_audit))
    with pytest.raises(RuntimeError, match="audit failure"):
        NicknameService.rename_managed(user.user_id, "新昵称", NicknameActor(user.user_id, user.user_name))
    with Session(engine) as session:
        saved = session.get(User, user.user_id)
        assert saved.user_name == user.user_name
        assert saved.nickname_customized is False
        assert saved.dsh_profile_version == 0
        assert session.exec(select(AuditLog)).all() == []
