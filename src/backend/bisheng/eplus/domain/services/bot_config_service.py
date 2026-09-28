"""Manage assistant-bound E+ robot configuration and connection targets."""

from __future__ import annotations

import logging
from typing import Protocol

from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.eplus.domain.models.eplus import EPlusBotConfig, EPlusConnectionStatus
from bisheng.eplus.domain.repositories.eplus_repository import EPlusConfigRepository
from bisheng.eplus.domain.schemas.config import (
    AssistantSnapshot,
    EPlusBotConfigUpsert,
    EPlusBotConfigView,
    EPlusConnectionTarget,
)

logger = logging.getLogger(__name__)


class PermissionChecker(Protocol):
    async def require_assistant_edit(
        self,
        *,
        tenant_id: int,
        assistant_id: str,
        operator_id: int,
        action: str,
    ) -> None: ...


class AssistantReader(Protocol):
    async def get_assistant(self, *, tenant_id: int, assistant_id: str) -> AssistantSnapshot | None: ...


class SpaceReader(Protocol):
    async def require_valid_spaces(self, *, tenant_id: int, space_ids: tuple[int, ...]) -> None: ...


class CredentialStore(Protocol):
    def encrypt(self, secret: str) -> str: ...

    def decrypt(self, ciphertext: str) -> str: ...


class CertificateStore(Protocol):
    async def put_ca(self, pem: bytes) -> tuple[str, str]: ...


class ConfigNotifier(Protocol):
    async def config_changed(self, event: dict[str, int]) -> None: ...


class EPlusBotConfigService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        permission_checker: PermissionChecker,
        assistant_reader: AssistantReader,
        space_reader: SpaceReader,
        credential_store: CredentialStore,
        certificate_store: CertificateStore,
        notifier: ConfigNotifier,
    ) -> None:
        self._session = session
        self._repository = EPlusConfigRepository(session)
        self._permission_checker = permission_checker
        self._assistant_reader = assistant_reader
        self._space_reader = space_reader
        self._credential_store = credential_store
        self._certificate_store = certificate_store
        self._notifier = notifier

    async def save_config(
        self,
        *,
        tenant_id: int,
        assistant_id: str,
        operator_id: int,
        request: EPlusBotConfigUpsert,
    ) -> EPlusBotConfigView:
        await self._permission_checker.require_assistant_edit(
            tenant_id=tenant_id,
            assistant_id=assistant_id,
            operator_id=operator_id,
            action="edit",
        )
        assistant = await self._require_assistant(tenant_id=tenant_id, assistant_id=assistant_id)
        space_ids = tuple(request.space_ids)
        await self._space_reader.require_valid_spaces(tenant_id=tenant_id, space_ids=space_ids)

        row = await self._repository.get_by_assistant_id(tenant_id=tenant_id, assistant_id=assistant.assistant_id)
        bot_owner = await self._repository.get_by_bot_id(tenant_id=tenant_id, bot_id=request.bot_id)
        if bot_owner is not None and (row is None or bot_owner.id != row.id):
            raise ValueError("E+ bot is already bound to another assistant")

        previous_space_ids: tuple[int, ...] = ()
        if row is None:
            if request.secret is None:
                raise ValueError("secret is required for a new E+ bot configuration")
            row = EPlusBotConfig(
                tenant_id=tenant_id,
                assistant_id=assistant.assistant_id,
                bot_id=request.bot_id,
                connection_url=request.connection_url,
                secret_ciphertext=self._credential_store.encrypt(request.secret),
                media_host_allowlist=list(request.media_hosts),
                enabled=request.enabled,
                is_deleted=False,
                connection_status=EPlusConnectionStatus.DISABLED.value,
                credential_version=1,
                scope_version=1,
                created_by=operator_id,
                updated_by=operator_id,
            )
            if request.ca_pem is not None:
                row.ca_object_key, row.ca_sha256 = await self._certificate_store.put_ca(request.ca_pem)
            await self._repository.save(tenant_id=tenant_id, row=row)
            scope_changed = True
        else:
            previous_space_ids = tuple(await self._repository.list_space_ids(tenant_id=tenant_id, bot_config_id=row.id))
            credential_changed = row.connection_url != request.connection_url or row.bot_id != request.bot_id
            row.bot_id = request.bot_id
            row.connection_url = request.connection_url
            if request.secret is not None:
                row.secret_ciphertext = self._credential_store.encrypt(request.secret)
                credential_changed = True
            if request.ca_pem is not None:
                object_key, sha256 = await self._certificate_store.put_ca(request.ca_pem)
                if sha256 != row.ca_sha256:
                    credential_changed = True
                row.ca_object_key = object_key
                row.ca_sha256 = sha256
            elif request.remove_ca and row.ca_object_key is not None:
                row.ca_object_key = None
                row.ca_sha256 = None
                credential_changed = True
            if credential_changed:
                row.credential_version += 1
            scope_changed = previous_space_ids != space_ids
            if scope_changed:
                row.scope_version += 1
            row.media_host_allowlist = list(request.media_hosts)
            row.enabled = request.enabled
            row.is_deleted = False
            row.updated_by = operator_id
            await self._repository.save(tenant_id=tenant_id, row=row)

        if scope_changed:
            await self._repository.replace_space_ids(
                tenant_id=tenant_id,
                bot_config_id=row.id,
                space_ids=space_ids,
                bound_by=operator_id,
            )
        await self._session.commit()
        await self._session.refresh(row)
        await self._notify(row)
        return self._view(row, space_ids)

    async def get_config(
        self,
        *,
        tenant_id: int,
        assistant_id: str,
        operator_id: int,
    ) -> EPlusBotConfigView | None:
        await self._permission_checker.require_assistant_edit(
            tenant_id=tenant_id,
            assistant_id=assistant_id,
            operator_id=operator_id,
            action="edit",
        )
        row = await self._repository.get_by_assistant_id(tenant_id=tenant_id, assistant_id=assistant_id)
        if row is None:
            return None
        space_ids = tuple(await self._repository.list_space_ids(tenant_id=tenant_id, bot_config_id=row.id))
        return self._view(row, space_ids)

    async def disable_config(self, *, tenant_id: int, assistant_id: str, operator_id: int) -> bool:
        await self._permission_checker.require_assistant_edit(
            tenant_id=tenant_id,
            assistant_id=assistant_id,
            operator_id=operator_id,
            action="edit",
        )
        row = await self._repository.get_by_assistant_id(tenant_id=tenant_id, assistant_id=assistant_id)
        if row is None:
            return False
        row.enabled = False
        row.is_deleted = True
        row.connection_status = EPlusConnectionStatus.DISABLED.value
        row.updated_by = operator_id
        await self._repository.save(tenant_id=tenant_id, row=row)
        await self._session.commit()
        await self._notify(row)
        return True

    async def resolve_connection_target(
        self,
        *,
        tenant_id: int,
        bot_config_id: int,
    ) -> EPlusConnectionTarget | None:
        row = await self._repository.get_by_id(tenant_id=tenant_id, bot_config_id=bot_config_id)
        if row is None or row.is_deleted or not row.enabled or not row.secret_ciphertext:
            return None
        assistant = await self._assistant_reader.get_assistant(
            tenant_id=tenant_id,
            assistant_id=row.assistant_id,
        )
        if assistant is None or assistant.is_deleted or not assistant.is_online:
            return None
        return EPlusConnectionTarget(
            tenant_id=tenant_id,
            bot_config_id=row.id,
            assistant_id=row.assistant_id,
            bot_id=row.bot_id,
            connection_url=row.connection_url,
            secret=self._credential_store.decrypt(row.secret_ciphertext),
            ca_object_key=row.ca_object_key,
            media_hosts=tuple(row.media_host_allowlist),
            credential_version=row.credential_version,
            scope_version=row.scope_version,
        )

    async def _require_assistant(self, *, tenant_id: int, assistant_id: str) -> AssistantSnapshot:
        assistant = await self._assistant_reader.get_assistant(tenant_id=tenant_id, assistant_id=assistant_id)
        if assistant is None or assistant.is_deleted or assistant.tenant_id != tenant_id:
            raise ValueError("assistant does not exist in the current tenant")
        return assistant

    async def _notify(self, row: EPlusBotConfig) -> None:
        try:
            await self._notifier.config_changed(
                {
                    "tenant_id": int(row.tenant_id),
                    "bot_config_id": int(row.id),
                    "credential_version": int(row.credential_version),
                    "scope_version": int(row.scope_version),
                }
            )
        except Exception as exc:
            logger.warning("E+ config notification failed for config_id=%s: %s", row.id, type(exc).__name__)

    @staticmethod
    def _view(row: EPlusBotConfig, space_ids: tuple[int, ...]) -> EPlusBotConfigView:
        return EPlusBotConfigView(
            id=int(row.id),
            assistant_id=row.assistant_id,
            bot_id=row.bot_id,
            connection_url=row.connection_url,
            credential_version=int(row.credential_version),
            scope_version=int(row.scope_version),
            enabled=bool(row.enabled),
            is_deleted=bool(row.is_deleted),
            connection_status=row.connection_status,
            secret_configured=bool(row.secret_ciphertext),
            ca_configured=bool(row.ca_object_key),
            ca_sha256=row.ca_sha256,
            media_hosts=tuple(row.media_host_allowlist),
            space_ids=space_ids,
            insecure_transport=row.connection_url.startswith("ws://"),
        )
