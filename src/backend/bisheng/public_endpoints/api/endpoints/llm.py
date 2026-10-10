"""Speech capabilities for published workflow and assistant pages."""

from uuid import UUID

from fastapi import APIRouter, Body, File, Query, UploadFile

from bisheng.common.schemas.api import resp_200
from bisheng.llm.domain import LLMService
from bisheng.public_endpoints.domain.services.guest_policy import public_application_execution

router = APIRouter(prefix="/llm", tags=["PublicAPI", "Speech"])


@router.get("/workbench")
async def get_workbench_voice_config(flow_id: UUID = Query(...)):
    """Expose only the model references needed to enable speech controls."""
    async with public_application_execution(flow_id.hex):
        config = await LLMService.get_workbench_llm()
        return resp_200(
            data={
                "asr_model": {"id": config.asr_model.id if config.asr_model else None},
                "tts_model": {"id": config.tts_model.id if config.tts_model else None},
            }
        )


@router.post("/workbench/asr")
async def invoke_workbench_asr(
    flow_id: UUID = Query(...),
    file: UploadFile = File(...),
):
    async with public_application_execution(flow_id.hex) as execution:
        text = await LLMService.invoke_workbench_asr(execution.operator, file)
        return resp_200(data=text)


@router.post("/workbench/tts")
async def invoke_workbench_tts(
    flow_id: UUID = Query(...),
    text: str = Body(..., embed=True),
):
    async with public_application_execution(flow_id.hex) as execution:
        audio_url = await LLMService.invoke_workbench_tts(execution.operator, text)
        return resp_200(data=audio_url)
