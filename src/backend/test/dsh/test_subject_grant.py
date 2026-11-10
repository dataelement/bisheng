"""Local department grants are idempotent and independent of membership capacity. 覆盖 AC: AC-04, AC-06, AC-10."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlmodel import Session, select

from bisheng.database.models.department import UserDepartment
from bisheng.dsh.domain.models.subject_grant import DshSubjectGrant
from bisheng.dsh.domain.models.subject_policy import DshSubjectPolicy
from bisheng.dsh.domain.repositories.subject_grant import DshSubjectGrantRepository
from bisheng.dsh.domain.repositories.subject_policy import DshSubjectPolicyRepository
from test.dsh.test_subject_policy import subject_store  # noqa: F401


def arguments():
    return {
        "actor_id": 20,
        "model_id": 7,
        "subject_type": "DEPARTMENT",
        "subject_id": 10,
        "request": SimpleNamespace(expected_version=0, enabled=True, monthly_token_limit=1000),
    }


def test_retry_commits_once_and_new_members_inherit_without_seats(subject_store):  # noqa: F811
    DshSubjectGrant.__table__.create(subject_store)
    with Session(subject_store) as db, db.begin():
        intent = DshSubjectGrantRepository(db).prepare(**arguments())
        assert intent["payload"]["user_ids"] == []
    with Session(subject_store) as db, db.begin():
        db.add(UserDepartment(id=101, user_id=21, department_id=11))
    with Session(subject_store) as db, db.begin():
        repository = DshSubjectGrantRepository(db)
        assert repository.prepare(**arguments())["operation_id"] == intent["operation_id"]
        assert repository.finish(intent["operation_id"])["result"]["version"] == 1
    with Session(subject_store) as db, db.begin():
        assert DshSubjectGrantRepository(db).prepare(**arguments())["status"] == "SUCCEEDED"
        assert len(db.exec(select(DshSubjectPolicy)).all()) == 1
        policies = DshSubjectPolicyRepository(db)
        assert policies.effective(20).monthly_token_limit == 1000
        assert policies.effective(21).monthly_token_limit == 1000


async def test_subject_save_recovers_local_failure_without_remote_calls(subject_store, monkeypatch):  # noqa: F811
    import httpx

    import bisheng.core.database as database
    from bisheng.dsh import admin_runtime

    DshSubjectGrant.__table__.create(subject_store)

    @contextmanager
    def scope():
        with Session(subject_store) as db:
            yield db

    monkeypatch.setattr(database, "get_sync_db_session", scope)
    monkeypatch.setattr(admin_runtime, "read_available_models", AsyncMock(return_value=[{}]))
    remote = AsyncMock(side_effect=AssertionError("Remote access is forbidden"))
    monkeypatch.setattr(httpx.AsyncClient, "request", remote)
    original = DshSubjectGrantRepository.finish
    attempts = []

    def interrupted(self, operation_id, **kwargs):
        attempts.append(operation_id)
        if len(attempts) == 1:
            raise RuntimeError("Local transaction interrupted")
        return original(self, operation_id, **kwargs)

    monkeypatch.setattr(DshSubjectGrantRepository, "finish", interrupted)
    args = dict(actor={"user_id": "20", "tenant_id": "2", "scope": "tenant"}, tenant=2, **arguments())
    with pytest.raises(RuntimeError):
        await admin_runtime.write_subject_grant(**args)
    with Session(subject_store) as db:
        assert db.exec(select(DshSubjectPolicy)).all() == []
    assert (await admin_runtime.write_subject_grant(**args))["version"] == 1
    assert attempts[0] == attempts[1]
    remote.assert_not_awaited()
