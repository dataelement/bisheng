"""Owning-tenant validation for finetuning server management."""

from fastapi import HTTPException

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.database.models.tenant import ROOT_TENANT_ID
from bisheng.finetune.domain.models.server import Server, ServerCreate, ServerDao


class ServerService:
    @staticmethod
    async def _writable_tenant(login_user: UserPayload) -> int:
        from bisheng.permission.application import is_tenant_admin
        from bisheng.utils.http_middleware import _check_is_global_super

        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            raise HTTPException(status_code=403, detail="tenant scope required")
        is_super = await _check_is_global_super(login_user.user_id)
        if is_super:
            return tenant_id
        if tenant_id == ROOT_TENANT_ID or not await is_tenant_admin(login_user.user_id, tenant_id):
            raise HTTPException(status_code=403, detail="server management forbidden")
        return tenant_id

    @classmethod
    async def add_server(cls, server: ServerCreate, login_user: UserPayload) -> Server:
        tenant_id = await cls._writable_tenant(login_user)
        row = Server(**server.model_dump(), tenant_id=tenant_id)
        return await ServerDao.insert(row, tenant_id=tenant_id)

    @classmethod
    async def delete_server(cls, server_id: int, login_user: UserPayload) -> None:
        tenant_id = await cls._writable_tenant(login_user)
        row = await ServerDao.find_server(server_id)
        if row is None or row.id != server_id or row.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="server not found")
        if not await ServerDao.delete(server_id, tenant_id=tenant_id):
            raise HTTPException(status_code=404, detail="server not found")
