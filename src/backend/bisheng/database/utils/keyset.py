"""Keyset (cursor-based) WHERE clause helper for cursor-paginated list APIs (F027).

For an ordered query with sort columns ``(c0, c1, ..., cN)`` (last typically the
primary-key id tie-breaker), the keyset continuation predicate is::

    WHERE (c0, c1, ..., cN) > (v0, v1, ..., vN)

SQLAlchemy expresses this as ``tuple_(c0, ..., cN) > tuple_(v0, ..., vN)``,
which T001 verified compiles on MySQL, DM (DefaultDialect), and SQLite.

``sort_cols`` accepts any SQLAlchemy ``ColumnElement`` — including ``case()``
expressions (used by F027 for ``knowledge_file.ext_rank``, see spec AD-14).
"""
from __future__ import annotations

from typing import Sequence, Union

from sqlalchemy import tuple_
from sqlalchemy.sql.elements import ColumnElement


# DM8 (达梦 v8) at runtime rejects SQL-standard row-value comparison
# ``(a, b) < (?, ?)`` with [CODE:-2007] syntax error, even though T001's
# dialect-stub smoke test (`DefaultDialect`-based) compiled it cleanly. The
# fallback below expands the predicate into nested
# ``OR (col = val AND ...)`` form, which is semantically equivalent and uses
# the same composite index on every dialect we ship to (MySQL, DM, SQLite).
# Keep this True until/unless a real performance regression appears.
_USE_EXPANDED_FALLBACK = True


def build_keyset_where(
    sort_cols: Sequence[ColumnElement],
    cursor_values: Sequence,
    *,
    descending: Union[bool, Sequence[bool]] = False,
) -> ColumnElement:
    """Build a ``WHERE (sort_cols) > (cursor_values)`` boolean expression.

    Args:
        sort_cols: SQLAlchemy column elements in sort order; last is the id
            tie-breaker. Can include ``case()`` expressions for computed
            sort keys (e.g. F027 ``ext_rank``).
        cursor_values: Python values from the decoded cursor; same length and
            order as ``sort_cols``.
        descending: Direction of each sort column.

            - ``bool`` (default ``False``): single direction shared by all
              columns. ``True`` → ``<`` predicate (ORDER BY col DESC);
              ``False`` → ``>`` (ASC). Uses SQL row-value comparison
              (``tuple_() < tuple_()``) for compactness.
            - ``Sequence[bool]``: per-column direction. Required when the
              ORDER BY mixes ASC and DESC across columns (e.g. F027
              ``knowledge_file``: file_type ASC, ext_rank ASC, update_time
              DESC, id DESC). Falls back to the expanded
              ``OR (col = val AND ...)`` form because tuple comparison
              can't express mixed directions.

    Returns:
        SQLAlchemy boolean expression suitable for ``select().where(...)``.

    Raises:
        ValueError: If the lengths of ``sort_cols`` / ``cursor_values`` /
            ``descending`` (when sequence) differ.

    Note:
        Callers should pass ``None`` cursor as the first-page case **before**
        calling this helper (i.e. omit the predicate entirely on first page);
        this function does not special-case ``None``.
    """
    if len(sort_cols) != len(cursor_values):
        raise ValueError(
            f"sort_cols/cursor_values length mismatch: "
            f"{len(sort_cols)} vs {len(cursor_values)}"
        )

    if isinstance(descending, bool):
        if _USE_EXPANDED_FALLBACK:
            return _expanded_keyset_where(sort_cols, cursor_values, descending=descending)
        left = tuple_(*sort_cols)
        right = tuple_(*cursor_values)
        return left < right if descending else left > right

    # Per-column direction (mixed ASC/DESC) — must expand because tuple
    # comparison can't express mixed directions.
    if len(descending) != len(sort_cols):
        raise ValueError(
            f"descending sequence length mismatch: {len(descending)} vs {len(sort_cols)}"
        )
    return _expanded_keyset_where(sort_cols, cursor_values, descending=list(descending))


def _expanded_keyset_where(
    sort_cols: Sequence[ColumnElement],
    cursor_values: Sequence,
    *,
    descending: Union[bool, Sequence[bool]] = False,
) -> ColumnElement:
    """Expand ``(a, b, id) > (a0, b0, id0)`` into

        a > a0 OR (a = a0 AND b > b0) OR (a = a0 AND b = b0 AND id > id0)

    Used when (a) a future dialect rejects ``tuple_()`` row-value comparison,
    or (b) the keyset mixes ASC/DESC directions per column (tuple comparison
    can't express that).

    ``descending`` may be a single bool (shared direction) or a per-column
    sequence of bools. Each ``True`` flips the strict comparator from ``>``
    to ``<`` at that column position.
    """
    from sqlalchemy import and_, or_

    if isinstance(descending, bool):
        descending_seq = [descending] * len(sort_cols)
    else:
        descending_seq = list(descending)

    clauses = []
    for i in range(len(sort_cols)):
        equality_prefix = [
            sort_cols[j] == cursor_values[j] for j in range(i)
        ]
        strict = (sort_cols[i] < cursor_values[i]) if descending_seq[i] else (sort_cols[i] > cursor_values[i])
        clauses.append(and_(*equality_prefix, strict) if equality_prefix else strict)

    return or_(*clauses)
