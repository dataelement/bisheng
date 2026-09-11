"""Tenant custom skill management API (F035 Track D, contract C3 + 2026-06-12 increment).

Management endpoints require tenant admin; ``/skill/selectable`` serves the
end-user picker with plain login auth. built-in skills are not addressable
here — unknown names answer 11053 without leaking existence (design §7.5).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.linsight import SkillFileTooLargeError, SkillValidationError
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, get_current_tenant_id
from bisheng.linsight.domain.schemas.skill_schema import (
    SkillCreateForm,
    SkillGitHubImportRequest,
    SkillStatusUpdate,
)
from bisheng.linsight.domain.services.skill_service import SkillService
from bisheng.linsight.domain.services.skill_store import MAX_BUNDLE_SIZE, slugify_pinyin

router = APIRouter(prefix="/skill", tags=["LinsightSkill"])


def _current_tenant_id() -> int:
    return get_current_tenant_id() or DEFAULT_TENANT_ID


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read()
    if len(data) > MAX_BUNDLE_SIZE:
        raise SkillFileTooLargeError()
    return data


def _require_form(
    display_name: str | None, name: str | None, description: str | None, content: str | None
) -> SkillCreateForm:
    missing = [
        label
        for label, value in (
            ("display_name", display_name),
            ("name", name),
            ("description", description),
            ("content", content),
        )
        if not value
    ]
    if missing:
        raise SkillValidationError(msg=f"missing required fields: {', '.join(missing)}")
    return SkillCreateForm(display_name=display_name, name=name, description=description, content=content)


@router.get("", summary="Tenant custom skill list (management)")
async def list_skills(
    keyword: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
) -> UnifiedResponseModel:
    page_data = await SkillService().get_page(keyword=keyword, enabled=enabled, page=page, page_size=page_size)
    return resp_200(page_data)


@router.get("/selectable", summary="Enabled skills for the end-user picker")
async def selectable_skills(
    login_user: UserPayload = Depends(UserPayload.get_login_user),
) -> UnifiedResponseModel:
    return resp_200(await SkillService().get_selectable())


@router.get("/slugify", summary="Suggest a skill ID from a display name (pypinyin)")
async def slugify_skill_name(
    text: str = Query(..., max_length=255),
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
) -> UnifiedResponseModel:
    # Single source of truth with the SOP migration script (skill_store.slugify_pinyin).
    return resp_200({"slug": slugify_pinyin(text)})


@router.get("/{name}", summary="Skill detail (frontmatter + body + bundle file tree)")
async def get_skill(
    name: str,
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
) -> UnifiedResponseModel:
    return resp_200(await SkillService().get_detail(_current_tenant_id(), name))


@router.get("/{name}/file", summary="Read a bundle asset (read-only)")
async def get_skill_file(
    name: str,
    path: str = Query(..., description="Bundle-relative file path"),
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
) -> UnifiedResponseModel:
    return resp_200(await SkillService().read_bundle_file(_current_tenant_id(), name, path))


@router.post("", summary="Create skill: multipart (.md/.zip/.skill) or form fields")
async def create_skill(
    file: UploadFile | None = File(default=None),
    display_name: str | None = Form(default=None),
    name: str | None = Form(default=None),
    description: str | None = Form(default=None),
    content: str | None = Form(default=None),
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
) -> UnifiedResponseModel:
    service = SkillService()
    tenant_id = _current_tenant_id()
    if file is not None:
        data = await _read_upload(file)
        detail = await service.create_from_upload(tenant_id, login_user.user_id, file.filename or "", data)
    else:
        form = _require_form(display_name, name, description, content)
        detail = await service.create_from_form(tenant_id, login_user.user_id, form)
    return resp_200(detail)


@router.post("/import-github", summary="Import a skill from a public GitHub directory URL")
async def import_skill_from_github(
    payload: SkillGitHubImportRequest,
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
) -> UnifiedResponseModel:
    detail = await SkillService().create_from_github(_current_tenant_id(), login_user.user_id, payload.url)
    return resp_200(detail)


@router.put("/{name}", summary="Edit skill: form (SKILL.md only) or multipart (whole-bundle replace)")
async def update_skill(
    name: str,
    file: UploadFile | None = File(default=None),
    display_name: str | None = Form(default=None),
    description: str | None = Form(default=None),
    content: str | None = Form(default=None),
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
) -> UnifiedResponseModel:
    service = SkillService()
    tenant_id = _current_tenant_id()
    if file is not None:
        data = await _read_upload(file)
        detail = await service.update_from_upload(tenant_id, name, file.filename or "", data)
    else:
        form = _require_form(display_name, name, description, content)
        detail = await service.update_from_form(tenant_id, name, form)
    return resp_200(detail)


@router.patch("/{name}/status", summary="Enable / disable skill")
async def set_skill_status(
    name: str,
    payload: SkillStatusUpdate,
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
) -> UnifiedResponseModel:
    await SkillService().set_status(name, payload.enabled)
    return resp_200({"ok": True})


@router.delete("/{name}", summary="Delete skill (whole bundle dir)")
async def delete_skill(
    name: str,
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
) -> UnifiedResponseModel:
    await SkillService().delete(_current_tenant_id(), name)
    return resp_200({"ok": True})
