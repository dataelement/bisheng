import json
import tempfile
from typing import Literal

from fastapi import APIRouter, Body, Depends, File, Query, Request, UploadFile
from fastapi.responses import Response
from loguru import logger
from pydantic import ValidationError

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.finetune import InvalidDatasetPackageError
from bisheng.common.schemas.api import PageData, resp_200
from bisheng.core.cache.utils import async_file_download
from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
from bisheng.finetune.domain.models.finetune import Finetune, FinetuneChangeModelName, FinetuneList
from bisheng.finetune.domain.services.datasets import DatasetService
from bisheng.finetune.domain.services.finetune import FinetuneService
from bisheng.finetune.domain.services.finetune_file import FinetuneFileService
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
from bisheng.knowledge.domain.models.knowledge_file import QAKnoweldgeDao

from ..schemas import DatasetImportReq, FinetuneCreateReq, FinetuneInferenceReq, FinetunePreflightReq

router = APIRouter(prefix="/finetune", tags=["Finetune"], dependencies=[Depends(UserPayload.get_tenant_admin_user)])


# create finetune job
@router.post("/job")
async def create_job(
    *, finetune: FinetuneCreateReq, login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user)
):
    # get login user
    request_data = finetune.model_dump(exclude={"method", "contract_version", "capability_id"})
    request_data["extra_params"]["contract_version"] = finetune.contract_version
    if finetune.capability_id:
        request_data["extra_params"]["capability_id"] = finetune.capability_id
    finetune = Finetune(
        **request_data, method=finetune.method.value, user_id=login_user.user_id, user_name=login_user.user_name
    )
    ret = await FinetuneService.create_job(finetune)
    return resp_200(ret)


@router.get("/capabilities")
async def get_capabilities(*, server_id: int):
    return resp_200(await FinetuneService.get_capabilities(server_id))


@router.post("/preflight")
async def preflight(*, request: FinetunePreflightReq):
    return resp_200(await FinetuneService.preflight(request))


@router.post("/job/{job_id}/validate")
async def validate_inference(*, job_id: str, request: FinetuneInferenceReq):
    return resp_200(await FinetuneService.validate_inference(job_id, request))


@router.post("/job/{job_id}/media")
@router.post("/job/{job_id}/validate-media", include_in_schema=False)
async def upload_validation_media(
    *,
    job_id: str,
    file: UploadFile = File(...),
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
):
    try:
        return resp_200(await FinetuneService.upload_validation_media(job_id, file, login_user))
    finally:
        await file.close()


# Delete training task
@router.delete("/job")
async def delete_job(*, job_id: str, login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user)):
    # get login user
    await FinetuneService.delete_job(job_id, login_user)
    return resp_200(None)


# Abort training mission
@router.post("/job/cancel")
async def cancel_job(*, job_id: str, login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user)):
    # get login user
    ret = await FinetuneService.cancel_job(job_id, login_user)
    return resp_200(ret)


# Publish Training Tasks
@router.post("/job/publish")
async def publish_job(*, job_id: str, login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user)):
    # get login user
    ret = await FinetuneService.publish_job(job_id, login_user)
    return resp_200(ret)


@router.post("/job/publish/cancel")
async def cancel_publish_job(*, job_id: str, login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user)):
    # get login user
    ret = await FinetuneService.cancel_publish_job(job_id, login_user)
    return resp_200(ret)


# Get a list of training tasks, support pagination
@router.get("/job")
async def get_job(
    *,
    server: str = Query(default=None, description="RelatedRTService name"),
    status: str = Query(
        default="",
        title="Multiple commas,separator",
        description="the status of the training task,1: Training 2: Training failed 3: Task Aborted 4: Training Successful 5: Publication complete",
    ),
    model_name: str | None = Query(default="", description="Model Name,Fuzzy search"),
    page: int | None = Query(default=1, description="Page"),
    limit: int | None = Query(default=10, description="Listings Per Page"),
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
):
    status_list = []
    if status.strip():
        status_list = [int(one) for one in status.strip().split(",")]
    req_data = FinetuneList(server_name=server, status=status_list, model_name=model_name, page=page, limit=limit)
    data, total = await FinetuneService.get_all_job(req_data)
    return resp_200(data=PageData(data=data, total=total))


# Get the latest details of the task, this interface will synchronize the querySFT-backendThe side updates the task status to the latest
@router.get("/job/info")
async def get_job_info(*, job_id: str, login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user)):
    # get login user
    ret = await FinetuneService.get_job_info(job_id)
    return resp_200(ret)


@router.patch("/job/model")
async def update_job(
    *, req_data: FinetuneChangeModelName, login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user)
):
    # get login user
    ret = await FinetuneService.change_job_model_name(req_data)
    return resp_200(ret)


@router.post("/job/file")
async def upload_file(
    *,
    files: list[UploadFile] = File(description="Training File List"),
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
):
    try:
        ret = await FinetuneFileService.upload_file(files, False, login_user)
        return resp_200(ret)
    except Exception as e:
        logger.error(f"upload finetune file error: {e}")
        raise e

    finally:
        if files:
            for file in files:
                await file.close()


@router.post("/job/file/preset")
async def upload_preset_file(
    *,
    files: str | None = Body(default=None, description="Preset Training File List"),
    name: str | None = Body(description="Dataset Name"),
    qa_list: list[int] | None = Body(default=None, description="QAThe knowledge base upon"),
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
):
    ret = None
    if files:
        filepath, file_name = await async_file_download(files)
        logger.info(f"dataset upload_file_name: {file_name}")
        ret = await FinetuneFileService.upload_preset_file(name, 0, filepath, login_user)
    elif qa_list:
        # will beqaData byfinetuneFormat for file storage
        qa_knowledge_db = await KnowledgeDao.aget_list_by_ids(qa_list)
        qa_knowledge_db_ids = [qa_knowledge.id for qa_knowledge in qa_knowledge_db]
        qa_db_list = await QAKnoweldgeDao.aget_qa_knowledge_by_knowledge_ids(qa_knowledge_db_ids)
        qa_list = []
        for qa in qa_db_list:
            qa_list.extend(
                [
                    {"instruction": question, "input": "", "output": json.loads(qa.answers)[0]}
                    for question in qa.questions
                ]
            )
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as filepath:
            json.dump(qa_list, filepath, ensure_ascii=False, indent=2)
            filepath.seek(0)
            ret = await FinetuneFileService.upload_preset_file(name, 1, filepath.name, login_user)
    return resp_200(ret)


# Get a list of preset training files
@router.get("/job/file/preset")
async def get_preset_file(
    *,
    page_size: int | None = None,
    page_num: int | None = None,
    keyword: str | None = None,
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
):
    ret = await FinetuneFileService.get_preset_file(keyword, page_size, page_num)
    return resp_200(ret)


@router.delete("/job/file/preset")
async def delete_preset_file(*, file_id: str, login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user)):
    # get login user
    await FinetuneFileService.delete_preset_file(file_id, login_user)
    return resp_200()


@router.get("/job/file/download")
async def get_download_url(*, file_url: str, login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user)):
    minio_client = get_minio_storage_sync()
    download_url = await minio_client.get_share_link(file_url, clear_host=False)
    return resp_200(data={"url": download_url})


@router.get("/server/filters")
async def get_server_filters(*, login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user)):
    ret = await FinetuneService.get_server_filters()
    return resp_200(data=ret)


@router.get("/model/list")
async def get_model_list(
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
    server_id: int = Query(..., description="ftService UniqueID"),
):
    """DapatkanftList of all models under the service"""
    ret = await FinetuneService.get_model_list(server_id)
    return resp_200(data=ret)


@router.get("/gpu")
async def get_gpu_info(*, login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user)):
    # get login user
    ret = await FinetuneService.get_gpu_info()
    return resp_200(data=ret)


@router.get("/datasets")
async def list_datasets(
    data_type: Literal["text", "image_text", "video_text"] | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    return resp_200(await DatasetService.list_versions(data_type, page, limit))


async def parse_dataset_import(request: Request) -> DatasetImportReq:
    # The legacy global 422 handler echoes/logs validation inputs. Never send connection
    # credentials to that path, including malformed requests missing a required field.
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 22 * 1024 * 1024:
            raise InvalidDatasetPackageError(msg="Import request exceeds 22 MiB")
    try:
        return DatasetImportReq.model_validate_json(raw)
    except ValidationError as exc:
        errors = exc.errors(include_input=False, include_context=False, include_url=False)
        messages = [f"{'.'.join(map(str, item['loc'])) or 'body'}: {item['msg']}" for item in errors[:5]]
        raise InvalidDatasetPackageError(msg="Invalid import request: " + "; ".join(messages)) from None


@router.post("/datasets/import")
async def import_dataset(
    request: DatasetImportReq = Depends(parse_dataset_import),
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
):
    return resp_200(await DatasetService.import_version(request, login_user))


@router.get("/datasets/{version_id}/preview")
async def preview_dataset(version_id: str):
    return resp_200(await DatasetService.preview(version_id))


@router.get("/datasets/{version_id}/media")
async def preview_dataset_media(version_id: str, path: str = Query(max_length=2048)):
    content, content_type = await DatasetService.media(version_id, path)
    return Response(
        content,
        media_type=content_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
