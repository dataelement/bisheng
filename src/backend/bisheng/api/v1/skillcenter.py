from fastapi import APIRouter, Depends, Query

from bisheng.app_template.domain.schemas.template import TemplateCreate, TemplateType, TemplateUpdate
from bisheng.app_template.domain.services.template_service import TemplateService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200

router = APIRouter(prefix="/skill", tags=["Skills"], dependencies=[Depends(UserPayload.get_login_user)])


@router.post("/template/create")
async def create_template(*, template: TemplateCreate, user: UserPayload = Depends(UserPayload.get_login_user)):
    return resp_200(await TemplateService.create(user, template))


@router.get("/template")
async def read_template(
    page_size: int | None = Query(default=None, gt=0),
    page_name: int | None = Query(default=None, gt=0),
    flow_type: TemplateType | None = None,
    id: int | None = None,
    name: str | None = None,
):
    return resp_200(
        await TemplateService.read(
            template_id=id, flow_type=flow_type, name=name, page_size=page_size, page_name=page_name
        )
    )


@router.post("/template/{id}")
async def update_template(
    *, id: int, template: TemplateUpdate, user: UserPayload = Depends(UserPayload.get_login_user)
):
    return resp_200(await TemplateService.update(user, id, template))


@router.delete("/template/{id}", status_code=200)
async def delete_template(*, id: int, user: UserPayload = Depends(UserPayload.get_login_user)):
    await TemplateService.delete(user, id)
    return resp_200()
