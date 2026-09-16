"""``/api/v1/apps/**`` — state actions and the read side of a hosted application.

Binding and delegation only; every rule lives in the domain services. Two
conventions worth knowing before adding an endpoint here:

* **Route order is load bearing.** ``/apps/runtime-status`` is declared before
  ``/apps/{app_id}``; Starlette matches in declaration order, so the reverse
  would turn the super-admin page into a lookup for an application literally
  named "runtime-status". The same applies to ``/apps/_unavailable``, declared
  in ``internal_app_proxy.py`` whose router is included first.
* **Refusals ride inside a 200 envelope.** The services raise 161xx business
  errors and the platform handler wraps them; answering a GET with a real
  403/404 makes the platform SPA navigate the whole page to ``/403`` (design
  pit 25), which for the log tab means losing the app detail page over one tab.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel

from bisheng.app_runtime.domain.services.app_data_service import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, AppDataService
from bisheng.app_runtime.domain.services.app_meta_service import AppMetaService
from bisheng.app_runtime.domain.services.app_query_service import AppQueryService
from bisheng.app_runtime.domain.services.app_state_service import AppStateService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200

router = APIRouter(prefix="/apps", tags=["HostedApp"])


class AppMetaPatch(BaseModel):
    """AC-06 — the writable metadata. ``slug`` is absent by design (AC-08)."""

    name: str | None = None
    description: str | None = None
    #: MinIO object name, never a presigned URL — those expire.
    logo: str | None = None


class AppRowPatch(BaseModel):
    """AC-56 — the columns to change on one row. Scalars only; the key column is refused."""

    values: dict[str, Any]


def _action_payload(result) -> dict:
    """Flatten an ``ActionResult`` for the wire.

    ``ok=False`` is a *successful request* reporting a handled outcome (parked
    for capacity, start failed): the caller needs ``state`` and ``reason`` to
    render it, which a thrown error would not carry (AC-65).
    """
    return {
        "app_id": result.app_id,
        "state": result.state,
        "ok": result.ok,
        "reason": result.reason,
        "version_id": result.version_id,
        "detail": result.detail,
    }


# ---------------------------------------------------------------------------
# reads — the static path must precede the {app_id} pattern
# ---------------------------------------------------------------------------


@router.get("/runtime-status", response_model=UnifiedResponseModel[dict], summary="Runtime environment status")
async def runtime_status(user: UserPayload = Depends(UserPayload.get_login_user)):
    """AC-23 — one endpoint for both deployment shapes; super admin only."""
    return resp_200(data=await AppQueryService.get_runtime_status(actor=user))


@router.get("", response_model=UnifiedResponseModel[list], summary="Hosted applications in the caller's scope")
async def list_apps(user: UserPayload = Depends(UserPayload.get_login_user)):
    """AC-57 — an owner's own apps, or a tenant administrator's whole tenant."""
    return resp_200(data=await AppQueryService.list_apps(actor=user))


@router.get("/{app_id}", response_model=UnifiedResponseModel[dict], summary="Application detail")
async def get_app(app_id: str, user: UserPayload = Depends(UserPayload.get_login_user)):
    """AC-25 — includes ``entry_url`` as a full address; the front end must not compose it."""
    return resp_200(data=await AppQueryService.get_detail(app_id, actor=user))


@router.get("/{app_id}/instance", response_model=UnifiedResponseModel[dict], summary="Instance state and health")
async def get_instance(app_id: str, user: UserPayload = Depends(UserPayload.get_login_user)):
    return resp_200(data=await AppQueryService.get_instance(app_id, actor=user))


@router.get("/{app_id}/logs", response_model=UnifiedResponseModel[dict], summary="Recent application output")
async def get_logs(
    app_id: str,
    tail: int | None = Query(default=None, ge=1, le=5000),
    since: str | None = Query(default=None, description="epoch seconds, or a relative window like 30m / 2h / 7d"),
    keyword: str | None = Query(default=None),
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    """AC-55 — owner or tenant administrator. A refusal is 16161 inside a 200 envelope."""
    return resp_200(data=await AppQueryService.get_logs(app_id, actor=user, tail=tail, since=since, keyword=keyword))


@router.get("/{app_id}/versions", response_model=UnifiedResponseModel[dict], summary="Version list (read-only)")
async def list_versions(
    app_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=200, description="omit to receive every version"),
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    """AC-52 — ``{"data": [...], "total": n}``; the row shape defined here is the
    one the card dropdown, the version tab and the publish tab's version list all
    consume. Without ``page_size`` the list is whole (``total == len(data)``);
    with it the list is one page and ``total`` counts every version. There is
    deliberately no switch or rollback write."""
    return resp_200(data=await AppQueryService.list_versions_page(app_id, actor=user, page=page, page_size=page_size))


# ---------------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------------


@router.patch("/{app_id}", response_model=UnifiedResponseModel[dict], summary="Update application metadata")
async def patch_app(
    app_id: str,
    patch: AppMetaPatch = Body(...),
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    """AC-06 — no state change, no version record. Same method the publish pipeline calls."""
    await AppMetaService.update_meta(
        app_id=app_id,
        name=patch.name,
        description=patch.description,
        logo=patch.logo,
        actor=user,
    )
    return resp_200(data=await AppQueryService.get_detail(app_id, actor=user))


@router.delete("/{app_id}", response_model=UnifiedResponseModel[dict], summary="Delete an application")
async def delete_app(app_id: str, user: UserPayload = Depends(UserPayload.get_login_user)):
    """AC-42 / AC-43 / AC-44 — owner only, blocked while online, purges the data."""
    return resp_200(data=_action_payload(await AppStateService.delete(app_id, actor=user)))


@router.post("/{app_id}/actions/publish", response_model=UnifiedResponseModel[dict], summary="Bring online")
async def publish_app(app_id: str, user: UserPayload = Depends(UserPayload.get_login_user)):
    return resp_200(data=_action_payload(await AppStateService.publish(app_id, actor=user)))


@router.post(
    "/{app_id}/actions/manual-publish",
    response_model=UnifiedResponseModel[dict],
    summary="Retry a parked application without a second approval",
)
async def manual_publish_app(app_id: str, user: UserPayload = Depends(UserPayload.get_login_user)):
    return resp_200(data=_action_payload(await AppStateService.manual_publish(app_id, actor=user)))


@router.post("/{app_id}/actions/stop", response_model=UnifiedResponseModel[dict], summary="Stop an application")
async def stop_app(app_id: str, user: UserPayload = Depends(UserPayload.get_login_user)):
    return resp_200(data=_action_payload(await AppStateService.stop(app_id, actor=user)))


@router.post("/{app_id}/actions/resume", response_model=UnifiedResponseModel[dict], summary="Re-enable an application")
async def resume_app(app_id: str, user: UserPayload = Depends(UserPayload.get_login_user)):
    return resp_200(data=_action_payload(await AppStateService.resume(app_id, actor=user)))


# ---------------------------------------------------------------------------
# data plane (AC-56) — owner only; refusals are 16162 inside a 200 envelope
# ---------------------------------------------------------------------------


@router.get("/{app_id}/data/tables", response_model=UnifiedResponseModel[dict], summary="Tables of the app's database")
async def list_app_tables(app_id: str, user: UserPayload = Depends(UserPayload.get_login_user)):
    return resp_200(data=await AppDataService.list_tables(app_id, actor=user))


@router.get(
    "/{app_id}/data/tables/{table}/schema", response_model=UnifiedResponseModel[dict], summary="Columns of one table"
)
async def get_app_table_schema(app_id: str, table: str, user: UserPayload = Depends(UserPayload.get_login_user)):
    return resp_200(data=await AppDataService.get_table_schema(app_id, table, actor=user))


@router.get("/{app_id}/data/tables/{table}/rows", response_model=UnifiedResponseModel[dict], summary="One page of rows")
async def get_app_table_rows(
    app_id: str,
    table: str,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    order: str | None = Query(default=None, description="column or -column; the row key is always the tiebreaker"),
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    return resp_200(data=await AppDataService.get_rows(app_id, table, actor=user, page=page, size=size, order=order))


@router.patch(
    "/{app_id}/data/tables/{table}/rows/{key}", response_model=UnifiedResponseModel[dict], summary="Edit one row"
)
async def update_app_table_row(
    app_id: str,
    table: str,
    key: str,
    patch: AppRowPatch = Body(...),
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    """Exactly one row; audited as ``app.data_row_edit`` with before / after."""
    return resp_200(data=await AppDataService.update_row(app_id, table, key, patch.values, actor=user))


@router.get("/{app_id}/data/export", summary="Export one table as CSV")
async def export_app_table(
    app_id: str,
    table: str = Query(...),
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    """A file, not an envelope — the platform downloads it as a blob.

    A refusal still arrives as the JSON envelope (the business-error handler
    answers before this body runs), which is why the platform inspects the
    blob's content type before saving it as a CSV.
    """
    filename, content = await AppDataService.export_table(app_id, table, actor=user)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )
