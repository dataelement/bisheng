import logging
from logging.config import fileConfig

from sqlalchemy import inspect, text

from alembic import context
from alembic.ddl.impl import DefaultImpl

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.alembic_helpers.online import (
    finalize_online_migration_connection,
)

logger = logging.getLogger("alembic.dm")


def _patch_dm_get_indexes_rows() -> None:
    """Rewrite ``DMDialect._get_indexes_rows`` to stop mutating immutable Rows.

    Why:
      Upstream dmSQLAlchemy implements the function by mutating
      ``Row._data`` to enrich each column row with extra fields from the
      index row. SQLAlchemy 2's Cython ``BaseRow`` makes ``_data``
      immutable and raises
      ``AttributeError: attribute '_data' of 'sqlalchemy.cyextension.resultproxy.BaseRow' objects is not writable``.
      Every ``Table(..., autoload_with=conn)`` reflection then crashes
      (the helper is used by both ``get_multi_indexes`` and
      ``get_multi_unique_constraints``), blocking any migration that uses
      SQLAlchemy expression-language reflection on DM8.

    Fix:
      Re-implement ``_get_indexes_rows`` to return plain dicts merged in
      Python — same shape (``row["key"]`` access), same filtering logic
      (drop rows whose ``index_name`` matches a primary key), no
      ``_data`` mutation.
    """
    try:
        from dmSQLAlchemy.base import DMDialect  # type: ignore[import]
        from sqlalchemy.engine import reflection as _refl
    except ImportError:
        return  # not running on a DaMeng-capable platform

    @_refl.cache  # preserve the original LRU cache decoration
    def _get_indexes_rows(self, connection, schema, filter_names,
                          scope, dblink=None, **kw):
        if isinstance(filter_names, str):
            filter_names = [filter_names]

        schema = self.denormalize_name(schema or self.default_schema_name)
        flag = (schema is not None
                and schema.upper() == self.default_schema_name.upper())

        params = {"param_0": schema}
        col_query = (
            'SELECT table_name as "table_name", index_name as "index_name", '
            'table_owner as "table_owner", column_name as "column_name" '
            'FROM ALL_IND_COLUMNS '
            'WHERE TABLE_OWNER = :param_0 AND TABLE_NAME IN ('
        )
        query_tail = ") ORDER BY index_name"

        if filter_names is None:
            all_objects = self._get_all_objects(
                connection, schema, scope, None, filter_names, dblink, **kw,
            )
        else:
            all_objects = [self.denormalize_name(n) for n in filter_names]

        # Replicate the original placeholder substitution.
        col_query = col_query % {"dblink": dblink or ""}

        col_result = self._run_batches(
            connection, all_objects, col_query, query_tail, dblink, params,
        )

        idx_query = (
            'SELECT table_name as "table_name", index_name as "index_name", '
            'table_owner as "table_owner", index_type as "index_type", '
            'uniqueness as "uniqueness", compression as "compression", '
            'prefix_length as "prefix_length", \'\' as "column_name"\n'
        )
        if flag:
            idx_query += (
                "FROM USER_INDEXES WHERE TABLE_OWNER = :param_0 "
                "AND index_type != 'VIRTUAL' AND GENERATED = 'N' "
                "AND TABLE_NAME IN ("
            )
        else:
            idx_query += (
                "FROM ALL_INDEXES WHERE TABLE_OWNER = :param_0 "
                "AND index_type != 'VIRTUAL' AND GENERATED = 'N' "
                "AND TABLE_NAME IN ("
            )
        idx_query = idx_query % {"dblink": dblink or ""}

        index_result = self._run_batches(
            connection, all_objects, idx_query, query_tail, dblink, params,
        )

        idx_meta = {
            (row["table_name"], row["index_name"], row["table_owner"]): {
                "index_type": row["index_type"],
                "uniqueness": row["uniqueness"],
                "compression": row["compression"],
                "prefix_length": row["prefix_length"],
            }
            for row in index_result
        }

        # Provide defaults for the enriched fields so unmatched rows still
        # satisfy downstream consumers (``get_multi_indexes`` etc.) that do
        # raw ``row["uniqueness"]`` lookups.
        default_extra = {
            "index_type": None,
            "uniqueness": "",
            "compression": None,
            "prefix_length": None,
        }
        merged = []
        for col_row in col_result:
            key = (col_row["table_name"], col_row["index_name"],
                   col_row["table_owner"])
            base = {
                "table_name": col_row["table_name"],
                "index_name": col_row["index_name"],
                "table_owner": col_row["table_owner"],
                "column_name": col_row["column_name"],
            }
            base.update(default_extra)
            extra = idx_meta.get(key)
            if extra is not None:
                base.update(extra)
            merged.append(base)

        pks = {
            row["cons_name"]
            for row in self.get_multi_constraint_data(
                connection, schema, filter_names, scope, None, dblink,
            )
            if row["constraint_type"] == "P"
        }

        return [row for row in merged if row["index_name"] not in pks]

    DMDialect._get_indexes_rows = _get_indexes_rows


_patch_dm_get_indexes_rows()


# Register DaMeng dialect with Alembic.
# Alembic ships implementations for mysql/postgresql/oracle/sqlite but not for
# 'dm'.  Without this registration MigrationContext.configure() raises KeyError.
# DaMeng is Oracle-compatible and uses auto-committed DDL (transactional_ddl=False).
class DaMengImpl(DefaultImpl):
    __dialect__ = "dm"
    transactional_ddl = False

    def create_index(self, index, **kw):  # type: ignore[override]
        """Skip CREATE INDEX on DM8 when the same column list is already indexed.

        Why:
          On a fresh install the schema is bootstrapped via
          ``SQLModel.metadata.create_all()`` before Alembic runs. That call
          creates the model-level ``ix_<table>_<col>`` index for every
          ``Field(index=True)``. Migration scripts then re-create the same
          column index under their own ``idx_<table>_<col>`` name. MySQL
          allows multiple indexes on identical columns; DM8 (Oracle-like)
          rejects with ``-3236 "such column list already indexed"`` and
          aborts the whole upgrade.

          Skipping the duplicate keeps both fresh-install (idempotent) and
          upgrade-from-MySQL (migration runs first time) paths working.
          The pre-existing index is functionally equivalent — same columns,
          same selectivity — so behaviour is preserved.
        """
        try:
            cols = [str(c.name) for c in index.expressions
                    if hasattr(c, "name")]
            table_name = index.table.name if index.table is not None else None
            index_name = (index.name or "").lower()
            if cols and table_name:
                bind = self.connection
                if bind is not None:
                    insp = inspect(bind)
                    existing_indexes = insp.get_indexes(table_name)
                    for existing_idx in existing_indexes:
                        same_name = (existing_idx.get("name") or "").lower() == index_name
                        same_cols = list(existing_idx.get("column_names") or []) == cols
                        if same_name or same_cols:
                            logger.warning(
                                "[dm] Skip create_index %s on %s(%s): "
                                "already present as index %s",
                                index.name, table_name, ",".join(cols),
                                existing_idx.get("name"),
                            )
                            return
                    # A unique INDEX (create_index unique=True) collides with an
                    # existing UNIQUE CONSTRAINT of the same name or same column
                    # set, even though they live in different reflection lists.
                    if index.unique:
                        existing_uqs = insp.get_unique_constraints(table_name)
                        for ex in existing_uqs:
                            same_name = (ex.get("name") or "").lower() == index_name
                            same_cols = list(ex.get("column_names") or []) == cols
                            if same_name or same_cols:
                                logger.warning(
                                    "[dm] Skip create_index UNIQUE %s on %s(%s): "
                                    "equivalent UNIQUE constraint %s already present",
                                    index.name, table_name, ",".join(cols),
                                    ex.get("name"),
                                )
                                return
        except Exception:
            logger.exception(
                "[dm] create_index pre-check failed; falling back to default"
            )
        return super().create_index(index, **kw)

    def alter_column(  # type: ignore[override]
        self, table_name, column_name, nullable=None,
        server_default=False, name=None, type_=None,
        schema=None, autoincrement=None, comment=False,
        existing_comment=None, existing_type=None,
        existing_server_default=None, existing_nullable=None,
        existing_autoincrement=None, **kw,
    ):
        """Emit DM8-compatible ALTER COLUMN DDL.

        Why:
          Alembic's generic ``alter_column`` falls back to PostgreSQL-style
          ``ALTER TABLE t ALTER COLUMN c TYPE NEWTYPE`` for unknown dialects.
          DM8 (Oracle-like) does not parse ``TYPE`` in that position and
          fails with ``-2007 Syntax error nearby [TYPE]``. DM8 expects
          ``ALTER TABLE t MODIFY c NEWTYPE``.

        Scope:
          Currently handles type changes (the case migrations actually use).
          Other column attribute changes (nullable, default, comment) are
          delegated to the default impl, which on DM8 emits MODIFY-style
          DDL via dmSQLAlchemy's compiler for those.
        """
        if type_ is not None:
            from sqlalchemy.schema import Column
            tmp_col = Column(column_name, type_)
            compiled_type = type_.compile(dialect=self.dialect)
            stmt = (
                f"ALTER TABLE {table_name} MODIFY "
                f"{self.dialect.identifier_preparer.quote(column_name)} "
                f"{compiled_type}"
            )
            self._exec(text(stmt))
            # Re-enter for remaining attribute changes (nullable/default/etc.)
            type_ = None
            existing_type = tmp_col.type

        return super().alter_column(
            table_name, column_name,
            nullable=nullable, server_default=server_default,
            name=name, type_=type_, schema=schema,
            autoincrement=autoincrement, comment=comment,
            existing_comment=existing_comment, existing_type=existing_type,
            existing_server_default=existing_server_default,
            existing_nullable=existing_nullable,
            existing_autoincrement=existing_autoincrement, **kw,
        )

    def add_constraint(self, const, **kw):  # type: ignore[override]
        """Skip ADD CONSTRAINT on DM8 when an equivalent constraint exists.

        Why:
          ``SQLModel.metadata.create_all()`` creates UniqueConstraints declared
          on the model at bootstrap. Migration scripts that re-add the same
          (or differently-named) UniqueConstraint will fail on DM8 with
          ``-2109 "Invalid constraint name"`` when the name collides, or
          create a duplicate on the same column set otherwise.

          We short-circuit by matching either the constraint name (case
          insensitive — DM8 normalizes to uppercase) or the column set.
        """
        from sqlalchemy.schema import UniqueConstraint
        try:
            if isinstance(const, UniqueConstraint):
                cols = [str(c.name) for c in const.columns]
                table_name = const.table.name if const.table is not None else None
                const_name = (const.name or "").lower()
                if cols and table_name:
                    bind = self.connection
                    if bind is not None:
                        existing = inspect(bind).get_unique_constraints(table_name)
                        for ex in existing:
                            same_name = (ex.get("name") or "").lower() == const_name
                            same_cols = list(ex.get("column_names") or []) == cols
                            if same_name or same_cols:
                                logger.warning(
                                    "[dm] Skip add UNIQUE %s on %s(%s): "
                                    "equivalent constraint %s already present",
                                    const.name, table_name, ",".join(cols),
                                    ex.get("name"),
                                )
                                return
        except Exception:
            logger.exception(
                "[dm] add_constraint pre-check failed; falling back to default"
            )
        return super().add_constraint(const, **kw)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = SQLModelSerializable.metadata


# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def ensure_alembic_version_table(connection) -> None:
    """Ensure long local revision ids fit into Alembic's version table.

    Uses SQLAlchemy Inspector — dialect-agnostic, works on MySQL and DaMeng.
    """
    from bisheng.core.database.dialect_helpers import table_exists, get_version_num_length

    dialect_name = connection.dialect.name
    if dialect_name not in ("mysql", "dm"):
        return

    if not table_exists(connection, "alembic_version"):
        connection.execute(
            text(
                "CREATE TABLE alembic_version ("
                "version_num VARCHAR(255) NOT NULL PRIMARY KEY"
                ")"
            )
        )
        return

    length = get_version_num_length(connection)
    if length is not None and int(length) < 255:
        # Column resize has no dialect-agnostic Alembic API outside a migration
        # context. Both MySQL and DaMeng support MODIFY syntax for ALTER TABLE.
        connection.execute(
            text("ALTER TABLE alembic_version MODIFY version_num VARCHAR(255) NOT NULL")
        )


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    from bisheng.core.database.manager import sync_get_database_connection
    database_conn_manager = sync_get_database_connection()

    with database_conn_manager.engine.connect() as connection:
        ensure_alembic_version_table(connection)
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()

        # SQLAlchemy 2 autobegin can leave a pending DML transaction on
        # MySQL even when Alembic treats DDL as non-transactional. Commit
        # it explicitly so backfills and alembic_version updates persist.
        finalize_online_migration_connection(connection)


run_migrations_online()
