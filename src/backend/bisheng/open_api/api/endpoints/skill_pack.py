"""Anonymous distribution for allowlisted static Open API skills."""

from fastapi import APIRouter, Request
from fastapi.responses import Response

from bisheng.open_api.domain.services.skill_pack_service import SkillPackService

router = APIRouter(prefix="/open-api/skill-packs", tags=["OpenAPI"])


@router.get("/{pack_name}", name="download_open_api_skill_pack")
async def download_skill_pack(pack_name: str, request: Request):
    payload = SkillPackService.build(pack_name, base_url=str(request.base_url).rstrip("/"))
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{pack_name}.zip"'},
    )

