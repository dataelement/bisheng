from fastapi import APIRouter, Body, Depends, File, Query, UploadFile
from loguru import logger

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import PageData, resp_200
from bisheng.finetune.api.dependencies import get_dataset_user, get_finetune_user
from bisheng.finetune.domain.models.finetune import Finetune, FinetuneChangeModelName, FinetuneList
from bisheng.finetune.domain.services.finetune import FinetuneService
from bisheng.finetune.domain.services.finetune_file import FinetuneFileService

from ..schemas import FinetuneCreateReq

# Tasks use the model menu; datasets retain their own independent menu gate.
router = APIRouter(prefix="/finetune", tags=["Finetune"])


# create finetune job
@router.post("/job")
async def create_job(*, finetune: FinetuneCreateReq, login_user: UserPayload = Depends(get_finetune_user)):
    # get login user
    finetune = Finetune(
        **finetune.model_dump(exclude={"method"}),
        method=finetune.method.value,
        user_id=login_user.user_id,
        user_name=login_user.user_name,
    )
    ret = await FinetuneService.create_job(finetune, login_user)
    return resp_200(ret)


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
    return resp_200(await FinetuneFileService.get_preset_file(keyword, page_size, page_num))


@router.get("/training-data/download")
async def download_training_data(file_url: str, login_user: UserPayload = Depends(get_finetune_user)):
    return resp_200({"url": await FinetuneFileService.get_download_url(file_url, login_user)})
