from typing import Literal

from fastapi import APIRouter, Body, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import Response
from loguru import logger
from pydantic import ValidationError

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.finetune import InvalidDatasetPackageError, InvalidExtraParamsError
from bisheng.common.schemas.api import PageData, resp_200
from bisheng.finetune.api.dependencies import get_dataset_user, get_finetune_user
from bisheng.finetune.domain.models.finetune import Finetune, FinetuneChangeModelName, FinetuneList
from bisheng.finetune.domain.services.datasets import DatasetService
from bisheng.finetune.domain.services.finetune import FinetuneService
from bisheng.finetune.domain.services.finetune_file import FinetuneFileService
from bisheng.finetune.domain.services.task_uploads import TaskUploadService

from ..schemas import DatasetImportReq, FinetuneCreateReq, FinetuneInferenceReq, FinetunePreflightReq

# Tasks use the model menu; datasets retain their own independent menu gate.
router = APIRouter(prefix="/finetune", tags=["Finetune"])


async def parse_create_job(request: Request) -> FinetuneCreateReq:
    # The body may carry dataset source secrets; validation errors must not echo or log it.
    raw = await request.body()
    try:
        return FinetuneCreateReq.model_validate_json(raw)
    except ValidationError as exc:
        errors = exc.errors(include_input=False, include_context=False, include_url=False)
        messages = [f"{'.'.join(map(str, item['loc'])) or 'body'}: {item['msg']}" for item in errors[:5]]
        raise InvalidExtraParamsError(msg="Invalid training request: " + "; ".join(messages)) from None


# create finetune job
@router.post("/job")
async def create_job(
    *,
    finetune: FinetuneCreateReq = Depends(parse_create_job),
    login_user: UserPayload = Depends(get_finetune_user),
):
    credentials = finetune.dataset_credentials
    request_data = finetune.model_dump(exclude={"method", "contract_version", "capability_id"})
    if finetune.contract_version == 2:
        # Legacy extra_params are validated strictly, so only contract v2 carries these markers.
        request_data["extra_params"]["contract_version"] = 2
        if finetune.capability_id:
            request_data["extra_params"]["capability_id"] = finetune.capability_id
    finetune = Finetune(
        **request_data, method=finetune.method.value, user_id=login_user.user_id, user_name=login_user.user_name
    )
    ret = await FinetuneService.create_job(finetune, login_user, credentials)
    return resp_200(ret)


# Contract v2 task endpoints share the task gate: the current tenant's model menu.
@router.get("/capabilities")
async def get_capabilities(*, server_id: int, login_user: UserPayload = Depends(get_finetune_user)):
    return resp_200(await FinetuneService.get_capabilities(server_id))


@router.post("/preflight")
async def preflight(*, request: FinetunePreflightReq, login_user: UserPayload = Depends(get_finetune_user)):
    return resp_200(await FinetuneService.preflight(request))


@router.post("/job/{job_id}/validate")
async def validate_inference(
    *, job_id: str, request: FinetuneInferenceReq, login_user: UserPayload = Depends(get_finetune_user)
):
    return resp_200(await FinetuneService.validate_inference(job_id, request))


@router.post("/job/{job_id}/media")
@router.post("/job/{job_id}/validate-media", include_in_schema=False)
async def upload_validation_media(
    *,
    job_id: str,
    file: UploadFile = File(...),
    login_user: UserPayload = Depends(get_finetune_user),
):
    try:
        return resp_200(await FinetuneService.upload_validation_media(job_id, file, login_user))
    finally:
        await file.close()


# Delete training task
@router.delete("/job")
async def delete_job(*, job_id: str, login_user: UserPayload = Depends(get_finetune_user)):
    # get login user
    await FinetuneService.delete_job(job_id, login_user)
    return resp_200(None)


# Abort training mission
@router.post("/job/cancel")
async def cancel_job(*, job_id: str, login_user: UserPayload = Depends(get_finetune_user)):
    # get login user
    ret = await FinetuneService.cancel_job(job_id, login_user)
    return resp_200(ret)


# Publish Training Tasks
@router.post("/job/publish")
async def publish_job(*, job_id: str, login_user: UserPayload = Depends(get_finetune_user)):
    # get login user
    ret = await FinetuneService.publish_job(job_id, login_user)
    return resp_200(ret)


@router.post("/job/publish/cancel")
async def cancel_publish_job(*, job_id: str, login_user: UserPayload = Depends(get_finetune_user)):
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
    login_user: UserPayload = Depends(get_finetune_user),
):
    status_list = []
    if status.strip():
        status_list = [int(one) for one in status.strip().split(",")]
    req_data = FinetuneList(server_name=server, status=status_list, model_name=model_name, page=page, limit=limit)
    data, total = await FinetuneService.get_all_job(req_data)
    return resp_200(data=PageData(data=data, total=total))


# Get the latest details of the task, this interface will synchronize the querySFT-backendThe side updates the task status to the latest
@router.get("/job/info")
async def get_job_info(*, job_id: str, login_user: UserPayload = Depends(get_finetune_user)):
    # get login user
    ret = await FinetuneService.get_job_info(job_id)
    return resp_200(ret)


@router.patch("/job/model")
async def update_job(*, req_data: FinetuneChangeModelName, login_user: UserPayload = Depends(get_finetune_user)):
    # get login user
    ret = await FinetuneService.change_job_model_name(req_data)
    return resp_200(ret)


@router.post("/job/file")
async def upload_file(
    *,
    files: list[UploadFile] = File(description="Training File List"),
    login_user: UserPayload = Depends(get_finetune_user),
):
    try:
        if len(files) != 1:
            raise InvalidDatasetPackageError(msg="Upload exactly one dataset")
        ret = [await TaskUploadService.upload(files[0], login_user)]
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
    login_user: UserPayload = Depends(get_dataset_user),
):
    ret = await FinetuneFileService.create_dataset(name, files, qa_list, login_user)
    return resp_200(ret)


# Get a list of preset training files
@router.get("/job/file/preset")
async def get_preset_file(
    *,
    page_size: int | None = None,
    page_num: int | None = None,
    keyword: str | None = None,
    login_user: UserPayload = Depends(get_dataset_user),
):
    ret = await FinetuneFileService.get_preset_file(keyword, page_size, page_num)
    return resp_200(ret)


@router.delete("/job/file/preset")
async def delete_preset_file(*, file_id: str, login_user: UserPayload = Depends(get_dataset_user)):
    # get login user
    await FinetuneFileService.delete_preset_file(file_id, login_user)
    return resp_200()


@router.get("/job/file/download")
async def get_download_url(*, file_url: str, login_user: UserPayload = Depends(get_dataset_user)):
    download_url = await FinetuneFileService.get_download_url(file_url, login_user)
    return resp_200(data={"url": download_url})


@router.post("/job/file/preset/upload")
async def stage_dataset_file(*, file: UploadFile = File(...), login_user: UserPayload = Depends(get_dataset_user)):
    try:
        return resp_200(await FinetuneFileService.stage_dataset_file(file, login_user))
    finally:
        await file.close()


@router.get("/server/filters")
async def get_server_filters(*, login_user: UserPayload = Depends(get_finetune_user)):
    ret = await FinetuneService.get_server_filters()
    return resp_200(data=ret)


@router.get("/model/list")
async def get_model_list(
    login_user: UserPayload = Depends(get_finetune_user),
    server_id: int = Query(..., description="ftService UniqueID"),
):
    """DapatkanftList of all models under the service"""
    ret = await FinetuneService.get_model_list(server_id)
    return resp_200(data=ret)


@router.get("/gpu")
async def get_gpu_info(*, login_user: UserPayload = Depends(get_finetune_user)):
    # get login user
    ret = await FinetuneService.get_gpu_info()
    return resp_200(data=ret)


@router.get("/server/options")
async def get_server_options(login_user: UserPayload = Depends(get_finetune_user)):
    return resp_200(await FinetuneService.get_server_options())


@router.get("/training-data")
async def get_training_data(
    page_size: int | None = None,
    page_num: int | None = None,
    keyword: str | None = None,
    login_user: UserPayload = Depends(get_finetune_user),
):
    return resp_200(await FinetuneFileService.get_preset_file(keyword, page_size, page_num, data_type="legacy"))


@router.get("/training-data/download")
async def download_training_data(file_url: str, login_user: UserPayload = Depends(get_finetune_user)):
    return resp_200({"url": await FinetuneFileService.get_download_url(file_url, login_user)})


# Training dataset versions for contract v2 tasks (tenant records; see DatasetService).
@router.get("/datasets")
async def list_datasets(
    data_type: Literal["text", "image_text", "video_text"] | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    login_user: UserPayload = Depends(get_finetune_user),
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
    login_user: UserPayload = Depends(get_dataset_user),
):
    return resp_200(await DatasetService.import_version(request, login_user))


@router.get("/datasets/{version_id}/preview")
async def preview_dataset(version_id: str, login_user: UserPayload = Depends(get_finetune_user)):
    return resp_200(await DatasetService.preview(version_id))


@router.get("/datasets/{version_id}/media")
async def preview_dataset_media(
    version_id: str, path: str = Query(max_length=2048), login_user: UserPayload = Depends(get_finetune_user)
):
    content, content_type = await DatasetService.media(version_id, path)
    return Response(
        content,
        media_type=content_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/dataset-catalog")
async def list_dataset_catalog(
    data_type: Literal["legacy", "text", "image_text", "video_text"] | None = None,
    source_type: Literal["local", "ftp", "sftp", "s3", "qa", "collection"] | None = None,
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    login_user: UserPayload = Depends(get_dataset_user),
):
    return resp_200(await DatasetService.list_catalog(data_type, source_type, keyword, page, limit))


@router.post("/dataset-catalog/files")
async def import_catalog_files(
    files: list[UploadFile] = File(...),
    name: str = Form(..., min_length=1, max_length=100),
    data_type: Literal["legacy", "text", "image_text", "video_text"] = Form(...),
    login_user: UserPayload = Depends(get_dataset_user),
):
    try:
        if len(files) != 1 or not name.strip():
            raise InvalidDatasetPackageError(msg="A name and exactly one dataset are required")
        return resp_200(
            (
                await FinetuneFileService.upload_file(
                    files, False, login_user, expected_type=data_type, name=name.strip()
                )
            )[0]
        )
    finally:
        for file in files:
            await file.close()


@router.post("/dataset-catalog/import")
async def import_catalog_remote(
    request: DatasetImportReq = Depends(parse_dataset_import),
    login_user: UserPayload = Depends(get_dataset_user),
):
    return resp_200(await DatasetService.import_version(request, login_user))


@router.post("/dataset-catalog/{identifier}/convert")
async def convert_catalog_dataset(identifier: str, login_user: UserPayload = Depends(get_dataset_user)):
    return resp_200(await DatasetService.convert(identifier, login_user))


@router.delete("/dataset-catalog/{identifier}")
async def delete_catalog_dataset(identifier: str, login_user: UserPayload = Depends(get_dataset_user)):
    await FinetuneFileService.delete_preset_file(identifier, login_user)
    return resp_200()


@router.get("/dataset-catalog/{identifier}/preview")
async def preview_catalog_dataset(identifier: str, login_user: UserPayload = Depends(get_dataset_user)):
    return resp_200(await DatasetService.catalog_preview(identifier))


@router.get("/dataset-catalog/{identifier}/media")
async def catalog_dataset_media(identifier: str, path: str, login_user: UserPayload = Depends(get_dataset_user)):
    catalog = await DatasetService.get_catalog(identifier)
    if not catalog or not catalog.version_id:
        from bisheng.common.errcode.finetune import TrainFileNotExistError

        raise TrainFileNotExistError()
    content, content_type = await DatasetService.media(catalog.version_id, path)
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/dataset-catalog/{identifier}/download")
async def download_catalog_dataset(identifier: str, login_user: UserPayload = Depends(get_dataset_user)):
    return resp_200(await DatasetService.download_catalog(identifier))


@router.get("/task-uploads/{upload_id}/preview")
async def preview_task_upload(upload_id: str, login_user: UserPayload = Depends(get_finetune_user)):
    return resp_200(await TaskUploadService.preview(upload_id, login_user))


@router.get("/task-uploads/{upload_id}/media")
async def task_upload_media(upload_id: str, path: str, login_user: UserPayload = Depends(get_finetune_user)):
    content, content_type = await TaskUploadService.media(upload_id, path, login_user)
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
