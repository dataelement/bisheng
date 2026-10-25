"""Keep the shipped SDK's relative API and error envelope during storage migration."""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.routing import APIRoute

from bisheng.app_runtime.domain.services.app_storage_service import AppStorageError, AppStorageService
from bisheng.common.services.config_service import settings


class StorageRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            try:
                return await original(request)
            except AppStorageError as exc:
                return JSONResponse(
                    status_code=exc.status, content={"detail": {"code": exc.code, "message": str(exc), **exc.detail}}
                )

        return handler


router = APIRouter(prefix="/apps/{app_id}/storage", tags=["Application Storage"], route_class=StorageRoute)


def service():
    return AppStorageService(max_file_bytes=settings.app_runtime.storage_max_file_mb * 1024 * 1024)


async def binding(app_id: str, request: Request, svc=Depends(service)):
    if not settings.app_runtime.enabled:
        raise AppStorageError("storage_unavailable", "Runtime layer disabled", 503)
    authorization = request.headers.get("authorization", "")
    token = authorization[7:] if authorization.startswith("Bearer ") else ""
    return await svc.authorize(app_id, token)


@router.get("/objects")
async def objects(
    prefix: str = "",
    cursor: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    scope=Depends(binding),
    svc=Depends(service),
):
    return await svc.list(scope, prefix=prefix, cursor=cursor, limit=limit)


@router.get("/meta/{key:path}")
async def meta(key: str, scope=Depends(binding), svc=Depends(service)):
    return await svc.stat(scope, key)


@router.put("/objects/{key:path}")
async def put(key: str, request: Request, scope=Depends(binding), svc=Depends(service)):
    raw = request.headers.get("content-length")
    if raw is not None and not raw.isdigit():
        raise AppStorageError("invalid_request", "Invalid content length")
    return await svc.put(
        scope,
        key,
        request.stream(),
        content_type=request.headers.get("content-type", "application/octet-stream"),
        content_length=int(raw) if raw else None,
    )


@router.get("/objects/{key:path}")
async def get(key: str, scope=Depends(binding), svc=Depends(service)):
    record = await svc.stat(scope, key)
    return StreamingResponse(svc.get(scope, key), media_type=record.get("content_type") or "application/octet-stream")


@router.delete("/objects/{key:path}")
async def delete(key: str, scope=Depends(binding), svc=Depends(service)):
    await svc.delete(scope, key)
    return {}
