from loguru import logger
from sqlalchemy.exc import IntegrityError

from bisheng.common.errcode.finetune import (
    FinetuneInferenceValidationError,
    FinetunePreflightError,
    FinetuneServiceOutdatedError,
    GetModelError,
    InvalidDatasetPackageError,
    UnsupportedFinetuneCapabilityError,
)
from bisheng.common.errcode.model_deploy import NotFoundModelError
from bisheng.common.errcode.server import NoSftServerError
from bisheng.finetune.domain.models.finetune import FinetuneDao, FinetuneStatus
from bisheng.finetune.domain.models.model_deploy import ModelDeploy, ModelDeployDao
from bisheng.finetune.domain.repositories.dataset import FinetuneDatasetRepository
from bisheng.finetune.domain.sft_backend import SFTBackend
from bisheng.finetune.utils import parse_server_host

from . import transfer


class MultimodalFinetuneService:
    @classmethod
    async def get_capabilities(cls, server_id: int) -> dict:
        server = await cls.get_sft_server(server_id)
        if not server:
            raise NoSftServerError()
        success, data = await SFTBackend.get_capabilities(parse_server_host(server.sft_endpoint))
        if not success and isinstance(data, dict) and data.get("http_status") == 404:
            # Training services before the multimodal release have no capability catalog.
            raise FinetuneServiceOutdatedError()
        if not success or not isinstance(data, dict):
            raise GetModelError()
        deployed = await ModelDeployDao.find_model_by_server(str(server_id))
        by_name = {item.model: item for item in deployed}
        models = []
        for capability in data.get("models", []):
            model = by_name.get(capability.get("model_name"))
            if model is None and capability.get("model_name"):
                try:
                    model = await ModelDeployDao.insert_one(
                        ModelDeploy(
                            server=str(server_id),
                            model=capability["model_name"],
                            endpoint="",
                            remark="Training base model discovered from FT",
                        )
                    )
                except IntegrityError:
                    model = await ModelDeployDao.find_model_by_server_and_name(str(server_id), capability["model_name"])
                if model is None:
                    raise GetModelError()
                by_name[model.model] = model
            models.append(
                {
                    **capability,
                    "base_model_id": model.id if model else None,
                    "registered": model is not None,
                }
            )
        return {"contract_version": data.get("contract_version", 2), "models": models}

    @classmethod
    async def preflight(cls, request) -> dict:
        server = await cls.get_sft_server(request.server)
        if not server:
            raise NoSftServerError()
        base_model = await ModelDeployDao.find_model(request.base_model)
        if not base_model or str(base_model.server) != str(request.server):
            raise NotFoundModelError()
        capabilities = await cls.get_capabilities(request.server)
        capability = next(
            (item for item in capabilities["models"] if item["capability_id"] == request.capability_id),
            None,
        )
        if not capability or capability.get("model_name") != base_model.model:
            raise UnsupportedFinetuneCapabilityError()
        payload = {
            "capability_id": request.capability_id,
            "data_type": request.data_type,
            "method": request.method.value,
            "parameters": request.parameters,
        }
        success, data = await SFTBackend.preflight(parse_server_host(server.sft_endpoint), payload)
        if not success or not isinstance(data, dict):
            raise FinetunePreflightError()
        return data

    @classmethod
    async def validate_inference(cls, job_id: str, request) -> dict:
        # _get_job also proves the job's training service still belongs to this tenant.
        finetune = await cls._get_job(job_id)
        if (
            finetune.status != FinetuneStatus.SUCCESS.value
            or not finetune.artifact_report
            or not finetune.artifact_report.get("complete")
        ):
            raise FinetuneInferenceValidationError()
        payload = request.model_dump()
        if finetune.data_type != "text":
            media = await FinetuneDatasetRepository.find_by_url(request.media_url or "")
            if (
                not media
                or media.purpose != "inference"
                or media.job_id != job_id
                or media.report["data_type"] != finetune.data_type
            ):
                raise FinetuneInferenceValidationError()
            payload["media_url"], mode = await transfer.reference_for(
                parse_server_host(finetune.sft_endpoint), media.url, media.report["sha256"]
            )
        elif request.media_url:
            raise FinetuneInferenceValidationError()
        success, data = await SFTBackend.validate_inference(
            parse_server_host(finetune.sft_endpoint),
            job_id,
            payload,
        )
        if not success or not isinstance(data, dict):
            logger.error("FT inference validation for job {} failed: {}", job_id, str(data)[:2000])
            raise FinetuneInferenceValidationError()
        if finetune.data_type != "text":
            data = {**data, "transfer": mode}
        previous = finetune.inference_validation or {}
        key = "baseline" if request.baseline else "adapter"
        finetune.inference_validation = {**previous, key: data, "last_result": data}
        finetune.stage = "completed"
        await FinetuneDao.update_job(finetune)
        return data

    @classmethod
    async def validate_uploaded_datasets(cls, finetune):
        if finetune.extra_params.get("contract_version") != 2:
            return
        if finetune.preset_data or len(finetune.train_data or []) != 1:
            raise InvalidDatasetPackageError.http_exception(msg="Select exactly one uploaded dataset version")
        reports = []
        for item in finetune.train_data:
            record = await FinetuneDatasetRepository.find_by_url(item.get("url", ""))
            if not record or record.purpose != "training" or record.report.get("data_type") != finetune.data_type:
                raise InvalidDatasetPackageError()
            item["id"] = record.id
            item["name"] = record.name
            item["num"] = record.report["samples"]
            reports.append({**record.report, "version_id": record.id})
        finetune.dataset_report = {"files": reports}

    @classmethod
    async def upload_validation_media(cls, job_id, file, user):
        from .finetune_file import FinetuneFileService

        job = await cls._get_job(job_id)
        if job.status != FinetuneStatus.SUCCESS.value or job.data_type not in {"image_text", "video_text"}:
            raise FinetuneInferenceValidationError()
        return await FinetuneFileService.upload_validation_media(job_id, job.data_type, file, user)
