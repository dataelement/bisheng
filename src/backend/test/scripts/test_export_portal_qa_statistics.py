# ruff: noqa: RUF003
"""验证按提问配对、实际 ORM 租户/日期边界及只读导出契约。"""

import csv
import json
from collections import Counter
from contextlib import contextmanager
from datetime import datetime

import pytest
from sqlalchemy import Boolean, Column, DateTime, Integer, MetaData, String, Table, create_engine, event
from sqlmodel import Session

from scripts import export_portal_qa_statistics as script
from scripts.export_portal_qa_statistics import LABELS, Message, QaStatisticsRepository, Totals, count_messages


def dt(value):
    return datetime.fromisoformat(value)


def message(id, *, bot=False, **changes):
    values = {
        "id": id,
        "chat_id": "smart",
        "user_id": 10,
        "tenant_id": 1,
        "flow_id": "",
        "is_bot": bot,
        "category": "agent_answer" if bot else "question",
        "type": "end",
        "extra": "{}",
        "liked": 0,
        "create_time": dt(f"2026-08-01 00:00:{id:02d}"),
    }
    values.update(changes)
    return Message(**values)


def test_counts_questions_not_answers_and_does_not_steal_next_turn_reply():
    rows = [
        message(1),
        message(2),
        message(3, bot=True, liked=1),
        message(4, bot=True, liked=1),
        message(5),
        message(6, bot=True, category="agent_thinking"),
        message(7, bot=True, type="stream"),
    ]
    result = count_messages(list(reversed(rows)), None, dt("2026-09-01"), Counter())
    assert result.row(LABELS[0]) == [LABELS[0], 3, 1, "33.33%", 2]
    assert result.failed == 2


def test_explicit_parent_wins_and_cross_boundary_answer_is_included():
    rows = [
        message(1, create_time=dt("2026-07-31 23:59")),
        message(2, create_time=dt("2026-08-01 23:59")),
        message(3, create_time=dt("2026-08-02 00:01")),
        message(4, bot=True, extra=json.dumps({"parentMessageId": "2"}), liked=1, create_time=dt("2026-08-02 00:02")),
        message(5, bot=True, extra=json.dumps({"parentMessageId": "1"}), liked=1, create_time=dt("2026-08-02 00:03")),
    ]
    result = count_messages(rows, dt("2026-08-01"), dt("2026-08-02"), Counter())
    assert result.row(LABELS[0]) == [LABELS[0], 1, 1, "100.00%", 1]


@pytest.mark.parametrize(
    "changes",
    [
        {"extra": '{"parentMessageId": 99}'},
        {"extra": '{"parentMessageId": null}'},
        {"extra": '{"parentMessageId": true}'},
        {"extra": '{"parentMessageId": 1}', "tenant_id": 2},
        {"extra": '{"parentMessageId": 1}', "user_id": 20},
        {"extra": '{"parentMessageId": 1}', "chat_id": "other"},
        {"extra": '{"parentMessageId": 1}', "flow_id": "other"},
    ],
)
def test_unknown_or_wrong_owner_parent_never_falls_back_to_another_question(changes):
    result = count_messages([message(1), message(2, bot=True, liked=1, **changes)], None, dt("2026-09-01"), Counter())
    assert (result.success, result.failed, result.likes) == (0, 1, 0)


@pytest.mark.parametrize("extra", ["broken", "[]"])
def test_unreadable_association_stops_instead_of_inventing_pair(extra):
    with pytest.raises(ValueError, match="关联信息"):
        count_messages([message(1), message(2, bot=True, extra=extra)], None, dt("2026-09-01"), Counter())


def test_presence_rule_does_not_reinterpret_reply_error_text_or_cancelled_like():
    result = count_messages(
        [
            message(1),
            message(2, bot=True, extra='{"error": true}', liked=0),
            message(3),
            message(4, bot=True, type="assistant", category="answer", liked=2),
        ],
        None,
        dt("2026-09-01"),
        Counter(),
    )
    assert result.row(LABELS[0]) == [LABELS[0], 2, 2, "100.00%", 0]


@pytest.fixture
def database():
    repository = QaStatisticsRepository(None)
    engine = create_engine("sqlite://")
    metadata = MetaData()
    chats = Table(
        repository.Chat.__tablename__,
        metadata,
        Column("chat_id", String, primary_key=True),
        Column("flow_type", Integer),
        Column("flow_id", String),
        Column("user_id", Integer),
        Column("tenant_id", Integer),
        Column("is_delete", Boolean),
    )
    messages = Table(
        repository.Message.__tablename__,
        metadata,
        *[
            Column(
                name,
                Boolean
                if name == "is_bot"
                else DateTime
                if name == "create_time"
                else Integer
                if name in {"id", "user_id", "tenant_id", "liked"}
                else String,
                primary_key=name == "id",
            )
            for name in Message.__dataclass_fields__
        ],
    )
    metadata.create_all(engine)
    with Session(engine) as session:
        specs = [
            ("smart", 15, "", 1),
            ("document", 30, "space_7_file_12", 1),
            ("folder", 30, "space_7_folder_12", 1),
            ("workflow", 10, "wf", 1),
            ("tenant2", 15, "", 2),
            ("deleted", 15, "", 1),
        ]
        for i, (chat_id, flow_type, flow_id, tenant_id) in enumerate(specs):
            session.execute(
                chats.insert(),
                {
                    "chat_id": chat_id,
                    "flow_type": flow_type,
                    "flow_id": flow_id,
                    "tenant_id": tenant_id,
                    "user_id": 10,
                    "is_delete": chat_id == "deleted",
                },
            )
            question = message(i * 5 + 1, chat_id=chat_id, flow_id=flow_id, tenant_id=tenant_id)
            session.execute(messages.insert(), question.__dict__)
            if chat_id not in {"smart", "deleted"}:
                answer = message(
                    i * 5 + 2,
                    bot=True,
                    chat_id=chat_id,
                    flow_id=flow_id,
                    tenant_id=tenant_id,
                    liked=1,
                    create_time=dt("2026-08-02 00:00"),
                )
                session.execute(messages.insert(), answer.__dict__)
        # 截止时刻之后的回复，以及消息中途流片段，不能让无回答提问变成成功。
        session.execute(messages.insert(), message(40, bot=True, create_time=dt("2026-08-03")).__dict__)
        session.execute(messages.insert(), message(41, bot=True, type="stream").__dict__)
        session.commit()
    try:
        yield engine, repository
    finally:
        engine.dispose()


def test_real_orm_paging_scope_deleted_sessions_and_reply_snapshot(database):
    from bisheng.core.context.tenant import (
        bypass_tenant_filter,
        current_tenant_id,
        set_current_tenant_id,
        strict_tenant_filter,
    )
    from bisheng.core.database import tenant_filter

    engine, repository = database
    tenant_filter.register_tenant_filter_events()
    statements = []
    event.listen(engine, "before_cursor_execute", lambda conn, cur, stmt, params, ctx, many: statements.append(stmt))
    token = set_current_tenant_id(1)
    try:
        for context, expected in [(strict_tenant_filter(), (2, 0)), (bypass_tenant_filter(), (3, 1))]:
            with context, Session(engine) as session:
                repository.session = session
                totals, diagnostics = repository.collect(
                    dt("2026-08-01"), dt("2026-08-02"), dt("2026-08-03"), batch_size=1, verbose=False
                )
                assert (totals[LABELS[0]].questions, totals[LABELS[0]].success) == expected
                assert totals[LABELS[1]].row(LABELS[1]) == [LABELS[1], 1, 1, "100.00%", 1]
                assert diagnostics["conversations"] == expected[0] + 1
                session.rollback()
    finally:
        current_tenant_id.reset(token)
    assert statements and all(stmt.lstrip().upper().startswith("SELECT") for stmt in statements)


def test_report_is_two_rows_and_refuses_overwrite_and_cleans_failed_write(tmp_path, monkeypatch):
    totals = {LABELS[0]: Totals(3, 2, 1), LABELS[1]: Totals()}
    target = script.write_report(tmp_path / "result", totals)
    with target.open(encoding="utf-8-sig", newline="") as stream:
        assert list(csv.reader(stream)) == [
            script.HEADERS,
            [LABELS[0], "3", "2", "66.67%", "1"],
            [LABELS[1], "0", "0", "0.00%", "0"],
        ]
    saved = target.read_bytes()
    with pytest.raises(FileExistsError):
        script.write_report(target.parent, totals)
    assert target.read_bytes() == saved

    def failed_fsync(fd):
        raise OSError("disk write failed")

    monkeypatch.setattr(script.os, "fsync", failed_fsync)
    with pytest.raises(OSError):
        script.write_report(tmp_path / "failure", totals)
    assert not (tmp_path / "failure").exists()
    assert not list(tmp_path.glob(".portal-qa-*"))


@pytest.mark.parametrize("query_fails", [False, True])
def test_main_converts_beijing_window_to_database_timezone(database, tmp_path, monkeypatch, capsys, query_fails):
    import bisheng.core.database
    from bisheng.core.context.tenant import get_current_tenant_id

    engine, _ = database
    calls = []
    rolled_back = []

    @contextmanager
    def get_session():
        with Session(engine) as session:
            event.listen(session, "after_rollback", lambda session: rolled_back.append(True))
            yield session

    class Clock:
        @staticmethod
        def now(zone=None):
            return dt("2026-09-21 18:00").replace(tzinfo=zone)

        combine = staticmethod(datetime.combine)

    def collect(self, start, end, snapshot, **kwargs):
        calls.append((start, end, snapshot))
        # 触发真实只读事务，验证 main 的回滚和上下文恢复。
        from sqlalchemy import select

        self.session.execute(select(1))
        if query_fails:
            raise OSError("database unavailable")
        return {label: Totals() for label in LABELS}, Counter()

    previous_tenant = get_current_tenant_id()
    monkeypatch.setattr(script, "datetime", Clock)
    monkeypatch.setattr(bisheng.core.database, "get_sync_db_session", get_session)
    monkeypatch.setattr(script.QaStatisticsRepository, "collect", collect)
    monkeypatch.setattr(
        script.sys,
        "argv",
        [
            "script",
            "--all-tenants",
            "--start-date",
            "2026-08-01",
            "--end-date",
            "2026-09-21",
            "--db-timezone",
            "UTC",
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )
    assert script.main() == int(query_fails)
    assert calls == [(dt("2026-07-31 16:00"), dt("2026-09-21 10:00"), dt("2026-09-21 10:00"))]
    assert rolled_back and get_current_tenant_id() == previous_tenant
    output = capsys.readouterr()
    if query_fails:
        assert not (tmp_path / "out").exists()
        assert "统计失败" in output.err
    else:
        assert "成功率仅代表现存记录" in output.out
