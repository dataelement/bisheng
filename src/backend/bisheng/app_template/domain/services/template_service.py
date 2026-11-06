"""Tenant-public templates maintained only by the active tenant's admins."""

from copy import deepcopy

from bisheng.app_template.domain.repositories.template_repository import TemplateRepository
from bisheng.app_template.domain.schemas.template import TemplateCreate, TemplateUpdate
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.common.errcode.tenant import NoTenantContextError
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, get_current_tenant_id
from bisheng.permission.application.business_authorization import require_business_action
from bisheng.permission.application.identity import resolve_permission_actor

ASSISTANT_FIELDS = ("prompt", "desc", "guide_word", "guide_question", "temperature", "max_token", "knowledge_auth")


class TemplateService:
    @staticmethod
    def current_tenant() -> int:
        tid = get_current_tenant_id()
        if tid is None and not settings.multi_tenant.enabled:
            return DEFAULT_TENANT_ID
        if type(tid) is not int or tid <= 0:
            raise NoTenantContextError()
        return tid

    @classmethod
    async def require_admin(cls, user):
        tid = cls.current_tenant()
        actor = await resolve_permission_actor(user)
        if not actor.super_admin and tid not in actor.tenant_admin_tenant_ids:
            raise PermissionDeniedError()

    @classmethod
    async def read(cls, *, template_id=None, flow_type=None, **filters):
        cls.current_tenant()
        if template_id is not None:
            row = await TemplateRepository.get(template_id)
            if row is None or (flow_type is not None and row.flow_type != flow_type):
                raise NotFoundError()
            return [row]
        rows = await TemplateRepository.list(flow_type=flow_type, **filters)
        return [row.model_dump(include={"id", "name", "description", "update_time", "order_num"}) for row in rows]

    @classmethod
    async def create(cls, user, request: TemplateCreate):
        await cls.require_admin(user)
        source = await TemplateRepository.source(request.flow_id, request.flow_type)
        if source is None or source["tenant_id"] != cls.current_tenant():
            raise NotFoundError()
        await require_business_action(
            user,
            resource_type="assistant" if request.flow_type == 5 else "workflow",
            resource_id=request.flow_id,
            action="visible",
        )
        data = {key: source[key] for key in ASSISTANT_FIELDS} if request.flow_type == 5 else source["data"]
        return await TemplateRepository.create({**request.model_dump(), "data": deepcopy(data)})

    @classmethod
    async def update(cls, user, template_id: int, request: TemplateUpdate):
        await cls.require_admin(user)
        values = request.model_dump(exclude_unset=True)
        values = {key: value for key, value in values.items() if value is not None or key == "description"}
        return await TemplateRepository.update(template_id, values)

    @classmethod
    async def delete(cls, user, template_id: int):
        await cls.require_admin(user)
        await TemplateRepository.delete(template_id)

    @classmethod
    async def workflow_data(cls):
        cls.current_tenant()
        return await TemplateRepository.workflow_data()
