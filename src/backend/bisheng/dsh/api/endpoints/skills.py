"""Personal uploads and per-account skill switches, shared by Chat and Work."""

import asyncio
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Path, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, StrictBool

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.linsight.domain.services.skill_service import SkillService
from bisheng.linsight.domain.services.skill_store import (
    pack_bundle_zip,
)
from bisheng.linsight.domain.services.user_skills import UserSkillsService

router = APIRouter(prefix="/dsh/skills")


@router.get("")
async def list_skills(user=Depends(UserPayload.get_login_user)):
    rows = []
    for skill, enabled in await UserSkillsService(user.user_id).records(False):
        entry = {
            "id": skill.id,
            "name": skill.name,
            "display_name": skill.display_name or skill.name,
            "description": skill.description,
            "enabled": enabled,
            "content_hash": skill.content_hash,
            "source": "personal" if skill.source == "personal" else "platform",
            "builtin_key": skill.name if skill.source == "builtin" else None,
            "updated_at": skill.update_time or skill.create_time,
        }
        if skill.source == "personal":
            detail = await SkillService(personal_owner=user.user_id).get_detail(user.tenant_id, skill.name)
            entry.update(instructions=detail.preview, files=[f.path for f in detail.files])
        rows.append(entry)
    return resp_200(rows)


class Availability(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool


@router.put("/{skill_id}/availability")
async def availability(body: Availability, skill_id: int = Path(gt=0), user=Depends(UserPayload.get_login_user)):
    await UserSkillsService(user.user_id).toggle(skill_id, body.enabled)
    from bisheng.dsh.domain.repositories.work_publication import WorkPublicationRepository

    await WorkPublicationRepository().audit(user, "availability", "skill", skill_id, {"enabled": body.enabled})
    return resp_200({"id": skill_id, "enabled": body.enabled})


@router.post("/personal")
async def upload(
    file: UploadFile = File(...),
    client_id: str = Form(default_factory=lambda: str(uuid4()), max_length=100),
    user=Depends(UserPayload.get_login_user),
):
    return await UserSkillsService(user.user_id).save_personal_upload(user, file, client_id)


@router.post("/personal/{skill_id}")
async def update_personal(skill_id: int, file: UploadFile = File(...), user=Depends(UserPayload.get_login_user)):
    return await UserSkillsService(user.user_id).save_personal_upload(user, file, "", skill_id)


@router.get("/personal/{skill_id}/bundle")
async def download(skill_id: int, user=Depends(UserPayload.get_login_user)):
    row = await UserSkillsService(user.user_id).personal(skill_id)
    files = await asyncio.to_thread(SkillService()._load_existing_bundle, user.tenant_id, row.name, row.content_hash)
    return Response(pack_bundle_zip(files), media_type="application/zip")


@router.delete("/personal/{skill_id}")
async def delete_personal(skill_id: int, user=Depends(UserPayload.get_login_user)):
    row = await UserSkillsService(user.user_id).personal(skill_id)
    await SkillService(personal_owner=user.user_id).delete(user.tenant_id, row.name)
    return resp_200()
