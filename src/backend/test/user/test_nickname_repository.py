"""AC-04, AC-06, AC-07, AC-22, AC-23, AC-24, AC-25: atomic manual nickname changes."""

import pytest
from sqlalchemy import event
from sqlmodel import Session, select

from bisheng.common.errcode.user import NicknameValidationError
from bisheng.database.models.audit_log import AuditLog
from bisheng.user.domain.models.user import User
from bisheng.user.domain.schemas.nickname import NicknameActor
from test.user.f011_fixtures import identity_store, nickname_store, old_user  # noqa: F401


def test_rename_updates_one_identity_and_records_snapshot(nickname_store):  # noqa: F811
    engine, repository = nickname_store
    user = old_user(engine)
    saved = repository.rename(user.user_id, "新昵称", NicknameActor(user.user_id, user.user_name), profile_enabled=True)
    assert saved.user_name == "新昵称"
    assert saved.external_id == user.external_id
    assert saved.nickname_customized is True
    assert saved.token_version == user.token_version
    assert saved.password == user.password
    assert saved.dsh_profile_version == 1
    with Session(engine) as session:
        log = session.exec(select(AuditLog)).one()
        assert log.operator_id == user.user_id
        assert log.operator_name == user.user_name
        assert log.target_id == str(user.user_id)
        assert log.audit_metadata == {
            "field": "user_name",
            "before": user.user_name,
            "after": "新昵称",
            "result": "success",
        }
        assert log.operator_dept_id == 0


def test_unchanged_historical_name_does_not_enable_protection(nickname_store):  # noqa: F811
    engine, repository = nickname_store
    name = " old " + "中" * 40
    user = old_user(engine, name=name)
    saved = repository.rename(user.user_id, name, NicknameActor(user.user_id, name), profile_enabled=True)
    assert saved.user_name == name
    assert saved.nickname_customized is False
    assert saved.dsh_profile_version == 0
    with Session(engine) as session:
        assert session.exec(select(AuditLog)).all() == []


def test_rejected_new_value_leaves_original_and_logs_result(nickname_store):  # noqa: F811
    engine, repository = nickname_store
    user = old_user(engine)
    with pytest.raises(NicknameValidationError):
        repository.rename(user.user_id, "bad name", NicknameActor(user.user_id, user.user_name))
    with Session(engine) as session:
        saved = session.get(User, user.user_id)
        assert saved.user_name == user.user_name
        assert saved.nickname_customized is False
        log = session.exec(select(AuditLog)).one()
        assert log.audit_metadata["result"] == "failure"
        assert log.audit_metadata["before"] == user.user_name
        assert log.audit_metadata["after"] == "bad name"


def test_audit_failure_rolls_back_name_flag_and_version(nickname_store):  # noqa: F811
    engine, repository = nickname_store
    user = old_user(engine)

    def fail_audit(_mapper, _connection, _target):
        raise RuntimeError("injected audit failure")

    event.listen(AuditLog, "before_insert", fail_audit)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            repository.rename(user.user_id, "新昵称", NicknameActor(user.user_id, user.user_name), profile_enabled=True)
    finally:
        event.remove(AuditLog, "before_insert", fail_audit)
    with Session(engine) as session:
        saved = session.get(User, user.user_id)
        assert saved.user_name == user.user_name
        assert saved.nickname_customized is False
        assert saved.dsh_profile_version == 0
        assert session.exec(select(AuditLog)).all() == []
