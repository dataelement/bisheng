"""DDL string building for the DaMeng alembic impl.

Lives outside ``env.py`` because that module runs alembic context code at import
time and cannot be imported by a test.
"""

from typing import Protocol


class IdentifierPreparer(Protocol):
    """The bit of SQLAlchemy's preparer this module needs."""

    def quote(self, ident: str) -> str: ...


def build_modify_column_ddl(
    preparer: IdentifierPreparer,
    table_name: str,
    column_name: str,
    compiled_type: str,
    schema: str | None = None,
) -> str:
    """``ALTER TABLE t MODIFY c newtype`` — DM8's spelling of a type change.

    Both identifiers go through the preparer. Quoting the column but not the
    table is what broke F056: the table is ``user``, a DM8 reserved word, so the
    statement failed to parse with ``-2007 ... nearby [user]``. ``quote()``
    leaves names alone unless they actually need it, so ordinary tables keep
    their bare form.
    """
    qualified_table = preparer.quote(table_name)
    if schema:
        qualified_table = f"{preparer.quote(schema)}.{qualified_table}"
    return f"ALTER TABLE {qualified_table} MODIFY {preparer.quote(column_name)} {compiled_type}"
