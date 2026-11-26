"""Register the current tenant's WeKnora connection. The key is sealed and never returned."""

from sqlalchemy import select

from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.common.errcode.knowledge_space import ProviderInstanceInvalidError
from bisheng.core.config.settings import encrypt_token
from bisheng.core.config.weknora import WeKnoraSettings
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderInstance as Instance
from bisheng.knowledge.domain.schemas.provider_instance import ProviderInstanceView
from bisheng.permission.application.identity import is_current_tenant_administrator


def normalize_connection(endpoint: str, scope: str) -> tuple[str, str]:
    if not isinstance(scope, str) or not scope.isdigit():
        raise ProviderInstanceInvalidError()
    try:
        base = WeKnoraSettings.normalize_endpoint(endpoint)
    except ValueError:
        raise ProviderInstanceInvalidError() from None
    return base, scope


def seal_api_key(secret: str) -> str:
    if not secret or not secret.isascii() or not secret.isprintable() or any(c.isspace() for c in secret):
        raise ProviderInstanceInvalidError()
    ref = "fernet:" + encrypt_token(secret).decode()
    if len(ref) > 256:
        raise ProviderInstanceInvalidError()
    return ref


def _optional_secret(value) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProviderInstanceInvalidError()
    secret = value.strip()
    return secret or None


def _view(row: Instance) -> ProviderInstanceView:
    return ProviderInstanceView(
        id=row.id,
        endpoint=row.endpoint,
        remote_scope_id=row.remote_scope_id,
        state=row.state,
        capability_revision=row.capability_revision,
        has_api_key=bool(row.credential_ref),
        has_upload_signed_token_secret=bool(row.upload_credential_ref),
    )


async def _tenant(identity) -> int:
    tenant_id = get_current_tenant_id()
    if not tenant_id or is_tenant_filter_bypassed() or not await is_current_tenant_administrator(identity):
        raise UnAuthorizedError()
    return tenant_id


def _activate(row: Instance) -> None:
    row.state = "ready"
    if row.capability_revision < 1:
        row.capability_revision = 1


async def list_instances(identity) -> list[ProviderInstanceView]:
    tenant_id = await _tenant(identity)
    async with get_async_db_session() as session:
        rows = (
            await session.execute(
                select(Instance)
                .where(Instance.tenant_id == tenant_id, Instance.provider_key == "weknora")
                .order_by(Instance.id)
            )
        ).scalars()
        return [_view(row) for row in rows]


async def create_instance(identity, body) -> ProviderInstanceView:
    tenant_id = await _tenant(identity)
    endpoint, scope = normalize_connection(body.endpoint, body.remote_scope_id)
    upload_secret = _optional_secret(body.upload_signed_token_secret)
    row = Instance(
        tenant_id=tenant_id,
        provider_key="weknora",
        endpoint=endpoint,
        credential_ref=seal_api_key(body.api_key),
        upload_credential_ref=seal_api_key(upload_secret) if upload_secret else None,
        remote_scope_id=scope,
    )
    _activate(row)
    async with get_async_db_session() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return _view(row)


async def update_instance(identity, instance_id: int, body) -> ProviderInstanceView:
    tenant_id = await _tenant(identity)
    endpoint, scope = normalize_connection(body.endpoint, body.remote_scope_id)
    secret = _optional_secret(body.api_key)
    upload_secret = _optional_secret(body.upload_signed_token_secret)
    async with get_async_db_session() as session:
        row = (
            await session.execute(
                select(Instance).where(
                    Instance.tenant_id == tenant_id,
                    Instance.id == instance_id,
                    Instance.provider_key == "weknora",
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError()
        row.endpoint = endpoint
        row.remote_scope_id = scope
        if secret:
            row.credential_ref = seal_api_key(secret)
        if upload_secret:
            row.upload_credential_ref = seal_api_key(upload_secret)
        row.revision += 1
        _activate(row)
        await session.commit()
        await session.refresh(row)
        return _view(row)
