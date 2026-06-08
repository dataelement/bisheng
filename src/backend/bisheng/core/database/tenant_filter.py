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

# ORM modules that must be imported before _discover_tenant_aware_tables runs.
# Without this, models that nothing in the FastAPI router chain happens to
# import stay invisible to SQLModel.metadata, and their tables silently slip
# past both before_flush auto-fill and do_orm_execute filtering — which is
# exactly how knowledgefile / flowversion / roleaccess / userrole / ...
# kept writing child-tenant resources to root in v2.5.
_TENANT_AWARE_MODEL_MODULES = (
    # Already on the main router import chain — listed for completeness so
    # _force_import_all_models() guarantees them even if a future refactor
    # severs an indirect import edge.
    'bisheng.database.models.flow',
    'bisheng.database.models.assistant',
    'bisheng.database.models.role',
    'bisheng.database.models.group',
    'bisheng.database.models.audit_log',
    'bisheng.database.models.department',
    'bisheng.database.models.message',
    'bisheng.database.models.session',
    'bisheng.knowledge.domain.models.knowledge',
    'bisheng.knowledge.domain.models.department_knowledge_space',
    'bisheng.llm.domain.models.llm_server',
    'bisheng.llm.domain.models.llm_call_log',
    'bisheng.llm.domain.models.llm_token_log',
    'bisheng.llm.domain.models.tenant_system_model_config',
    'bisheng.workstation.domain.models.tenant_workstation_config',
    'bisheng.org_sync.domain.models.org_sync',
    'bisheng.approval.domain.models.approval_request',
    # Previously *not* on any auto-imported chain — silent tenant-id leaks.
    'bisheng.database.models.failed_tuple',
    'bisheng.database.models.flow_version',
    'bisheng.database.models.role_access',
    'bisheng.database.models.user_group',
    'bisheng.database.models.group_resource',
    'bisheng.database.models.tag',
    'bisheng.database.models.template',
    'bisheng.evaluation.domain.models.evaluation',
    'bisheng.database.models.invite_code',
    'bisheng.database.models.variable_value',
    'bisheng.database.models.report',
    'bisheng.database.models.mark_app_user',
    'bisheng.database.models.mark_record',
    'bisheng.database.models.mark_task',
    'bisheng.user.domain.models.user_role',
    'bisheng.knowledge.domain.models.knowledge_file',
    'bisheng.tool.domain.models.gpts_tools',
    'bisheng.share_link.domain.models.share_link',
    'bisheng.message.domain.models.inbox_message',
    'bisheng.message.domain.models.inbox_message_read',
    'bisheng.channel.domain.models.channel',
    'bisheng.channel.domain.models.article_read_record',
    'bisheng.channel.domain.models.channel_info_source',
    'bisheng.linsight.domain.models.linsight_execute_task',
    'bisheng.linsight.domain.models.linsight_session_version',
    'bisheng.linsight.domain.models.linsight_sop',
    'bisheng.finetune.domain.models.sft_model',
    'bisheng.finetune.domain.models.server',
    'bisheng.finetune.domain.models.preset_train',
    'bisheng.finetune.domain.models.model_deploy',
    'bisheng.finetune.domain.models.finetune',
)


def _force_import_all_models() -> None:
    """Force-import every tenant-aware ORM module so SQLModel.metadata
    fully populates before _discover_tenant_aware_tables() runs.

    Failures are warned but not raised — a missing optional module must
    not break the whole tenant filter registration.
    """
    import importlib
    for module_name in _TENANT_AWARE_MODEL_MODULES:
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001 - log every failure
            logger.warning(
                'Failed to import tenant-aware model module %s: %s. '
                'Tables defined in that module will silently bypass tenant '
                'filtering until the import is fixed.',
                module_name, exc,
            )


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

    _force_import_all_models()
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
                elif current_val != tid:
                    # Defense-in-depth: write proceeds with the explicit
                    # value (could be admin cross-tenant write, or a leaked
                    # default like the v2.5 default=1 bug). Log so anomalies
                    # surface during canary rollout.
                    logger.warning(
                        'tenant_id mismatch on write: table=%s pk=%s '
                        'ctx_tid=%s obj_tid=%s (write proceeded as-is)',
                        table_name, getattr(obj, 'id', None), tid, current_val,
                    )

    _initialized = True
    logger.info(
        f'Tenant filter events registered for {len(_tenant_aware_tables)} tables'
    )


def build_tenant_filter_clause(tenant_col):
    """Return a WHERE clause matching the do_orm_execute event listener's logic.

    The auto tenant filter in ``_on_orm_execute`` can only see tables that
    surface through ``column_descriptions`` or ``get_final_froms`` on the
    outer statement. SQL shapes like ``select(sub.c.id) FROM (select … FROM
    flow UNION ALL select … FROM assistant) AS sub`` hide the inner tables
    behind a Subquery, so the listener finds no tenant-aware table and
    injects no filter — leaking cross-tenant data on the outer SELECT.

    Use this helper at those sites: build the clause once per inner SELECT
    and attach it manually. Keeping the resolution logic here (instead of
    open-coding ``tenant_col == get_current_tenant_id()`` per call site)
    ensures the manual path stays in lockstep with the event listener as
    bypass / visible-ids / strict semantics evolve.

    Returns:
        A SQLAlchemy clause (``tenant_col == X`` or ``tenant_col.in_([…])``
        or ``false()`` for empty visible set), or ``None`` when no filter
        should be applied (bypass active, or ``_resolve_tenant_id`` returned
        ``None`` — the latter only when multi_tenant is disabled and no
        context exists). Callers should treat ``None`` as "skip this WHERE".
    """
    if is_tenant_filter_bypassed():
        return None

    visible = _resolve_visible_tenant_ids()
    if visible is not None:
        if not visible:
            return false()
        if len(visible) == 1:
            return tenant_col == next(iter(visible))
        return tenant_col.in_(sorted(visible))

    tid = _resolve_tenant_id()
    if tid is None:
        return None
    return tenant_col == tid


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
