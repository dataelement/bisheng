"""Hosted-application data, state and log MCP tool handlers (`app:manage`).

Everything here is bounded by **the credential's resource owner**, evaluated at
call time so a change of owner takes effect on the next call rather than being
frozen into the key (AC-36). The owner rule is *not* implemented here:

* ⑥ passes ``entry="mcp"`` and lets ``AppQueryService`` / ``PublishStatusService``
  apply it, the same code the CLI door uses;
* ⑤ passes nothing at all — ``AppDataService`` builds owner-only in
  unconditionally (its ``_require_owner`` deliberately ignores ``is_global_super``
  and the tenant-admin check), so a second comparison here would only be a second
  thing to drift.

Every refusal — absent, another tenant's, someone else's — collapses into one
26305 whose payload carries nothing but the ``app_id``. Naming the owner, or
answering differently for "exists but not yours", would let a key enumerate the
tenant's applications.

These tools need the hosted-application runtime layer. The registry hides them
from ``tools/list`` when it is off, and every handler refuses with 16207 as
the second lock.
"""

from __future__ import annotations

from bisheng.app_publish.domain.services.publish_pipeline_service import resource_owner_of
from bisheng.app_publish.domain.services.publish_status_service import PublishStatusService
from bisheng.app_runtime.domain.services.app_data_service import AppDataService
from bisheng.app_runtime.domain.services.app_query_service import LOG_ENTRY_MCP, AppQueryService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.app_factory import AppLogForbiddenError, AppNotFoundError
from bisheng.common.errcode.app_publish import (
    AppNotOwnedBySubjectError,
    AppPublishOwnerOnlyError,
    AppPublishRuntimeLayerDisabledError,
)
from bisheng.common.errcode.mcp_face import McpAppNotOwnedError
from bisheng.common.services.config_service import settings
from bisheng.open_api.domain.context import get_current_open_api_principal
from bisheng.open_mcp.contracts import (
    AppDataResult,
    AppIdInput,
    AppLogsInput,
    AppLogsResult,
    AppRowsInput,
    AppRowUpdateInput,
    AppStatusResult,
    AppTableInput,
)

#: The 16xxx codes that all mean the same thing on this face: "not yours".
#: ``AppDataForbiddenError`` (16162) lives in the same module and is included by
#: class, not by number.
_NOT_YOURS = (
    AppNotFoundError,
    AppLogForbiddenError,
    AppPublishOwnerOnlyError,
    AppNotOwnedBySubjectError,
)


def _actor() -> UserPayload:
    """The natural person this credential creates and reaches resources for.

    Built exactly like the CLI deploy face's actor, and deliberately carrying no
    field that could widen the verdict: no roles, no ``is_global_super``. A key
    with no resource owner raises 16205 rather than silently becoming user 0 —
    a personal access token cannot hold ``app:manage`` anyway, so the registry's
    scope check fires first and this is the second lock.
    """

    principal = get_current_open_api_principal()
    return UserPayload(
        user_id=resource_owner_of(principal),
        user_name=getattr(principal, "actor_name", "") or "",
        user_role=[],
        tenant_id=principal.tenant_id,
    )


def _fold_not_yours(exc: Exception, app_id: str) -> Exception:
    """One answer for absent / another tenant's / somebody else's."""

    from bisheng.common.errcode.app_factory import AppDataForbiddenError

    if isinstance(exc, (*_NOT_YOURS, AppDataForbiddenError)):
        return McpAppNotOwnedError(app_id=app_id)
    return exc


def app_runtime_enabled() -> bool:
    return bool(settings.app_runtime.enabled)


def _require_runtime() -> None:
    if not app_runtime_enabled():
        raise AppPublishRuntimeLayerDisabledError()


async def app_status(arguments: AppIdInput) -> AppStatusResult:
    """Runtime state plus the latest release's approval outcome for one of your apps."""

    _require_runtime()
    app_id = arguments.app_id
    try:
        # ``_actor()`` is inside the guard on purpose: a key with no resource
        # owner raises 16205 from here, and that is one more spelling of "not an
        # application you can reach".
        actor = _actor()
        instance = await AppQueryService.get_instance(app_id, actor=actor, entry=LOG_ENTRY_MCP)
        publish = await PublishStatusService.get_publish_status(app_id, actor=actor, entry=LOG_ENTRY_MCP)
    except Exception as exc:
        raise _fold_not_yours(exc, app_id) from exc
    return AppStatusResult(
        app_id=app_id,
        app_state=publish.get("app_state"),
        instance=instance,
        publish=publish,
    )


async def app_logs(arguments: AppLogsInput) -> AppLogsResult:
    """Recent output of one of your applications — the app's own lines, never the platform's."""

    _require_runtime()
    app_id = arguments.app_id
    try:
        payload = await AppQueryService.get_logs(
            app_id,
            actor=_actor(),
            tail=arguments.tail,
            since=arguments.since,
            keyword=arguments.keyword,
            entry=LOG_ENTRY_MCP,
        )
    except Exception as exc:
        raise _fold_not_yours(exc, app_id) from exc
    # An empty ``lines`` has two causes the text alone cannot separate — quiet
    # app, or no running instance. Same two fields the CLI's ``logs`` prints.
    payload.update(await PublishStatusService.runtime_hint(app_id))
    return AppLogsResult(
        lines=list(payload.get("lines") or []),
        app_state=payload.get("app_state"),
        pending_reason=payload.get("pending_reason"),
    )


async def app_db_tables(arguments: AppIdInput) -> AppDataResult:
    """List the tables in one of your applications' own database."""

    _require_runtime()
    try:
        return AppDataResult(result=await AppDataService.list_tables(arguments.app_id, actor=_actor()))
    except Exception as exc:
        raise _fold_not_yours(exc, arguments.app_id) from exc


async def app_db_schema(arguments: AppTableInput) -> AppDataResult:
    """Read one table's columns and primary key. Schema is declared in `bisheng-app.yaml`; this never changes it."""

    _require_runtime()
    try:
        return AppDataResult(
            result=await AppDataService.get_table_schema(arguments.app_id, arguments.table, actor=_actor())
        )
    except Exception as exc:
        raise _fold_not_yours(exc, arguments.app_id) from exc


async def app_db_rows(arguments: AppRowsInput) -> AppDataResult:
    """Read one page of rows from one of your applications' tables."""

    _require_runtime()
    try:
        return AppDataResult(
            result=await AppDataService.get_rows(
                arguments.app_id,
                arguments.table,
                actor=_actor(),
                page=arguments.page,
                size=arguments.size,
                order=arguments.order,
            )
        )
    except Exception as exc:
        raise _fold_not_yours(exc, arguments.app_id) from exc


async def app_db_row_update(arguments: AppRowUpdateInput) -> AppDataResult:
    """Update one row by its key. Audited with before / after by the data service itself."""

    _require_runtime()
    try:
        return AppDataResult(
            result=await AppDataService.update_row(
                arguments.app_id,
                arguments.table,
                arguments.key,
                arguments.values,
                actor=_actor(),
            )
        )
    except Exception as exc:
        raise _fold_not_yours(exc, arguments.app_id) from exc


APP_HANDLERS = {
    "bisheng_app_status": app_status,
    "bisheng_app_logs": app_logs,
    "bisheng_app_db_tables": app_db_tables,
    "bisheng_app_db_schema": app_db_schema,
    "bisheng_app_db_rows": app_db_rows,
    "bisheng_app_db_row_update": app_db_row_update,
}


__all__ = ["APP_HANDLERS", "app_runtime_enabled"]
