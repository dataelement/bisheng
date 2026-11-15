"""F003 T003: every audit source write stamps the organisation snapshot.

Covers the DAO choke points (behaviour) plus a source scan, so a new direct
``AuditLog(...)`` construction cannot slip past the snapshot unnoticed.
"""

import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlmodel import select

for _mod in ("celery", "celery.schedules", "celery.app", "celery.app.task"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

from bisheng.database.models import org_snapshot
from bisheng.database.models.audit_log import AuditLog, AuditLogDao
from bisheng.database.models.org_snapshot import DEPT_NOT_APPLICABLE
from bisheng.database.models.session import MessageSession, MessageSessionDao
from bisheng.open_api.domain.models.model_call_record import ModelCallRecord
from bisheng.open_api.domain.services.model_call_record_writer import ModelCallRecordWriter

_BACKEND = Path(__file__).resolve().parents[2] / "bisheng"
_CONSTRUCTION = re.compile(r"(?<![\w.])AuditLog\(")
# A file that constructs ``AuditLog`` must hand it to one of these.
_STAMPED_SINKS = (
    "stamp_audit_logs",
    "AuditLogDao.insert_audit_logs",
    "AuditLogDao.ainsert_audit_logs",
    "open_api_call_audit_service.enqueue",
)
_SNAPSHOT = (3, "Root/Sales/East")


@pytest.fixture()
def fake_resolve(monkeypatch):
    calls = []

    def _resolve(user_id):
        calls.append(user_id)
        return _SNAPSHOT

    async def _aresolve(user_ids):
        ids = [one for one in user_ids if one]
        calls.extend(ids)
        return {int(one): _SNAPSHOT for one in ids}

    monkeypatch.setattr(org_snapshot, "resolve_user_dept", _resolve)
    monkeypatch.setattr(org_snapshot, "aresolve_users_dept", _aresolve)
    return calls


class TestGuard:
    def test_every_direct_construction_reaches_a_stamping_sink(self):
        offenders = []
        for path in _BACKEND.rglob("*.py"):
            if "alembic" in path.parts:
                continue
            source = path.read_text(encoding="utf-8")
            constructions = [
                line
                for line in source.splitlines()
                if _CONSTRUCTION.search(line) and not line.lstrip().startswith(("class ", "#", "``"))
            ]
            if constructions and not any(sink in source for sink in _STAMPED_SINKS):
                offenders.append(str(path.relative_to(_BACKEND)))
        assert offenders == []


class TestAuditLogDao:
    def test_sync_insert_stamps_and_marks_system(self, patch_audit_dao, audit_session, fake_resolve):
        AuditLogDao.insert_audit_logs([AuditLog(operator_id=7, tenant_id=1), AuditLog(operator_id=0, tenant_id=1)])
        rows = audit_session.exec(select(AuditLog).order_by(AuditLog.operator_id)).all()
        assert [(r.operator_id, r.operator_dept_id, r.operator_dept_path) for r in rows] == [
            (0, DEPT_NOT_APPLICABLE, None),
            (7, *_SNAPSHOT),
        ]
        assert fake_resolve == [7]

    async def test_async_insert_stamps_before_add(self, monkeypatch, fake_resolve):
        added = []
        session = SimpleNamespace(add_all=added.extend, commit=AsyncMock())

        class _Ctx:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *exc):
                return False

        monkeypatch.setattr("bisheng.database.models.audit_log.get_async_db_session", _Ctx)
        await AuditLogDao.ainsert_audit_logs([AuditLog(operator_id=7), AuditLog(operator_id=0)])
        assert [(r.operator_dept_id, r.operator_dept_path) for r in added] == [_SNAPSHOT, (DEPT_NOT_APPLICABLE, None)]


class TestMessageSessionDao:
    def _session(self, **kwargs):
        return MessageSession(chat_id="c1", flow_id="f1", flow_name="app", flow_type=5, group_ids=[1], **kwargs)

    async def test_user_session_gets_primary_department(self, monkeypatch, fake_resolve):
        captured = []
        session = SimpleNamespace(add=captured.append, commit=AsyncMock(), refresh=AsyncMock())

        class _Ctx:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *exc):
                return False

        monkeypatch.setattr("bisheng.database.models.session.get_async_db_session", _Ctx)
        await MessageSessionDao.async_insert_one(self._session(user_id=7))
        assert (captured[0].operator_dept_id, captured[0].operator_dept_path) == _SNAPSHOT

    def test_open_api_session_is_not_applicable(self, monkeypatch, fake_resolve):
        captured = []
        session = MagicMock()
        session.add.side_effect = captured.append

        class _Ctx:
            def __enter__(self):
                return session

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr("bisheng.database.models.session.get_sync_db_session", _Ctx)
        MessageSessionDao.insert_one(self._session(user_id=7, api_subject_type="app_secret"))
        assert captured[0].operator_dept_id == DEPT_NOT_APPLICABLE
        assert fake_resolve == []


class TestModelCallRecordWriter:
    async def test_subject_rules(self, fake_resolve):
        def _record(kind, subject_id):
            return ModelCallRecord(requested_model="m", result="success", subject_kind=kind, subject_id=subject_id)

        batch = [
            _record("user", 7),
            _record("natural_person", 8),
            _record("natural_person", None),
            _record("service_account", 9),
            _record("app_self", None),
        ]
        await ModelCallRecordWriter._stamp_subject_departments(batch)
        assert [r.operator_dept_id for r in batch] == [3, 3, None, DEPT_NOT_APPLICABLE, DEPT_NOT_APPLICABLE]
        assert sorted(fake_resolve) == [7, 8]


class TestRuntimeRecords:
    async def test_access_log_stamped_with_visitor(self, monkeypatch, fake_resolve):
        from bisheng.app_runtime.domain.services import app_access_log_service as svc

        captured = []

        async def _insert(session, row):
            captured.append(row)

        class _Ctx:
            async def __aenter__(self):
                return SimpleNamespace(commit=AsyncMock())

            async def __aexit__(self, *exc):
                return False

        monkeypatch.setattr(svc, "_first_entry_in_window", AsyncMock(return_value=True))
        monkeypatch.setattr(svc, "get_async_db_session", _Ctx)
        monkeypatch.setattr(svc.AppAccessLogDao, "ainsert", _insert)
        assert await svc.record_access(app_id="a", tenant_id=1, user_id=7, user_name="u") is True
        assert (captured[0].operator_dept_id, captured[0].operator_dept_path) == _SNAPSHOT

    async def test_capability_record_stamped_with_access_user(self, monkeypatch, fake_resolve):
        from bisheng.app_publish.domain.services import capability_audit as svc

        captured = []

        async def _insert(session, row):
            captured.append(row)

        class _Ctx:
            async def __aenter__(self):
                return SimpleNamespace(commit=AsyncMock())

            async def __aexit__(self, *exc):
                return False

        monkeypatch.setattr(svc, "get_async_db_session", _Ctx)
        monkeypatch.setattr(svc.AppCapabilityCallRecordDao, "ainsert", _insert)
        await svc.record_retrieval(
            app_id="a", app_name="A", tenant_id=1, version_id=None, access_user_id=7, requested=[], effective=[]
        )
        assert captured[0].operator_dept_id == 3

    async def test_snapshot_failure_never_escapes_access_log(self, monkeypatch):
        from bisheng.app_runtime.domain.services import app_access_log_service as svc

        monkeypatch.setattr(svc, "_first_entry_in_window", AsyncMock(return_value=True))
        with patch.object(org_snapshot.UserDepartmentDao, "aget_by_user_ids", side_effect=RuntimeError):
            monkeypatch.setattr(svc, "get_async_db_session", MagicMock(side_effect=RuntimeError))
            assert await svc.record_access(app_id="a", tenant_id=1, user_id=7, user_name="u") is False
