import json
from typing import Literal

from aiohttp import ClientTimeout

from bisheng.core.external.http_client.http_client_manager import get_http_client


class SFTBackend:
    """Packaging andSFT-BackendInteraction"""

    # of fine-tuning training instructionsoptionsParameters Listing
    CMD_OPTIONS = ["train"]

    # jobStatus Misi
    JOB_FINISHED = "FINISHED"
    JOB_FAILED = "FAILED"

    @classmethod
    async def handle_response(cls, res, *, include_http_status: bool = False) -> (bool, str | None | dict):
        content = await res.content.read()
        if res.status != 200:
            detail = content.decode("utf-8", errors="replace")
            return False, {"http_status": res.status, "detail": detail} if include_http_status else detail
        result = json.loads(content)
        if result.get("status_code") != 200:
            return False, content.decode("utf-8")
        return True, result.get("data", None)

    @classmethod
    async def _base_request(
        cls, method: Literal["get", "post", "put"], *args, include_http_status: bool = False, **kwargs
    ) -> (bool, str | dict):
        client = await get_http_client()
        client = await client.get_aiohttp_client()
        if method == "get":
            res = await client.get(*args, **kwargs)
        elif method == "put":
            res = await client.put(*args, **kwargs)
        else:
            res = await client.post(*args, **kwargs)
        return await cls.handle_response(res, include_http_status=include_http_status)

    @classmethod
    async def create_job(cls, host: str, job_id: str, params: dict) -> (bool, str | dict):
        """
        host RTof servicehost<g id="Bold">Address:</g>
        job_id is unique to the instruction id, UUID format
        options Is InstructionoptionsParameters
        params Is InstructionalcommandParameter Parameter
        """
        uri = "/v2.1/sft/job"
        url = "/v2.1/models/sft_elem/infer"
        return await cls._base_request(
            "post", f"{host}{url}", json={"uri": uri, "job_id": job_id, "options": cls.CMD_OPTIONS, "params": params}
        )

    @classmethod
    async def cancel_job(cls, host: str, job_id: str) -> (bool, str | dict):
        """Cancel training task"""
        uri = "/v2.1/sft/job/cancel"
        url = "/v2.1/models/sft_elem/infer"
        return await cls._base_request("post", f"{host}{url}", json={"uri": uri, "job_id": job_id})

    @classmethod
    async def delete_job(cls, host: str, job_id: str, model_name: str) -> (bool, str | dict):
        """Delete training task"""
        uri = "/v2.1/sft/job/delete"
        url = "/v2.1/models/sft_elem/infer"
        return await cls._base_request(
            "post",
            f"{host}{url}",
            json={"uri": uri, "job_id": job_id, "model_name": model_name},
            include_http_status=True,
        )

    @classmethod
    async def publish_job(cls, host: str, job_id: str, model_name: str) -> (bool, str | dict):
        """Publish Training Tasks From training path to formal path"""
        uri = "/v2.1/sft/job/publish"
        url = "/v2.1/models/sft_elem/infer"
        return await cls._base_request(
            "post", f"{host}{url}", json={"uri": uri, "job_id": job_id, "model_name": model_name}
        )

    @classmethod
    async def cancel_publish_job(cls, host: str, job_id: str, model_name: str) -> (bool, str | dict):
        """Deactivate Training Task Published Model"""
        uri = "/v2.1/sft/job/publish/cancel"
        url = "/v2.1/models/sft_elem/infer"
        return await cls._base_request(
            "post", f"{host}{url}", json={"uri": uri, "job_id": job_id, "model_name": model_name}
        )

    @classmethod
    async def get_job_status(cls, host: str, job_id: str) -> (bool, str | dict):
        """
        Get training task status
        Interface return format:
        {
           "status": "FINISHED",
           "reason": "Failure Reason"
        }
        """
        uri = "/v2.1/sft/job/status"
        url = "/v2.1/models/sft_elem/infer"
        return await cls._base_request("post", f"{host}{url}", json={"uri": uri, "job_id": job_id})

    @classmethod
    async def get_job_log(cls, host: str, job_id: str) -> (bool, str | dict):
        """
        Get the training task log and use it temporarilydictFormat - Returns the contents of the
        TODO zgq Subsequent AdoptionhttpStandard File Transfer Format
        Data format returned by the interface
        {
            "log_data": Ref.bisheng-ftProduction Training Log File Contents
        }
        """
        uri = "/v2.1/sft/job/log"
        url = "/v2.1/models/sft_elem/infer"
        return await cls._base_request("post", f"{host}{url}", json={"uri": uri, "job_id": job_id})

    @classmethod
    async def get_job_metrics(cls, host: str, job_id: str) -> (bool, str | dict):
        """
        Get training mission final report
        Interface return data format
        {
            "report": {}
        }
        """
        uri = "/v2.1/sft/job/metrics"
        url = "/v2.1/models/sft_elem/infer"
        return await cls._base_request("post", f"{host}{url}", json={"uri": uri, "job_id": job_id})

    @classmethod
    async def change_model_name(cls, host, job_id: str, old_model_name: str, model_name: str) -> (bool, str):
        """Modify Model Name"""
        uri = "/v2.1/sft/job/model_name"
        url = "/v2.1/models/sft_elem/infer"
        return await cls._base_request(
            "post",
            f"{host}{url}",
            json={"uri": uri, "job_id": job_id, "old_model_name": old_model_name, "model_name": model_name},
        )

    @classmethod
    async def get_all_model(cls, host) -> (bool, list[str]):
        """Get a list of all models"""
        url = "/v2.1/sft/model"
        return await cls._base_request("get", f"{host}{url}")

    @classmethod
    async def get_gpu_info(cls, host) -> (bool, str):
        """DapatkanGPUMessage"""
        url = "/v2.1/sft/gpu"
        return await cls._base_request("get", f"{host}{url}")

    @classmethod
    async def get_capabilities(cls, host: str) -> (bool, dict):
        return await cls._base_request("get", f"{host}/v2.1/sft/capabilities", include_http_status=True)

    @classmethod
    async def preflight(cls, host: str, params: dict) -> (bool, dict):
        return await cls._base_request("post", f"{host}/v2.1/sft/preflight", json=params)

    @classmethod
    async def validate_inference(cls, host: str, job_id: str, params: dict) -> (bool, dict):
        return await cls._base_request(
            "post", f"{host}/v2.1/sft/job/{job_id}/infer", json=params, timeout=ClientTimeout(total=600)
        )

    @classmethod
    async def probe_url(cls, host: str, url: str) -> (bool, dict):
        """Ask FT whether it can download a platform storage link; FT builds without the probe answer 404."""
        return await cls._base_request(
            "post",
            f"{host}/v2.1/sft/probe",
            json={"url": url},
            include_http_status=True,
            timeout=ClientTimeout(total=30),
        )

    @classmethod
    async def push_file(cls, host: str, sha256: str, chunks) -> (bool, dict):
        """Stream bytes to FT under their digest, for FT hosts that cannot reach object storage."""
        return await cls._base_request(
            "put", f"{host}/v2.1/sft/files/{sha256}", data=chunks, timeout=ClientTimeout(total=1800)
        )

    @classmethod
    async def check_source(cls, host: str, source: dict, probe: str) -> (bool, dict):
        """Ask FT to log in to the dataset source and read one planned file before the job is created."""
        return await cls._base_request(
            "post",
            f"{host}/v2.1/sft/source/check",
            json={"source": source, "probe": probe},
            include_http_status=True,
            timeout=ClientTimeout(total=60),
        )
