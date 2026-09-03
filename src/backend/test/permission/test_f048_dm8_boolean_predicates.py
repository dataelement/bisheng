"""Regression coverage for DM8-compatible F048 Boolean predicates."""

from __future__ import annotations

import inspect

from sqlalchemy.engine.default import DefaultDialect
from sqlmodel import select

from bisheng.permission.application import control_state, sql_runtime
from bisheng.permission.domain.models import PermissionGrantAssignee
from bisheng.permission.migration import f048_runtime_verification


class _DmDialect(DefaultDialect):
    name = "dm"


def test_permission_boolean_predicate_compiles_as_equality_for_dm8() -> None:
    statement = select(PermissionGrantAssignee.id).where(PermissionGrantAssignee.protected == 1)

    sql = str(
        statement.compile(
            dialect=_DmDialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert " IS 1" not in sql
    assert " = 1" in sql


def test_f048_runtime_modules_do_not_use_dm8_incompatible_boolean_is() -> None:
    source = "\n".join(
        inspect.getsource(module)
        for module in (
            control_state,
            sql_runtime,
            f048_runtime_verification,
        )
    )

    assert ".is_(True)" not in source
    assert ".is_(False)" not in source
