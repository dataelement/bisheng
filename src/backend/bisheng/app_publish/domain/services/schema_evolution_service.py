"""Structure evolution of the declared application tables — ``precheck_schema`` (AC-09 / T061).

What one release may do to ``database.tables[]`` relative to the version that
is **currently online**, and which of it needs the owner to say so out loud:

* adding a table or a column is *additive* — it goes through without a word
  (AC-42 automates it at go-live);
* dropping a table, dropping a column, or changing a column's ``type`` /
  ``nullable`` / ``default`` is *breaking* — production rows would be lost or
  reinterpreted, so the publish is refused with **16229** until the caller
  confirms (``bisheng deploy --confirm-schema-change`` or the interactive
  prompt the CLI shows on that code).

Three rules that fix the shape of this module:

* **The reference is the online version, not the previous submission.** A
  rejected or withdrawn iteration never reached the database, so diffing
  against it would confirm changes that were never applied and miss the ones
  that were. ``app.current_version_id`` is the only row whose tables exist.
* **The verdict is a pure function of two declarations.** :func:`diff_tables`
  takes two lists and touches nothing else, which is what makes AC-09 testable
  with no database at all; :func:`evaluate` is the thin asynchronous wrapper
  that fetches the reference declaration and nothing more.
* **Confirmation is asked once, on the receive leg.** The gate answers the
  upload itself so the CLI can turn 16229 into a question and re-send; the
  worker's ``precheck_schema`` stage re-derives the same summary purely to
  record it (approval card, publish face) and never re-gates — "confirmed →
  enters the pipeline, no second confirmation at publish" is the AC's wording.

The summary shape ``{has_breaking, items: [{table, column, op}]}`` is design
§4.2 ② / ④ verbatim: it rides in ``payload_snapshot`` / ``detail_snapshot``
and in ``GET /publish-status``, and both front ends are written against it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bisheng.app_publish.domain.models.app_deployment import STAGE_PRECHECK_SCHEMA
from bisheng.app_publish.domain.schemas.app_manifest import AppManifest, DatabaseColumn, DatabaseTable
from bisheng.common.errcode.app_publish import AppSchemaChangeUnconfirmedError
from bisheng.core.database import get_async_db_session
from bisheng.database.models.app import AppDao
from bisheng.database.models.app_version import AppVersionDao

#: ``items[].op`` values. Both front ends switch on these strings.
OP_ADD_TABLE = "add_table"
OP_DROP_TABLE = "drop_table"
OP_ADD_COLUMN = "add_column"
OP_DROP_COLUMN = "drop_column"
OP_MODIFY_COLUMN = "modify_column"

#: The operations that need explicit confirmation (spec AC-09: 改 / 删列; a
#: dropped table drops every column it had).
BREAKING_OPS: frozenset[str] = frozenset({OP_DROP_TABLE, OP_DROP_COLUMN, OP_MODIFY_COLUMN})


@dataclass(slots=True, frozen=True)
class SchemaChangeItem:
    """One structural difference. ``column`` is ``None`` for table-level operations."""

    table: str
    op: str
    column: str | None = None

    @property
    def breaking(self) -> bool:
        return self.op in BREAKING_OPS

    def to_dict(self) -> dict[str, Any]:
        return {"table": self.table, "column": self.column, "op": self.op}


@dataclass(slots=True)
class SchemaChange:
    """The diff between two ``database.tables[]`` declarations."""

    items: list[SchemaChangeItem] = field(default_factory=list)

    @property
    def has_breaking(self) -> bool:
        return any(item.breaking for item in self.items)

    @property
    def is_empty(self) -> bool:
        return not self.items

    def breaking_items(self) -> list[SchemaChangeItem]:
        return [item for item in self.items if item.breaking]

    def to_dict(self) -> dict[str, Any]:
        """Design §4.2's ``{has_breaking, items[]}``."""
        return {"has_breaking": self.has_breaking, "items": [item.to_dict() for item in self.items]}

    def to_payload(self) -> dict[str, Any] | None:
        """What the approval card and the publish face carry: ``None`` when nothing changed.

        ``None`` rather than an empty summary so the panels' "no structure
        change" rendering stays a single ``null`` check, and so a first
        publish (no reference version) and an unchanged iteration read alike.
        """
        return None if self.is_empty else self.to_dict()


# ---------------------------------------------------------------------------
# The pure diff
# ---------------------------------------------------------------------------


def diff_tables(previous: list[DatabaseTable], current: list[DatabaseTable]) -> SchemaChange:
    """Structural diff of two table declarations, in declaration order.

    Table and column identity is the **name** (case-sensitive: SQLite, the
    per-app engine, treats ``Users`` and ``users`` as one table only by
    accident of its case-insensitive identifier rule, and the platform must
    not encode that accident). A renamed column is therefore a drop plus an
    add — and the drop is what makes it breaking, which is the honest answer:
    the platform cannot know a rename from a replacement.
    """
    before = {table.name: table for table in previous}
    after = {table.name: table for table in current}
    items: list[SchemaChangeItem] = []

    for name, table in after.items():
        if name not in before:
            items.append(SchemaChangeItem(table=name, op=OP_ADD_TABLE))
            continue
        items.extend(_diff_columns(name, before[name].columns, table.columns))

    for name in before:
        if name not in after:
            items.append(SchemaChangeItem(table=name, op=OP_DROP_TABLE))

    return SchemaChange(items=items)


def _diff_columns(table: str, previous: list[DatabaseColumn], current: list[DatabaseColumn]) -> list[SchemaChangeItem]:
    before = {column.name: column for column in previous}
    after = {column.name: column for column in current}
    items: list[SchemaChangeItem] = []

    for name, column in after.items():
        if name not in before:
            items.append(SchemaChangeItem(table=table, column=name, op=OP_ADD_COLUMN))
        elif _column_signature(before[name]) != _column_signature(column):
            items.append(SchemaChangeItem(table=table, column=name, op=OP_MODIFY_COLUMN))

    for name in before:
        if name not in after:
            items.append(SchemaChangeItem(table=table, column=name, op=OP_DROP_COLUMN))

    return items


def _column_signature(column: DatabaseColumn) -> tuple[str | None, bool | None, Any]:
    """The three attributes a modification is judged on.

    ``type`` is compared case-insensitively and whitespace-trimmed: ``TEXT``
    and ``text`` are one SQL type, and refusing a publish over a developer's
    capitalisation habit would teach them to reach for ``--confirm-schema-change``
    reflexively — which is the one thing a confirmation gate must not do.
    """
    declared = column.type.strip().lower() if isinstance(column.type, str) else None
    return declared or None, column.nullable, column.default


def tables_of(manifest: AppManifest | dict[str, Any] | None) -> list[DatabaseTable]:
    """The declared tables of a manifest, whether it arrives parsed or as the stored dict.

    ``app_version.manifest`` / ``app_deployment.manifest`` hold ``model_dump()``
    output, and a declaration written before ``columns`` had a schema is still
    a valid dict — re-validating through :class:`DatabaseTable` is what gives
    the two sides one shape to compare.
    """
    if manifest is None:
        return []
    if isinstance(manifest, AppManifest):
        return list(manifest.database.tables)
    database = manifest.get("database") if isinstance(manifest, dict) else None
    raw_tables = database.get("tables") if isinstance(database, dict) else None
    if not isinstance(raw_tables, list):
        return []
    return [DatabaseTable.model_validate(item) for item in raw_tables if isinstance(item, dict)]


# ---------------------------------------------------------------------------
# The stage: reference lookup + the gate
# ---------------------------------------------------------------------------


async def evaluate(app_id: str | None, manifest: AppManifest | dict[str, Any]) -> SchemaChange | None:
    """Diff ``manifest`` against the application's **online** version.

    ``None`` means "nothing to evolve from": a first publish, an application
    that never went online, or a reference version whose row is gone. That is
    distinct from an empty :class:`SchemaChange` (a reference exists and
    nothing differs) only for callers that want to say so; both are ``None``
    on the wire (:meth:`SchemaChange.to_payload`).
    """
    if not app_id:
        return None
    async with get_async_db_session() as session:
        app = await AppDao.aget(session, app_id)
        if app is None or not app.current_version_id:
            return None
        reference = await AppVersionDao.aget(session, app_id, str(app.current_version_id))
    if reference is None:
        return None
    return diff_tables(tables_of(reference.manifest), tables_of(manifest))


def require_confirmation(change: SchemaChange | None, *, confirmed: bool) -> None:
    """The gate: a breaking change without confirmation is 16229.

    ``details`` carries every item (not only the breaking ones) so the CLI can
    print the whole picture before asking, and ``breaking`` separately so the
    question names exactly what the confirmation covers.
    """
    if change is None or not change.has_breaking or confirmed:
        return
    breaking = [item.to_dict() for item in change.breaking_items()]
    raise AppSchemaChangeUnconfirmedError(
        msg="本次发布包含未确认的应用数据表结构变更(改列 / 删列)",
        stage=STAGE_PRECHECK_SCHEMA,
        details={
            "reason": "schema_change_unconfirmed",
            "has_breaking": True,
            "items": [item.to_dict() for item in change.items],
            "breaking": breaking,
        },
        hints=[
            "改列 / 删列会影响线上已有数据, 平台不会替你猜: 请逐项确认后带上 --confirm-schema-change 重新发布",
            "加表 / 加列不需要确认; 只有改列与删列会触发本提示",
            "确认后进入发布管线, 审批单与发布面会展示这次结构变更, 上线时不再二次确认",
        ],
    )
