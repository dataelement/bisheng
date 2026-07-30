from datetime import datetime
from urllib.parse import unquote, urlparse
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, Form, Query, Request, UploadFile

from bisheng.api.v1.schemas import resp_200
from bisheng.common.errcode.http_error import ServerError
from bisheng.core.cache.utils import save_download_file, save_uploaded_file
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.role.domain.services.quota_service import QuotaService
from bisheng.utils.util import sync_func_to_async
from bisheng.workstation.domain.services import WorkStationService
from bisheng.workstation.domain.services.media_cover_service import (
    MediaUploadStageTimer,
    WorkstationMediaCoverService,
)

from ..dependencies import LoginUserDep

router = APIRouter()


def _resolve_minio_object_from_filepath(filepath: str, minio_client) -> tuple[str, str]:
    """Parse a stored workstation attachment path into bucket + object name."""
    normalized = filepath.strip()
    if not normalized:
        raise ValueError("filepath is empty")

    parsed = urlparse(normalized)
    path = parsed.path if parsed.scheme in ("http", "https") or parsed.path else normalized.split("?", 1)[0]
    path = path.lstrip("/")
    bucket_name, _, object_name = path.partition("/")
    allowed_buckets = {minio_client.bucket, minio_client.tmp_bucket}
    if bucket_name not in allowed_buckets or not object_name:
        raise ValueError(f"invalid minio filepath: {filepath}")

    decoded_name = unquote(object_name)
    while decoded_name != unquote(decoded_name):
        decoded_name = unquote(decoded_name)
    return bucket_name, decoded_name


@router.get("/files/share-url")
async def get_file_share_url(
    filepath: str = Query(..., description="Stored MinIO path, e.g. /tmp-dir/foo.mp4"),
    login_user=LoginUserDep,
):
    del login_user  # auth gate only
    minio_client = await get_minio_storage()
    try:
        bucket_name, object_name = _resolve_minio_object_from_filepath(filepath, minio_client)
    except ValueError as exc:
        raise ServerError(msg=str(exc), exception=exc) from exc

    if not await minio_client.object_exists(bucket_name, object_name):
        raise ServerError(msg="File not found in object storage")

    share_url = await minio_client.get_share_link(object_name, bucket=bucket_name)
    return resp_200(data={"url": share_url})


@router.post("/knowledgeUpload")
async def knowledge_upload(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    login_user=LoginUserDep,
):
    try:
        file_path = await sync_func_to_async(save_download_file)(file.file, "bisheng", file.filename)
        upload_limit_bytes = await QuotaService.get_knowledge_space_upload_limit_bytes(login_user)
        res = await WorkStationService.uploadPersonalKnowledge(
            request,
            login_user,
            file_path=file_path,
            background_tasks=background_tasks,
            upload_limit_bytes=upload_limit_bytes,
        )
        return resp_200(data=res[0])
    except Exception as exc:
        raise ServerError(msg=f"Knowledge base upload failed: {exc!s}", exception=exc)
    finally:
        file.file.close()


@router.get("/queryKnowledge")
async def query_knowledge_list(request: Request, page: int, size: int, login_user=LoginUserDep):
    res, total = await WorkStationService.queryKnowledgeList(request, login_user, page, size)
    return resp_200(data={"list": res, "total": total})


@router.delete("/deleteKnowledge")
def delete_knowledge(request: Request, file_id: int, login_user=LoginUserDep):
    res = KnowledgeService.delete_knowledge_file(request, login_user, [file_id])
    return resp_200(data=res)


@router.post("/files")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    file_id: str = Form(..., description="Doc.ID"),
    login_user=LoginUserDep,
):
    del request  # reserved for future audit hooks
    file_name = unquote(file.filename)
    is_video = WorkstationMediaCoverService.is_video_filename(file_name)
    timer = MediaUploadStageTimer(file_name, media_kind="video" if is_video else "file", file_id=file_id)
    try:
        timer.stage("handler_enter", content_type=file.content_type or "-")
        minio_client = await get_minio_storage()
        timer.stage("minio_client_ready", endpoint=minio_client.minio_config.endpoint)
        timer.stage("file_read_start")
        file_path = await save_uploaded_file(file, "bisheng", file_name)
        timer.stage("file_minio_put", filepath=file_path)
        file_path = minio_client.clear_minio_share_host(file_path)
        timer.stage("file_clear_host", filepath=file_path)
        payload = {
            "filepath": file_path,
            "filename": file_name,
            "type": file.content_type,
            "user": login_user.user_id,
            "_id": uuid4().hex,
            "createdAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "temp_file_id": file_id,
            "file_id": uuid4().hex,
            "message": "File uploaded successfully",
            "context": "message_attachment",
            # Video cover is extracted at task submit ingest, not on upload.
            "parsing_status": "completed",
        }
        timer.finish(filepath=file_path)
        return resp_200(data=payload)
    except Exception as exc:
        timer.fail(exc)
        raise ServerError(msg=f"File upload failed: {exc!s}", exception=exc) from exc
    finally:
        await file.close()
