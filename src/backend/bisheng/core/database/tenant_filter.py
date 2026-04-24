"""SQLAlchemy event hooks for automatic tenant filtering and filling.

Registers two global Session events:
- ``do_orm_execute``: Intercepts SELECT queries and injects
  ``WHERE tenant_id = <current>`` for all tenant-aware tables.
- ``before_flush``: Auto-fills ``tenant_id`` on new objects before INSERT.

Known limitation: raw SQL via ``text()`` bypasses ORM events. Callers using
raw SQL must manually add ``WHERE tenant_id = X``.
"""

import logging
from typing import FrozenSet, Optional, Set

from sqlalchemy import event, false
from sqlmodel import Session

from bisheng.core.context.tenant import (
    DEFAULT_TENANT_ID,
    get_current_tenant_id,
    get_visible_tenant_ids,
    is_strict_tenant_filter,
    is_tenant_filter_bypassed,
)

logger = logging.getLogger(__name__)

_tenant_aware_tables: Set[str] = set()
_initialized: bool = False

# Tables that have a tenant_id column but use it as a FK, not as isolation field.
_EXCLUDED_TABLES: Set[str] = {'user_tenant'}


def _discover_tenant_aware_tables() -> Set[str]:
    """Discover tables that have a ``tenant_id`` column from SQLModel metadata.

    This avoids hardcoding table names — any model with a ``tenant_id``
    column will automatically be tenant-filtered.
    """
    from sqlmodel import SQLModel

    tables = set()
    for table_name, table in SQLModel.metadata.tables.items():
        if 'tenant_id' in table.c and table_name not in _EXCLUDED_TABLES:
            tables.add(table_name)
    logger.debug(f'Discovered {len(tables)} tenant-aware tables: {tables}')
    return tables


def register_tenant_filter_events() -> None:
    """Register global Session events for tenant filtering.

    Safe to call multiple times — only registers once.
    Must be called after all ORM models are imported (so metadata is populated).
    """
    global _tenant_aware_tables, _initialized
    if _initialized:
        return

    _tenant_aware_tables = _discover_tenant_aware_tables()
    if not _tenant_aware_tables:
        logger.warning('No tenant-aware tables found. Tenant filtering will be inactive.')

    @event.listens_for(Session, 'do_orm_execute')
    def _on_orm_execute(orm_execute_state):
        """Intercept ORM queries and inject tenant_id WHERE clause."""
        if is_tenant_filter_bypassed():
            return

        if not orm_execute_state.is_select:
            return

        stmt = orm_execute_state.statement

        # Find tenant-aware tables in the query
        tables_to_filter = _get_tenant_tables_from_statement(stmt)
        if not tables_to_filter:
            return

        visible_tenant_ids = _resolve_visible_tenant_ids()
        if visible_tenant_ids is not None:
            if not visible_tenant_ids:
                for _ in tables_to_filter:
                    stmt = stmt.where(false())
            elif len(visible_tenant_ids) == 1:
                tid = next(iter(visible_tenant_ids))
                for table in tables_to_filter:
                    stmt = stmt.where(table.c.tenant_id == tid)
            else:
                tenant_ids = sorted(visible_tenant_ids)
                for table in tables_to_filter:
                    stmt = stmt.where(table.c.tenant_id.in_(tenant_ids))
        else:
            # Resolve current tenant_id
            tid = _resolve_tenant_id()
            if tid is None:
                # Should not reach here — _resolve_tenant_id raises or returns a value
                return

            # Inject WHERE clause for each tenant-aware table
            for table in tables_to_filter:
                stmt = stmt.where(table.c.tenant_id == tid)

        orm_execute_state.statement = stmt

    @event.listens_for(Session, 'before_flush')
    def _on_before_flush(session, flush_context, instances):
        """Auto-fill tenant_id on new objects before INSERT."""
        if is_tenant_filter_bypassed():
            return

        tid = get_current_tenant_id()
        if tid is None:
            from bisheng.common.services.config_service import settings
            if not settings.multi_tenant.enabled:
                tid = DEFAULT_TENANT_ID
            else:
                # In enabled mode without context, skip auto-fill.
                # The do_orm_execute handler will catch reads without context.
                return

        for obj in session.new:
            table_name = _get_table_name(obj)
            if table_name and table_name in _tenant_aware_tables:
                current_val = getattr(obj, 'tenant_id', None)
                if current_val is None or current_val == 0:
                    obj.tenant_id = tid

    _initialized = True
    logger.info(
        f'Tenant filter events registered for {len(_tenant_aware_tables)} tables'
    )


def _get_tenant_tables_from_statement(stmt):
    """Extract SQLAlchemy Table objects that are tenant-aware from a statement.

    Handles:
    - Simple ``select(Model)`` — via ``column_descriptions``
    - Joins and subqueries — via ``froms``
    """
    tables = []

    # Method 1: Use column_descriptions (works for select(Model) patterns)
    if hasattr(stmt, 'column_descriptions'):
        for desc in stmt.column_descriptions:
            entity = desc.get('entity')
            if entity is not None:
                table_name = _get_table_name_from_class(entity)
                if table_name and table_name in _tenant_aware_tables:
                    table = getattr(entity, '__table__', None)
                    if table is not None and table not in tables:
                        tables.append(table)

    # Method 2: Fallback to froms (for joins, subqueries, etc.)
    if not tables:
        froms = getattr(stmt, 'get_final_froms', None)
        froms = froms() if froms else getattr(stmt, 'froms', [])
        for from_clause in froms:
            table_name = getattr(from_clause, 'name', None)
            if table_name and table_name in _tenant_aware_tables:
                if from_clause not in tables:
                    tables.append(from_clause)

    return tables


def _get_table_name_from_class(cls) -> Optional[str]:
    """Get __tablename__ from an ORM class."""
    return getattr(cls, '__tablename__', None)


def _get_table_name(obj) -> Optional[str]:
    """Get table name from an ORM instance."""
    cls = type(obj)
    return _get_table_name_from_class(cls)


def _resolve_tenant_id() -> int:
    """Resolve the effective tenant_id for the current context.

    Returns:
        int: The tenant_id to use for filtering.

    Raises:
        NoTenantContextError: If multi_tenant.enabled=True and no context is set.
    """
    tid = get_current_tenant_id()
    if tid is not None:
        return tid

    from bisheng.common.services.config_service import settings
    if not settings.multi_tenant.enabled:
        return DEFAULT_TENANT_ID
    else:
        from bisheng.common.errcode.tenant import NoTenantContextError
        raise NoTenantContextError()


def _resolve_visible_tenant_ids() -> Optional[FrozenSet[int]]:
    """Resolve the visible tenant IN-list for the current request, if any."""
    if is_strict_tenant_filter():
        return None
    visible = get_visible_tenant_ids()
    if visible is None:
        return None
    return frozenset(int(one) for one in visible)
