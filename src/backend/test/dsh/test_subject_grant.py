"""Member selection persists across retries, independent of later organization edits."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlmodel import Session, select

from bisheng.common.errcode.dsh import DshSeatLimitReachedError
from bisheng.database.models.department import UserDepartment
from bisheng.dsh.domain.models.subject_grant import DshSubjectGrant
from bisheng.dsh.domain.models.subject_policy import DshSubjectPolicy
from bisheng.dsh.domain.repositories.subject_grant import DshSubjectGrantRepository
from bisheng.dsh.domain.services.seat_allocation import allocate_seats
from test.dsh.test_subject_policy import subject_store  # noqa: F401


def test_retry_keeps_original_people_and_commits_once(subject_store):  # noqa: F811
    DshSubjectGrant.__table__.create(subject_store)
    args = {
        "actor_id": 20,
        "model_id": 1,
        "subject_type": "DEPARTMENT",
        "subject_id": 10,
        "request": SimpleNamespace(expected_version=0, enabled=True, monthly_token_limit=1000),
    }
    with Session(subject_store) as db, db.begin():
        intent = DshSubjectGrantRepository(db).prepare(**args)
        assert intent["payload"]["user_ids"] == [20]
    with Session(subject_store) as db, db.begin():
        db.add(UserDepartment(id=101, user_id=21, department_id=11))
    with Session(subject_store) as db, db.begin():
        retry = DshSubjectGrantRepository(db).prepare(**args)
        assert retry["operation_id"] == intent["operation_id"]
        assert retry["payload"]["user_ids"] == [20]
        result = DshSubjectGrantRepository(db).finish(intent["operation_id"])
        assert result["result"]["version"] == 1
    with Session(subject_store) as db, db.begin():
        assert DshSubjectGrantRepository(db).prepare(**args)["status"] == "SUCCEEDED"
        assert len(db.exec(select(DshSubjectPolicy)).all()) == 1


async def test_gateway_capacity_failure_is_preserved():
    gateway = SimpleNamespace(
        request=AsyncMock(return_value={"operation_id": "id", "status": "FAILED", "result_code": "seat_limit_reached"})
    )
    with pytest.raises(DshSeatLimitReachedError):
        await allocate_seats(gateway, "id", {"user_id": "20", "tenant_id": "2", "scope": "tenant"}, 2, [21, 21, 22])
    assert gateway.request.call_args.args[1]["user_ids"] == ["21", "22"]


async def test_subject_save_recovers_lost_gateway_response(subject_store, monkeypatch):  # noqa: F811
    import sys
    from contextlib import contextmanager

    import bisheng.core.database as database
    from bisheng.common.errcode.dsh import DshAuthorizationUnavailableError
    from bisheng.dsh import admin_runtime

    DshSubjectGrant.__table__.create(subject_store)

    @contextmanager
    def session_scope():
        with Session(subject_store) as db:
            yield db

    monkeypatch.setitem(
        sys.modules,
        "bisheng.llm.domain.services.llm",
        SimpleNamespace(LLMService=SimpleNamespace(get_dsh_model_snapshot=AsyncMock())),
    )
    monkeypatch.setattr(database, "get_sync_db_session", session_scope)
    monkeypatch.setattr(admin_runtime, "read_available_models", AsyncMock(return_value=[{}]))
    attempts = []

    async def gateway_request(operation, payload):
        attempts.append(payload)
        if len(attempts) == 1:
            raise DshAuthorizationUnavailableError()
        return {"operation_id": payload["operation_id"], "status": "SUCCEEDED", "selected": 1, "newly_assigned": 1}

    args = {
        "actor": {"user_id": "20", "tenant_id": "2", "scope": "tenant"},
        "tenant": 2,
        "actor_id": 20,
        "model_id": 1,
        "subject_type": "DEPARTMENT",
        "subject_id": 10,
        "request": SimpleNamespace(expected_version=0, enabled=True, monthly_token_limit=1000),
    }
    gateway = SimpleNamespace(request=gateway_request)
    with pytest.raises(DshAuthorizationUnavailableError):
        await admin_runtime.write_subject_grant(gateway, **args)
    with Session(subject_store) as db, db.begin():
        assert not db.exec(select(DshSubjectPolicy)).all()
        db.add(UserDepartment(id=101, user_id=21, department_id=11))
    result = await admin_runtime.write_subject_grant(gateway, **args)
    assert result["version"] == 1
    assert attempts[0] == attempts[1]
    assert attempts[1]["user_ids"] == ["20"]
