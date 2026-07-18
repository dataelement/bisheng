"""Regression guard: linsight status columns must NOT be a native ENUM.

A native MySQL ENUM freezes its allowed set at table-creation time, so a
later-added status value (e.g. WAITING_FOR_USER_INPUT, the HITL park state) is
rejected on upgraded DBs with ``(1265, "Data truncated for column 'status'")``.
The columns are kept as plain VARCHAR so current/future status names are
accepted; storage stays the enum NAME (back-compatible with existing rows).
"""

from __future__ import annotations

from sqlalchemy.dialects import mysql

from bisheng.linsight.domain.models.linsight_execute_task import (
    ExecuteTaskStatusEnum,
    LinsightExecuteTask,
)
from bisheng.linsight.domain.models.linsight_session_version import (
    LinsightSessionVersion,
    SessionVersionStatusEnum,
)


def test_status_columns_are_varchar_not_native_enum():
    for model in (LinsightSessionVersion, LinsightExecuteTask):
        col_type = model.__table__.c.status.type
        # not a native DB ENUM (the freeze-the-allowed-set footgun)
        assert getattr(col_type, "native_enum", True) is False, model.__tablename__
        # compiles to VARCHAR on MySQL, wide enough for the longest status name
        ddl = col_type.compile(dialect=mysql.dialect())
        assert ddl.startswith("VARCHAR"), f"{model.__tablename__}: {ddl}"


def test_new_status_value_fits_column_width():
    # the value that triggered the production failure must fit the column width
    for enum_cls, model in (
        (SessionVersionStatusEnum, LinsightSessionVersion),
        (ExecuteTaskStatusEnum, LinsightExecuteTask),
    ):
        assert enum_cls.WAITING_FOR_USER_INPUT.name == "WAITING_FOR_USER_INPUT"
        longest = max(len(m.name) for m in enum_cls)
        assert longest <= (model.__table__.c.status.type.length or 0)
