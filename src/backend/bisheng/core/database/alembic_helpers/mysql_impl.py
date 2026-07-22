"""BiSheng-specific Alembic implementation for MySQL."""

from __future__ import annotations

import logging

from alembic.ddl.mysql import MySQLImpl

from bisheng.core.database.alembic_helpers.indexes import find_equivalent_index

logger = logging.getLogger("alembic.mysql")


class BishengMySQLImpl(MySQLImpl):
    """Avoid duplicate model/migration indexes with different names."""

    __dialect__ = "mysql"

    def create_index(self, index, **kw):  # type: ignore[override]
        try:
            equivalent, existing_name = find_equivalent_index(self.connection, index)
            if equivalent:
                logger.warning(
                    "Skip create_index %s on %s: equivalent index %s already exists",
                    index.name,
                    index.table.name if index.table is not None else "<unknown>",
                    existing_name or "<unnamed>",
                )
                return None
        except Exception:
            logger.exception("MySQL equivalent-index check failed; falling back to default")

        return super().create_index(index, **kw)
