import asyncio
import hashlib
import io
import json
import re
from typing import Any

from aiohttp import ClientError
from loguru import logger
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.finetune import (
    CancelJobError,
    ChangeModelNameError,
    DeleteJobError,
    ExportJobError,
    FinetunePreflightError,
    GetModelError,
    InvalidDatasetPackageError,
    InvalidExtraParamsError,
    JobStatusError,
    ModelNameExistsError,
    NotFoundJobError,
    TrainDataNoneError,
    UnExportJobError,
    UnsupportedFinetuneCapabilityError,
)
from bisheng.common.errcode.model_deploy import NotFoundModelError
from bisheng.common.errcode.server import NoSftServerError
from bisheng.common.schemas.api import UnifiedResponseModel
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.storage.minio.minio_manager import get_minio_storage, get_minio_storage_sync

from ...utils import parse_gpus, parse_server_host
from ..models.finetune import (
    Finetune,
    FinetuneChangeModelName,
    FinetuneDao,
    FinetuneExtraParams,
    FinetuneList,
    FinetuneStatus,
)
from ..models.model_deploy import ModelDeploy, ModelDeployDao
from ..models.server import Server, ServerDao
from ..models.sft_model import SftModelDao
from ..sft_backend import SFTBackend
from . import transfer
from .finetune_file import FinetuneFileService
from .multimodal import MultimodalFinetuneService


class FinetuneService(MultimodalFinetuneService):
    _tasks: set[asyncio.Task] = set()

    @classmethod
    def _start_background(cls, coroutine):
        task = asyncio.create_task(coroutine)
        cls._tasks.add(task)
        task.add_done_callback(cls._finish_background)

    @classmethod
    def _finish_background(cls, task):
        cls._tasks.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.opt(exception=error).error("Fine-tuning background operation failed")

    @classmethod
    def validate_params(cls, finetune: Finetune) -> UnifiedResponseModel | None:
        """Check request parameters, returningNoneIndicates check passed"""
        cls.validate_model_name(finetune.model_name)
        # Individual Training Sets and Preset Training Sets Use at least one
        if not finetune.train_data and not finetune.preset_data:
            raise TrainDataNoneError()
        if finetune.extra_params.get("contract_version") == 2:
            reports = (finetune.dataset_report or {}).get("files", [])
            if (
                finetune.preset_data
                or not reports
                or any(report.get("data_type") != finetune.data_type for report in reports)
            ):
                raise InvalidDatasetPackageError()
            return None
        try:
            # Check Extra Parameter Values
            finetune.extra_params = FinetuneExtraParams.model_validate(finetune.extra_params).model_dump()
        except ValidationError as e:
            logger.warning("Invalid fine-tuning training options")
            raise InvalidExtraParamsError() from e
        return None

    @classmethod
    def validate_model_name(cls, model_name: str) -> None:
        if not isinstance(model_name, str) or not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,49}", model_name):
            raise InvalidExtraParamsError()

    @classmethod
    async def _is_server_isolated(cls, server: Server) -> bool:
        try:
            host = parse_server_host(server.sft_endpoint)
        except ValueError:
            logger.warning("Invalid FT address for service {}", server.id)
            return False
        for tenant_id, endpoint in await ServerDao.find_sft_owners():
            if tenant_id == get_current_tenant_id() or not endpoint:
                continue
            try:
                foreign_host = parse_server_host(endpoint)
            except ValueError:
                logger.warning("Ignoring an invalid FT binding during ownership validation")
                continue
            if foreign_host == host:
                logger.warning("FT service {} has ambiguous tenant ownership", server.id)
                return False
        return True

    @classmethod
    async def _get_job(cls, job_id: str) -> Finetune:
        job = await FinetuneDao.find_job(job_id)
        if job is None:
            raise NotFoundJobError()
        server = await cls.get_sft_server(job.server)
        if server is None:
            raise NotFoundJobError()
        try:
            same_host = parse_server_host(job.sft_endpoint) == parse_server_host(server.sft_endpoint)
        except ValueError:
            same_host = False
        if not same_host or job.rt_endpoint != server.endpoint:
            raise NotFoundJobError()
        cls.validate_model_name(job.model_name)
        if job.status == FinetuneStatus.PUBLISHED.value:
            await cls._get_published_model(job)
        return job

    @classmethod
    async def _get_published_model(cls, job: Finetune) -> ModelDeploy:
        model = await ModelDeployDao.find_model(job.model_id)
        if model is None or model.server != str(job.server) or model.model != job.model_name:
            raise NotFoundModelError()
        return model

    @classmethod
    def parse_command_params(cls, finetune: Finetune, base_model: ModelDeploy) -> dict:
        """Parse the request parameters and combine them into a training instructioncommandParameters"""
        params = finetune.extra_params.copy()
        # Needs to be inSFT-backendThe service willmodel_nameAbsolute path to the model
        params["model_name_or_path"] = base_model.model
        params["model_template"] = finetune.root_model_name
        params["finetuning_type"] = finetune.method
        if finetune.extra_params.get("contract_version") == 2:
            params["data_type"] = finetune.data_type

        # Special treatedcpu_loadformat, because the transmission method is different --cpu_load means isTrue, no additional parameter values are required
        if params.get("cpu_load") == "false":
            del params["cpu_load"]
        elif params.get("cpu_load") == "true":
            params["cpu_load"] = ""

        # Stitching training set parameters
        params["dataset"] = []
        params["each_max_samples"] = []
        if finetune.extra_params.get("contract_version") != 2:
            # Contract v2 resolves its single dataset in create_job, where pull or push is decided.
            cls.parse_command_train_file(finetune.train_data, params)
            cls.parse_command_train_file(finetune.preset_data, params)
        params["dataset"] = ",".join(params["dataset"])
        params["each_max_samples"] = ",".join(params["each_max_samples"])
        if finetune.extra_params.get("contract_version") == 2:
            params.pop("model_template", None)
            params.pop("each_max_samples", None)
        return params

    @classmethod
    def parse_command_train_file(cls, train_data: list[dict], params: dict):
        """DapatkanminioA public link to the file onSFT-BackendDownload training files"""
        if train_data is None:
            return
        minio_client = get_minio_storage_sync()
        for i in train_data:
            params["dataset"].append(minio_client.get_share_link_sync(i["url"], clear_host=False))
            params["each_max_samples"].append(str(i.get("num", 0)))

    @classmethod
    def validate_status(cls, finetune: Finetune, new_status: int) -> None:
        """Verify that the state change is logical ReturnNoneIndicates success"""
        # Training can only To Training Success, Training Failure, Task Abort
        if finetune.status == FinetuneStatus.TRAINING.value:
            if new_status not in [
                FinetuneStatus.SUCCESS.value,
                FinetuneStatus.FAILED.value,
                FinetuneStatus.CANCEL.value,
            ]:
                raise JobStatusError.http_exception(
                    msg="In training, it can only be changed to training success, training failure, task abort"
                )
        # Training failed can only Becoming in training
        elif finetune.status == FinetuneStatus.FAILED.value:
            if new_status != FinetuneStatus.TRAINING.value:
                raise JobStatusError.http_exception(msg="A training failure can only turn into a training")
        # Task Aborted can only Becoming in training
        elif finetune.status == FinetuneStatus.CANCEL.value:
            if new_status != FinetuneStatus.TRAINING.value:
                raise JobStatusError.http_exception(msg="Task abort can only become in training")
        # Training Successful can only Change to Publish Complete
        elif finetune.status == FinetuneStatus.SUCCESS.value:
            if new_status != FinetuneStatus.PUBLISHED.value:
                raise JobStatusError.http_exception(msg="Training success can only change to release completion")
        # Publication complete can only Become Training Successful
        elif finetune.status == FinetuneStatus.PUBLISHED.value:
            if new_status != FinetuneStatus.SUCCESS.value:
                raise JobStatusError.http_exception(
                    msg="Release completion can only be converted into training success"
                )
        return None

    @classmethod
    async def get_sft_server(cls, server_id: int) -> Server | None:
        server = await cls.get_server(server_id)
        if not server:
            logger.warning("not found rt server data by id: {}", server_id)
            return None
        if not server.sft_endpoint:
            logger.warning("not found sft endpoint by id: {}", server_id)
            return None
        if not await cls._is_server_isolated(server):
            return None
        return server

    @classmethod
    async def verify_job_model_name(cls, model_name: str) -> bool:
        """Correctionmodel_name Already exists?"""
        if await ModelDeployDao.find_model_by_name(model_name):
            raise ModelNameExistsError()
        if await FinetuneDao.find_job_by_model_name(model_name):
            raise ModelNameExistsError()
        return True

    @classmethod
    async def create_job(cls, finetune: Finetune, user: UserPayload, credentials=None) -> Finetune:
        from bisheng.common.errcode.finetune import TaskUploadAlreadyUsedError

        from ..repositories.dataset_catalog import DatasetCatalogRepository

        upload_id = (finetune.train_data or [{}])[0].get("upload_id") if len(finetune.train_data or []) == 1 else None
        fingerprint = None
        if upload_id:
            if (
                finetune.preset_data
                or finetune.train_data[0].get("catalog_id")
                or finetune.train_data[0].get("version_id")
            ):
                from bisheng.common.errcode.finetune import InvalidDatasetPackageError

                raise InvalidDatasetPackageError()
            config = {
                key: getattr(finetune, key) for key in ("server", "base_model", "model_name", "data_type", "method")
            }
            config["parameters"] = finetune.extra_params
            fingerprint = hashlib.sha256(json.dumps(config, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
            existing = await DatasetCatalogRepository.job_by_upload(upload_id)
            if existing:
                if (
                    existing.user_id != user.user_id
                    or (existing.dataset_report or {}).get("request_fingerprint") != fingerprint
                ):
                    raise TaskUploadAlreadyUsedError()
                await cls._get_job(existing.id)
                return existing
        await cls.validate_uploaded_datasets(finetune, user)
        _ = cls.validate_params(finetune)
        if finetune.extra_params.get("contract_version") != 2:
            # Contract v2 uses a tenant dataset version, already re-read from its record by validate_uploaded_datasets.
            await FinetuneFileService.validate_training_files(finetune.train_data, finetune.preset_data, user)

        # CariSFTWhether the service exists
        server = await cls.get_sft_server(finetune.server)
        if not server:
            raise NoSftServerError()

        # Verify that the model name already exists
        await cls.verify_job_model_name(finetune.model_name)

        # Find out if the underlying model exists
        base_model = await ModelDeployDao.find_model(finetune.base_model)
        if not base_model or base_model.server != str(server.id):
            raise NotFoundModelError()
        root_model_name = base_model.model
        # Can find instructions for retraining based on trained and completed models
        if base_job := await FinetuneDao.find_job_by_model_name(base_model.model):
            root_model_name = base_job.root_model_name

        finetune.server_name = server.server
        finetune.rt_endpoint = server.endpoint
        finetune.sft_endpoint = server.sft_endpoint
        finetune.base_model_name = base_model.model
        finetune.root_model_name = root_model_name

        capability_id = finetune.extra_params.pop("capability_id", None)
        contract_version = finetune.extra_params.pop("contract_version", 1)
        if contract_version == 2:
            if not capability_id or not finetune.data_type:
                raise UnsupportedFinetuneCapabilityError()
            from bisheng.finetune.schemas import FinetunePreflightReq

            from ..models.finetune import TrainMethod

            preflight = await cls.preflight(
                FinetunePreflightReq(
                    server=finetune.server,
                    base_model=finetune.base_model,
                    capability_id=capability_id,
                    data_type=finetune.data_type,
                    method=TrainMethod(finetune.method),
                    parameters=finetune.extra_params,
                )
            )
            if not preflight.get("passed"):
                raise FinetunePreflightError()
            finetune.capability_snapshot = preflight.get("capability")
            finetune.stage = "preparing"
            finetune.extra_params["contract_version"] = 2
            finetune.extra_params["capability_id"] = capability_id

        # RecallSFT-backendright of privacyAPIAdd New
        logger.info(f"start create sft job: {finetune.id}")
        # Required for stitching instructionscommandParameters
        command_params = cls.parse_command_params(finetune, base_model)
        if contract_version == 2:
            dataset = finetune.dataset_report["files"][0]
            host = parse_server_host(finetune.sft_endpoint)
            if dataset.get("delivery") == "remote":
                # Secrets stay in this request only: never on the job row, in logs or on the FT disk.
                source = transfer.remote_source(dataset["remote"], credentials)
                await transfer.check_source(host, source)
                command_params["dataset_source"] = source
            command_params["dataset"], mode = await transfer.reference_for(
                host, finetune.train_data[0]["url"], dataset["sha256"]
            )
            if dataset.get("delivery") == "remote":
                mode = "source"
            finetune.dataset_report = {**finetune.dataset_report, "transfer": mode}
        # Persist the stable ID first, so a transport timeout never loses a running remote job.
        if fingerprint:
            finetune.dataset_report = {**finetune.dataset_report, "request_fingerprint": fingerprint}
        try:
            finetune = await FinetuneDao.insert_one(finetune)
        except IntegrityError:
            if upload_id:
                existing = await DatasetCatalogRepository.job_by_upload(upload_id)
                if (
                    existing
                    and existing.user_id == user.user_id
                    and (existing.dataset_report or {}).get("request_fingerprint") == fingerprint
                ):
                    await cls._get_job(existing.id)
                    return existing
                if existing:
                    raise TaskUploadAlreadyUsedError() from None
            raise
        try:
            sft_ret = await SFTBackend.create_job(
                host=parse_server_host(finetune.sft_endpoint), job_id=finetune.id, params=command_params
            )
        except Exception:
            logger.exception("FT submission outcome unknown for job {}", finetune.id)
            finetune.stage = "unknown"
            finetune.reason = "Submission connection interrupted; refresh this task to check its outcome"
            await FinetuneDao.update_job(finetune)
            return finetune
        if not sft_ret[0]:
            logger.error("create sft job rejected: job_id: {}, err: {}", finetune.id, sft_ret[1])
            finetune.status = FinetuneStatus.FAILED.value
            finetune.stage = "failed"
            finetune.reason = str(sft_ret[1])[:4000]
            await FinetuneDao.update_job(finetune)
        logger.info("create sft job success")
        return finetune

    @classmethod
    async def cancel_job(cls, job_id: str, user: UserPayload) -> Finetune:
        # ViewjobTask Information
        finetune = await cls._get_job(job_id)

        # Verify task status change
        new_status = FinetuneStatus.CANCEL.value
        cls.validate_status(finetune, new_status)

        # RecallSFT-backendright of privacyAPICancel Task
        logger.info(f"start cancel job_id: {job_id}, user: {user.user_name}")
        sft_ret = await SFTBackend.cancel_job(host=parse_server_host(finetune.sft_endpoint), job_id=job_id)
        if not sft_ret[0]:
            logger.error(f"cancel sft job error: job_id: {job_id}, err: {sft_ret[1]}")
            raise CancelJobError()
        if finetune.extra_params.get("contract_version") == 2:
            acknowledgement = sft_ret[1] if isinstance(sft_ret[1], dict) else {}
            pending = acknowledgement.get("status") == "CANCELLING" or (
                acknowledgement.get("status") == "RUNNING" and acknowledgement.get("cancel_requested")
            )
            if pending:
                # Acceptance does not mean the training process has exited yet.
                finetune.stage = "cancelling"
                await FinetuneDao.update_job(finetune)
                return finetune
            success, state = await SFTBackend.get_job_status(parse_server_host(finetune.sft_endpoint), job_id)
            if not success:
                raise CancelJobError()
            if state.get("status") == "CANCELLING" or (
                state.get("status") == "RUNNING" and state.get("cancel_requested")
            ):
                finetune.stage = "cancelling"
                await FinetuneDao.update_job(finetune)
                return finetune
            if state.get("status") != "CANCELLED":
                raise CancelJobError()
            finetune.stage = "cancelled"
            finetune.log_path = ""  # Refresh the final FT log after cancellation is confirmed.
        logger.info("change sft job status")
        await FinetuneDao.change_status(job_id, finetune.status, new_status)
        finetune.status = new_status
        await FinetuneDao.update_job(finetune)
        logger.info("cancel sft job success")
        return finetune

    @classmethod
    async def delete_job(cls, job_id: str, user: UserPayload) -> Finetune:
        # ViewjobTask Information
        finetune = await cls._get_job(job_id)

        model_name = finetune.model_name
        if finetune.status == FinetuneStatus.PUBLISHED.value:
            model_name = (await cls._get_published_model(finetune)).model

        # Call the interface to delete the training task
        logger.info(f"start delete sft job: {job_id}, user: {user.user_name}")
        sft_ret = await SFTBackend.delete_job(
            host=parse_server_host(finetune.sft_endpoint), job_id=job_id, model_name=model_name
        )
        if not sft_ret[0]:
            remote_missing = (
                isinstance(sft_ret[1], dict)
                and sft_ret[1].get("http_status") == 404
                and finetune.status != FinetuneStatus.TRAINING.value
            )
            if not remote_missing:
                logger.error("delete sft job error: job_id: {}, err: {}", job_id, sft_ret[1])
                raise DeleteJobError()
            logger.info("Removing non-running local job {} after FT confirmed HTTP 404", job_id)
        await cls.delete_published_model(finetune)
        # Delete training task data
        logger.info("delete sft job data")
        # CleanedminioLog file on
        await FinetuneDao.delete_job(finetune)
        logger.info(f"delete sft job success, data: {finetune.model_dump()}")
        cls._start_background(cls.delete_job_log(finetune))
        return finetune

    @classmethod
    async def delete_job_log(cls, finetune: Finetune):
        minio_client = await get_minio_storage()
        await minio_client.remove_object(object_name=f"/finetune/log/{finetune.id}")

    @classmethod
    async def upload_job_log(cls, finetune: Finetune, log_data: io.BytesIO, length: int) -> str:
        minio_client = await get_minio_storage()
        log_path = f"finetune/log/{finetune.id}"
        await minio_client.put_object(
            bucket_name=minio_client.bucket, object_name=log_path, file=log_data, length=length
        )
        return log_path

    @classmethod
    async def get_job_log(cls, finetune: Finetune) -> str | None:
        expected_path = f"finetune/log/{finetune.id}"
        if finetune.log_path.lstrip("/") != expected_path:
            raise NotFoundJobError()
        minio_client = await get_minio_storage()
        resp = await minio_client.get_object(object_name=expected_path)
        if resp is None:
            return None
        return resp.decode("utf-8")

    @classmethod
    async def delete_published_model(cls, finetune: Finetune) -> str | None:
        """
        Offline the published model, delete the published model data, and return the published model name
        param finetune: Training Tasks
        """
        # Determine training task status
        if finetune.status != FinetuneStatus.PUBLISHED.value:
            return finetune.model_name
        # View published modelsID
        published_model = await cls._get_published_model(finetune)

        # Delete Published Model Data
        await ModelDeployDao.delete_model(published_model)
        logger.info(f"delete published model: {published_model.model}, id: {published_model.id}")
        return published_model.model

    @classmethod
    async def publish_job(cls, job_id: str, user: UserPayload) -> Finetune:
        # ViewjobTask Information
        finetune = await cls._get_job(job_id)
        new_status = FinetuneStatus.PUBLISHED.value
        cls.validate_status(finetune, new_status)

        # RecallSFT-backendright of privacyAPIInterfaces
        logger.info(f"start export sft job: {job_id}, user: {user.user_name}")
        sft_ret = await SFTBackend.publish_job(
            host=parse_server_host(finetune.sft_endpoint), job_id=job_id, model_name=finetune.model_name
        )
        if not sft_ret[0]:
            logger.error(f"export sft job error: job_id: {job_id}, err: {sft_ret[1]}")
            raise ExportJobError()
        # Create Published Model Data
        logger.info("create published model")
        published_model = ModelDeploy(
            model=finetune.model_name,
            server=str(finetune.server),
            endpoint=f"http://{finetune.rt_endpoint}/v2.1/models",
        )
        try:
            published_model = await ModelDeployDao.insert_one(published_model)
        except Exception as e:
            logger.error(f"create published model error: {e!s}")
            published_model = await ModelDeployDao.find_model_by_server_and_name(
                published_model.server, published_model.model
            )

        # Record the name of the model that can be used for training
        await SftModelDao.insert_sft_model(published_model.model)

        # Update training task status
        logger.info("update sft job data")
        finetune.status = new_status
        finetune.model_id = published_model.id
        await FinetuneDao.update_job(finetune)
        logger.info("export sft job success")
        return finetune

    @classmethod
    async def cancel_publish_job(cls, job_id: str, user: UserPayload) -> Finetune:
        # ViewjobTask Information
        finetune = await cls._get_job(job_id)
        new_status = FinetuneStatus.SUCCESS.value
        cls.validate_status(finetune, new_status)

        # RecallSFT-backendright of privacyAPIInterfaces
        logger.info(f"start cancel export sft job: {job_id}, user: {user.user_name}")
        sft_ret = await SFTBackend.cancel_publish_job(
            host=parse_server_host(finetune.sft_endpoint), job_id=job_id, model_name=finetune.model_name
        )
        if not sft_ret[0]:
            logger.error(f"cancel export sft job error: job_id: {job_id}, err: {sft_ret[1]}")
            raise UnExportJobError()
        await cls.delete_published_model(finetune)
        await SftModelDao.delete_sft_model(finetune.model_name)
        logger.info("update finetune status")
        finetune.status = new_status
        finetune.model_id = 0
        await FinetuneDao.update_job(finetune)
        logger.info("cancel export sft job success")
        return finetune

    @classmethod
    async def get_server(cls, server_id: int):
        # Authorization must use a fresh tenant-scoped row, never an id-only cache.
        return await ServerDao.find_server(server_id)

    @classmethod
    async def get_all_job(cls, req_data: FinetuneList) -> (list[Finetune], int):
        job_list, total = await FinetuneDao.find_jobs(req_data)
        # Asynchronous thread update task status
        cls._start_background(cls.sync_all_job_status(job_list))
        return job_list, total

    @classmethod
    async def sync_all_job_status(cls, job_list: list[Finetune]) -> None:
        # Asynchronous threads update the status of bulk tasks
        for finetune in job_list:
            await cls.sync_job_status(finetune, finetune.sft_endpoint)

    @classmethod
    async def get_job_info(cls, job_id: str) -> dict[str, Any]:
        """Get real-time information on tasks in training"""
        # ViewjobTask Information
        finetune = await cls._get_job(job_id)

        # Sync Task Execution
        await cls.sync_job_status(finetune, finetune.sft_endpoint)
        finetune = await cls._get_job(job_id)

        # Get log file
        log_data = None
        train_log = ""
        res_data = []
        if finetune.log_path:
            log_data = await cls.get_job_log(finetune)
            if log_data and log_data.startswith("{"):
                try:
                    stored_logs = json.loads(log_data)
                    if "log_data" in stored_logs:
                        log_data = stored_logs["log_data"]
                        train_log = stored_logs.get("train_log", "")
                except json.JSONDecodeError:
                    logger.debug("Legacy training log contains multiple JSON lines")
            res_data = cls.parse_log_data(log_data)

        published_model = await ModelDeployDao.find_model(finetune.model_id) if finetune.model_id else None
        model_online = bool(
            published_model and published_model.server == str(finetune.server) and published_model.status == "已上线"
        )
        return {
            "finetune": {**finetune.model_dump(), "contract_version": finetune.extra_params.get("contract_version", 1)},
            "model_online": model_online,
            "log": log_data if finetune.status != FinetuneStatus.FAILED.value else finetune.reason,
            "train_log": train_log,
            "config_snapshot": (finetune.report or {}).get("train_config"),
            "loss_data": res_data,  # like [{"step": 10, "loss": 0.5}, {"step": 20, "loss": 0.3}]
            "report": finetune.report if finetune.report else None,
        }

    @classmethod
    def parse_log_data(cls, log_data: str) -> list[dict[str, str]]:
        if log_data is None:
            return []
        res_data = []
        contents = log_data.split("\n")
        for elem in contents:
            if elem.strip() == "":
                continue
            sub_data = {"step": None, "loss": None}
            elem = elem.strip()
            try:
                elem_data = json.loads(elem)
            except json.JSONDecodeError:
                continue
            if not isinstance(elem_data, dict):
                continue
            if elem_data.get("loss", None) is None:
                continue
            sub_data["step"] = elem_data.get("current_steps", elem_data.get("step"))
            sub_data["loss"] = elem_data["loss"]
            res_data.append(sub_data)
        return res_data

    @classmethod
    async def sync_job_status(cls, finetune: Finetune, sft_endpoint: str) -> bool:
        """Reload the task and its verified transport before background I/O."""
        try:
            finetune = await cls._get_job(finetune.id)
        except (NotFoundJobError, NotFoundModelError, InvalidExtraParamsError):
            logger.warning("Skipped unavailable fine-tuning job during status refresh")
            return False
        sft_endpoint = finetune.sft_endpoint
        # A finished job is refreshed once more until its final log has been stored.
        if finetune.status != FinetuneStatus.TRAINING.value and finetune.log_path:
            return True
        logger.info(f"start sync job status: {finetune.id}")

        try:
            sft_ret = await SFTBackend.get_job_status(host=parse_server_host(sft_endpoint), job_id=finetune.id)
        except (ClientError, TimeoutError):
            logger.exception("Could not refresh FT job {}; keeping its last known state", finetune.id)
            return False
        if not sft_ret[0]:
            logger.error(f"get sft job status error: job_id: {finetune.id}, err: {sft_ret[1]}")
            return False
        remote = sft_ret[1]
        finetune.reason = remote.get("reason", "")
        finetune.stage = remote.get("stage", finetune.stage)
        if remote.get("artifacts"):
            finetune.artifact_report = remote["artifacts"]
        if remote.get("dataset_report"):
            finetune.dataset_report = {**(finetune.dataset_report or {}), "execution": remote["dataset_report"]}
        if remote.get("config"):
            finetune.report = {**(finetune.report or {}), "train_config": remote["config"]}
        if remote["status"] == SFTBackend.JOB_FINISHED:
            finetune.status = FinetuneStatus.SUCCESS.value
            if finetune.extra_params.get("contract_version") == 2 and not (
                finetune.artifact_report and finetune.artifact_report.get("complete")
            ):
                finetune.status = FinetuneStatus.FAILED.value
                finetune.stage = "failed"
                finetune.reason = "Training exited successfully but required artifacts are incomplete"
        elif remote["status"] == SFTBackend.JOB_FAILED:
            finetune.status = FinetuneStatus.FAILED.value
        elif remote["status"] == "CANCELLED":
            finetune.status = FinetuneStatus.CANCEL.value
            finetune.stage = "cancelled"
            finetune.log_path = ""  # A failed final-log fetch must be retried on the next refresh.

        # Query task execution logs and reports
        logger.info("start query sft job log and report")
        sft_ret = await SFTBackend.get_job_log(host=parse_server_host(sft_endpoint), job_id=finetune.id)
        if not sft_ret[0]:
            logger.error("get sft job log error: job_id: {}, err: {}", finetune.id, sft_ret[1])
        else:
            logs = sft_ret[1]
            content = {"log_data": logs.get("log_data", ""), "train_log": logs.get("train_log", "")}
            log_data = json.dumps(content).encode("utf-8")
            finetune.log_path = await cls.upload_job_log(finetune, io.BytesIO(log_data), len(log_data))

        # Query Task Evaluation Report
        logger.info("start query sft job report")
        sft_ret = await SFTBackend.get_job_metrics(host=parse_server_host(sft_endpoint), job_id=finetune.id)
        if not sft_ret[0]:
            logger.error(f"get sft job report error: job_id: {finetune.id}, err: {sft_ret[1]}")
        else:
            finetune.report = {**(finetune.report or {}), **(sft_ret[1].get("report") or {})}

        # Changelog and Report Data
        await FinetuneDao.update_job(finetune)
        return True

    @classmethod
    async def change_job_model_name(cls, req: FinetuneChangeModelName) -> Finetune:
        """Modify the model name of the training task"""
        cls.validate_model_name(req.model_name)
        finetune = await cls._get_job(req.id)

        # Verify that the model name already exists
        await cls.verify_job_model_name(req.model_name)

        # Modify Published Model Name
        if not await cls.change_published_model_name(finetune, req.model_name):
            raise ChangeModelNameError()

        # Update training task'smodel_name
        finetune.model_name = req.model_name
        await FinetuneDao.update_job(finetune)

        return finetune

    @classmethod
    async def change_published_model_name(cls, finetune: Finetune, model_name: str) -> bool:
        """Modify the model name of the training task"""
        # Unpublished training tasks do not require actionablemodel
        if finetune.status != FinetuneStatus.PUBLISHED.value:
            return True
        published_model = await cls._get_published_model(finetune)

        # Call the interface to modify the name of the published model
        sft_ret = await SFTBackend.change_model_name(
            parse_server_host(finetune.sft_endpoint), finetune.id, published_model.model, model_name
        )
        if not sft_ret[0]:
            logger.error(f"change model name error: job_id: {finetune.id}, err: {sft_ret[1]}")
            return False

        # Modify pre-trained model name
        await SftModelDao.change_sft_model(published_model.model, model_name)

        # Updating the published model'smodel_name
        published_model.model = model_name
        await ModelDeployDao.update_model(published_model)
        return True

    @classmethod
    async def get_server_filters(cls) -> list[dict[str, Any]]:
        """DapatkanftServer Filter Criteria"""
        server_filters = await FinetuneDao.get_server_filters()
        res = []
        for one in server_filters:
            res.append(
                {
                    "id": one,
                    "server_name": one,
                }
            )
        return res

    @classmethod
    async def get_model_list(cls, server_id: int) -> list[dict]:
        """DapatkanftList of all models under the service"""
        server_info = await cls.get_sft_server(server_id)
        if not server_info:
            raise NoSftServerError()
        flag, model_name_list = await SFTBackend.get_all_model(parse_server_host(server_info.sft_endpoint))
        if not flag:
            logger.error(f"get model list error: server_id: {server_id}, err: {model_name_list}")
            raise GetModelError()
        ret = []
        db_model = await ModelDeployDao.find_model_by_server(str(server_id))
        for one in db_model:
            if one.model in model_name_list:
                ret.append(one)
                model_name_list.remove(one.model)
        for one in model_name_list:
            ret.append(
                await ModelDeployDao.insert_one(
                    ModelDeploy(server=str(server_id), model=one, endpoint=f"http://{server_info.endpoint}/v2.1/models")
                )
            )

        res = []
        for one in ret:
            res.append({"id": one.id, "model": one.model, "sft_support": True})
        return res

    @classmethod
    async def get_server_options(cls) -> list[dict]:
        servers = await ServerDao.find_all_server()
        return [
            {"id": server.id, "server": server.server}
            for server in servers
            if server.sft_endpoint and await cls._is_server_isolated(server)
        ]

    @classmethod
    async def get_gpu_info(cls) -> list[dict]:
        """DapatkanGPUMessage"""
        all_server = await ServerDao.find_all_server()
        res = []
        for server in all_server:
            if not server.sft_endpoint or not await cls._is_server_isolated(server):
                continue
            sft_ret = await SFTBackend.get_gpu_info(parse_server_host(server.sft_endpoint))
            if not sft_ret[0]:
                logger.error(f"get gpu info error: server_id: {server.id}, err: {sft_ret[1]}")
                continue
            gpu_info = parse_gpus(sft_ret[1])
            for one in gpu_info:
                one["server"] = server.server
                res.append(one)
        return res
