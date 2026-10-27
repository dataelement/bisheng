"""Personal skill center API.

Login is enough. These paths are registered before ``/{name}`` so ``center``,
``candidates`` and ``personal`` are not read as skill identifiers. The handler
delegates to ``PersonalSkillService`` and does not touch object storage.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.linsight.domain.schemas.skill_schema import SkillStatusUpdate
from bisheng.linsight.domain.services.personal_skill_service import PersonalSkillDetail, PersonalSkillService

router = APIRouter(prefix="/skill", tags=["LinsightSkill"])


def _service() -> PersonalSkillService:
    return PersonalSkillService()


def _updated_at(skill) -> str | None:
    stamp = skill.update_time or skill.create_time
    if stamp is None:
        return None
    return stamp.isoformat() if hasattr(stamp, "isoformat") else str(stamp)


def _card(service: PersonalSkillService, skill) -> dict:
    return {
        "id": skill.id,
        "name": skill.name,
        "display_name": skill.display_name,
        "description": skill.description,
        "source": skill.source,
        "enabled": bool(skill.enabled),
        "content_hash": skill.content_hash,
        "bundle_missing": service.is_bundle_missing(skill),
        "update_time": _updated_at(skill),
    }


def _detail(service: PersonalSkillService, detail: PersonalSkillDetail) -> dict:
    card = _card(service, detail.skill)
    card.update(
        preview=detail.preview,
        source_text=detail.source_text,
        files=detail.files,
        bundle_missing=detail.bundle_missing,
    )
    return card


@router.get("/center", summary="Skill center groups")
async def skill_center(
    tab: str = Query(default="personal"),
    keyword: str | None = Query(default=None),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> UnifiedResponseModel:
    service = _service()
    center = await service.list_center(login_user.user_id, tab=tab, keyword=keyword)
    return resp_200(
        {
            "personal": [_card(service, row) for row in center.personal],
            "enterprise": [_card(service, row) for row in center.enterprise],
            "personal_count": center.personal_count,
            "enterprise_count": center.enterprise_count,
        }
    )


@router.get("/candidates", summary="Skills a new task may load")
async def skill_candidates(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> UnifiedResponseModel:
    service = _service()
    rows = await service.list_candidates(login_user.user_id)
    return resp_200([_card(service, row) for row in rows])


@router.get("/personal/usage", summary="Personal skill quota")
async def personal_skill_usage(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> UnifiedResponseModel:
    usage = await _service().usage(login_user.user_id)
    return resp_200(
        {
            "count": usage.count,
            "used_bytes": usage.used_bytes,
            "count_limit": usage.count_limit,
            "bytes_limit": usage.bytes_limit,
        }
    )


@router.get("/personal/import/{import_id}", summary="Personal skill saved for this import")
async def personal_skill_by_import(
    import_id: str,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> UnifiedResponseModel:
    service = _service()
    skill = await service.find_by_import(login_user.user_id, import_id)
    return resp_200(_card(service, skill))


@router.post("/personal/check", summary="Validate a personal skill upload without saving")
async def check_personal_skill(
    file: UploadFile = File(...),
    skill_id: int | None = Form(default=None),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> UnifiedResponseModel:
    preview = await _service().inspect_upload(
        user_id=login_user.user_id,
        filename=file.filename or "",
        data=await file.read(),
        content_type=file.content_type,
        skill_id=skill_id,
    )
    return resp_200(
        {
            "name": preview.name,
            "display_name": preview.display_name,
            "description": preview.description,
            "size": preview.size,
            "files": [{"path": path} for path in preview.files],
        }
    )


@router.post("/personal", summary="Create a personal skill")
async def create_personal_skill(
    file: UploadFile = File(...),
    import_id: str = Form(...),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> UnifiedResponseModel:
    service = _service()
    data = await file.read()
    skill = await service.create(
        user_id=login_user.user_id,
        filename=file.filename or "",
        data=data,
        import_id=import_id,
        content_type=file.content_type,
    )
    return resp_200(_card(service, skill))


@router.get("/personal/{skill_id}", summary="Personal or enterprise skill detail")
async def personal_skill_detail(
    skill_id: int,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> UnifiedResponseModel:
    service = _service()
    return resp_200(_detail(service, await service.get(user_id=login_user.user_id, skill_id=skill_id)))


@router.get("/personal/{skill_id}/file", summary="Read one file from a skill bundle")
async def personal_skill_file(
    skill_id: int,
    path: str = Query(...),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> UnifiedResponseModel:
    opened = await _service().read_file(user_id=login_user.user_id, skill_id=skill_id, path=path)
    return resp_200({"path": opened.path, "content": opened.content})


@router.post("/personal/{skill_id}/overwrite", summary="Replace a personal skill bundle")
async def overwrite_personal_skill(
    skill_id: int,
    file: UploadFile = File(...),
    import_id: str = Form(...),
    expected_content_hash: str = Form(...),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> UnifiedResponseModel:
    service = _service()
    data = await file.read()
    skill = await service.overwrite(
        user_id=login_user.user_id,
        skill_id=skill_id,
        filename=file.filename or "",
        data=data,
        expected_content_hash=expected_content_hash,
        import_id=import_id,
        content_type=file.content_type,
    )
    return resp_200(_card(service, skill))


@router.patch("/personal/{skill_id}/status", summary="Enable or disable a personal skill")
async def personal_skill_status(
    skill_id: int,
    payload: SkillStatusUpdate,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> UnifiedResponseModel:
    service = _service()
    skill = await service.set_enabled(user_id=login_user.user_id, skill_id=skill_id, enabled=payload.enabled)
    return resp_200(_card(service, skill))


@router.delete("/personal/{skill_id}", summary="Delete a personal skill")
async def delete_personal_skill(
    skill_id: int,
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> UnifiedResponseModel:
    await _service().delete(user_id=login_user.user_id, skill_id=skill_id)
    return resp_200({})
