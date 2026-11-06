"""F056 platform-session-only runtime record read surface."""

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from bisheng.app_governance.domain.services.runtime_audit_export_service import RuntimeAuditExportService
from bisheng.app_governance.domain.services.runtime_audit_query_service import RuntimeAuditQueryService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.app_governance import RuntimeAuditFilterInvalidError
from bisheng.common.schemas.api import resp_200

router = APIRouter(prefix="/app-runtime-audit", tags=["runtime-audit"])
Kind = Literal["model", "capability", "access"]


def filters(request, *, candidate=False):
    allowed = {
        "time_range",
        "start_time",
        "end_time",
        "app_id",
        "visitor_id",
        "credential_id",
        "tenant_id",
        "cursor",
        "limit",
        "kind",
        "query",
        "offset",
    }
    if not candidate:
        allowed -= {"kind", "query", "offset"}
    else:
        allowed -= {"cursor"}
    if set(request.query_params) - allowed or any(
        len(request.query_params.getlist(key)) > 1 for key in request.query_params
    ):
        raise RuntimeAuditFilterInvalidError()
    return {
        key: request.query_params[key]
        for key in ("time_range", "start_time", "end_time", "app_id", "visitor_id", "credential_id")
        if key in request.query_params
    }


@router.get("/records/{kind}")
async def records(
    kind: Kind,
    request: Request,
    tenant_id: int | None = Query(None, gt=0),
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = None,
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    return resp_200(
        await RuntimeAuditQueryService().list(
            user, kind, filters(request), limit=limit, cursor=cursor, tenant_id=tenant_id
        )
    )


@router.get("/candidates/{dimension}")
async def candidates(
    dimension: Literal["app", "visitor", "credential"],
    kind: Kind,
    request: Request,
    tenant_id: int | None = Query(None, gt=0),
    query: str = Query("", max_length=128),
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    user: UserPayload = Depends(UserPayload.get_login_user),
):
    return resp_200(
        await RuntimeAuditQueryService().candidates(
            user,
            kind,
            dimension,
            filters(request, candidate=True),
            tenant_id=tenant_id,
            query=query,
            offset=offset,
            limit=limit,
        )
    )


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot_id: str = Field(min_length=1, max_length=36)
    request_id: str = Field(min_length=1, max_length=128)
    tenant_id: int | None = Field(default=None, gt=0)


@router.post("/exports")
async def create_export(body: ExportRequest, user: UserPayload = Depends(UserPayload.get_login_user)):
    from bisheng.worker.runtime_audit.tasks import runtime_audit_export

    job = await RuntimeAuditExportService().submit(user, body.snapshot_id, body.request_id, tenant_id=body.tenant_id)
    if job.status == "pending":
        runtime_audit_export.apply_async(args=[job.id, job.tenant_id], headers={"tenant_id": job.tenant_id})
    return resp_200({"export_id": job.id, "status": job.status})


@router.get("/exports/{job_id}")
async def export_status(
    job_id: str, tenant_id: int | None = Query(None, gt=0), user: UserPayload = Depends(UserPayload.get_login_user)
):
    return resp_200(await RuntimeAuditExportService().status(user, job_id, tenant_id=tenant_id))


@router.post("/exports/{job_id}/cancel")
async def cancel_export(
    job_id: str, tenant_id: int | None = Query(None, gt=0), user: UserPayload = Depends(UserPayload.get_login_user)
):
    return resp_200(await RuntimeAuditExportService().cancel(user, job_id, tenant_id=tenant_id))


@router.get("/exports/{job_id}/download")
async def download(
    job_id: str, tenant_id: int | None = Query(None, gt=0), user: UserPayload = Depends(UserPayload.get_login_user)
):
    service = RuntimeAuditExportService()
    length = await service.download_size(user, job_id, tenant_id=tenant_id)
    stream = service.download(user, job_id, tenant_id=tenant_id)
    # Validate authorization, ready state and first immutable chunk before HTTP
    # headers commit. Later revocation terminates subsequent chunk delivery.
    first = await anext(stream)

    async def content():
        try:
            yield first
            async for chunk in stream:
                yield chunk
        finally:
            await stream.aclose()

    return StreamingResponse(
        content(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Cache-Control": "no-store",
            "Content-Length": str(length),
            "Content-Disposition": f'attachment; filename="runtime-audit-{job_id}.csv"',
        },
    )
