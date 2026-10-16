"""Indexable name/identity candidate expressions for MySQL and DM8."""

from sqlalchemy import Boolean, and_, case, false, literal, or_, select, true, union
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.expression import FunctionElement

from bisheng.common.subject_search import escape_like, numeric_prefix_ranges


class _ExactText(FunctionElement):
    type = Boolean()
    inherit_cache = True


class _PrefixText(FunctionElement):
    type = Boolean()
    inherit_cache = False


@compiles(_ExactText)
def _exact_default(element, compiler, **kwargs):
    column, value = element.clauses
    return f"({compiler.process(column, **kwargs)} COLLATE BINARY = {compiler.process(value, **kwargs)} COLLATE BINARY)"


@compiles(_PrefixText)
def _prefix_default(element, compiler, **kwargs):
    column, value = element.clauses
    col_sql = compiler.process(column, **kwargs)
    val_sql = compiler.process(value, **kwargs)
    return f"(substr({col_sql}, 1, length({val_sql})) COLLATE BINARY = {val_sql} COLLATE BINARY)"


@compiles(_ExactText, "mysql")
def _exact_mysql(element, compiler, **kwargs):
    column, value = element.clauses
    return (
        f"(CAST({compiler.process(column, **kwargs)} AS BINARY) = CAST({compiler.process(value, **kwargs)} AS BINARY))"
    )


@compiles(_PrefixText, "mysql")
def _prefix_mysql(element, compiler, **kwargs):
    column, value = element.clauses
    pattern = literal(escape_like(value.value) + "%")
    return f"(CAST({compiler.process(column, **kwargs)} AS BINARY) LIKE CAST({compiler.process(pattern, **kwargs)} AS BINARY) ESCAPE '/')"


@compiles(_ExactText, "dm")
def _exact_dm(element, compiler, **kwargs):
    column, value = element.clauses
    return f"(BINARY {compiler.process(column, **kwargs)} = {compiler.process(value, **kwargs)})"


@compiles(_PrefixText, "dm")
def _prefix_dm(element, compiler, **kwargs):
    column, value = element.clauses
    pattern = literal(escape_like(value.value) + "%")
    return f"(BINARY {compiler.process(column, **kwargs)} LIKE {compiler.process(pattern, **kwargs)} ESCAPE '/')"


def case_sensitive_equals(column, keyword: str):
    return _ExactText(column, literal(keyword)).as_comparison(1, 2)


def case_sensitive_prefix(column, keyword: str):
    # Keep a normal-column range candidate before the binary residual predicate.
    return and_(
        column.like(escape_like(keyword) + "%", escape="/"),
        _PrefixText(column, literal(keyword)).as_comparison(1, 2),
    )


def exact_id_priority(column, keyword: str):
    return case((case_sensitive_equals(column, keyword), 0), else_=1)


def subject_match_condition(id_column, name_column, external_id_column, keyword: str, *, name_prefix: bool):
    """Keep name and ID access paths separate; scope remains on the outer query."""
    if not keyword:
        return true()
    pattern = escape_like(keyword) + "%"
    if not name_prefix:
        pattern = "%" + pattern
    names = select(id_column).where(name_column.like(pattern, escape="/")).correlate(None)
    identities = select(id_column).where(case_sensitive_prefix(external_id_column, keyword)).correlate(None)
    return id_column.in_(union(names, identities))


def numeric_subject_match_condition(id_column, name_column, keyword: str, *, name_prefix: bool = True):
    if not keyword:
        return true()
    pattern = escape_like(keyword) + "%"
    if not name_prefix:
        pattern = "%" + pattern
    names = select(id_column).where(name_column.like(pattern, escape="/")).correlate(None)
    ranges = numeric_prefix_ranges(keyword)
    numeric = or_(*(id_column.between(start, end) for start, end in ranges)) if ranges else false()
    identities = select(id_column).where(numeric).correlate(None)
    return id_column.in_(union(names, identities))


def numeric_id_priority(column, keyword: str):
    ranges = numeric_prefix_ranges(keyword)
    if not ranges:
        return literal(1)
    return case((column == int(keyword), 0), else_=1)
