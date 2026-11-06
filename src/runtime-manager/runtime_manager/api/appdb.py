"""Data-plane RPC — ``/v1/apps/{app_id}/db/*`` (AC-56, design D10-C).

Five typed endpoints and nothing that carries SQL. The manager does not know
who is asking: owner narrowing and the audit row are the backend's job
(``AppDataService``), and it is the *only* caller — the F052 MCP data tools go
through that service too, never here directly.

The export answers with a file. It is written under ``{data_root}/exports``
and deleted once the response has been sent, so a large table never
accumulates on disk; the backend streams the bytes onwards and the platform
downloads them.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from runtime_manager.appdb import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, AppDbService
from runtime_manager.auth import verify_hmac
from runtime_manager.config import get_config

router = APIRouter(prefix="/v1/apps/{app_id}/db", tags=["data-plane"], dependencies=[Depends(verify_hmac)])


def _service() -> AppDbService:
    return AppDbService(get_config())


@router.get("/tables")
async def list_tables(app_id: str) -> dict:
    """User tables of the app, alphabetically. ``[]`` is a legitimate answer."""
    return {"tables": _service().list_tables(app_id)}


@router.get("/tables/{table}/schema")
async def table_schema(app_id: str, table: str) -> dict:
    """Columns plus the key the PATCH endpoint addresses rows by."""
    return _service().table_schema(app_id, table)


@router.get("/tables/{table}/rows")
async def table_rows(
    app_id: str,
    table: str,
    page: int = Query(1, ge=1),
    size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    order: str | None = Query(None, description="column or -column; the row key is always the tiebreaker"),
) -> dict:
    return _service().rows(app_id, table, page=page, size=size, order=order)


@router.patch("/tables/{table}/rows/{key}")
async def update_row(app_id: str, table: str, key: str, values: dict[str, Any] = Body(..., embed=True)) -> dict:
    """One row, addressed by the table's key. ``rowcount != 1`` is rolled back."""
    return _service().update_row(app_id, table, key, values)


@router.get("/export")
async def export_table(app_id: str, table: str = Query(...)) -> FileResponse:
    """The whole table as CSV; the temp file is removed after the response."""
    path = _service().export_csv(app_id, table)
    return FileResponse(
        path,
        media_type="text/csv",
        filename=f"{table}.csv",
        background=BackgroundTask(_remove, str(path)),
    )


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass  # already gone — the export dir is scratch space, nothing to report
