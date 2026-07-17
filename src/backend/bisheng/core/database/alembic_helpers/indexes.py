"""Index-equivalence helpers shared by Alembic dialect implementations."""

from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.engine import Connection
from sqlalchemy.schema import Index


def _normalized_column_names(values) -> tuple[str, ...]:
    return tuple(str(value).casefold() for value in values if value is not None)


def find_equivalent_index(connection: Connection, index: Index) -> tuple[bool, str | None]:
    """Find an existing index with the same ordered columns and uniqueness.

    Model-created indexes commonly use ``ix_*`` names while historical
    revisions use ``idx_*`` names. Names alone therefore cannot determine
    whether a migration still needs to create an index.

    Functional indexes are deliberately excluded because reflection does not
    provide enough portable information to prove expression equivalence.
    """
    table = index.table
    if table is None:
        return False, None

    expression_names = [getattr(expression, "name", None) for expression in index.expressions]
    if not expression_names or any(name is None for name in expression_names):
        return False, None

    expected_columns = _normalized_column_names(expression_names)
    expected_unique = bool(index.unique)
    inspector = inspect(connection)

    for existing in inspector.get_indexes(table.name, schema=table.schema):
        existing_columns = _normalized_column_names(existing.get("column_names") or ())
        existing_unique = bool(existing.get("unique", False))
        if existing_columns == expected_columns and existing_unique == expected_unique:
            return True, existing.get("name")

    if expected_unique:
        for existing in inspector.get_unique_constraints(table.name, schema=table.schema):
            existing_columns = _normalized_column_names(existing.get("column_names") or ())
            if existing_columns == expected_columns:
                return True, existing.get("name")

    return False, None
