from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager

from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.services.approval_registry import ensure_system_file_change_scenario
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum
from bisheng.knowledge.domain.models.knowledge_space_file_change_policy import (
    KnowledgeSpaceFileChangePolicy,
    KnowledgeSpaceFileChangePolicyScope,
    KnowledgeSpaceFileChangeSetting,
)
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_repository import (
    KnowledgeSpaceFileChangeRepository,
    KnowledgeSpaceFileChangeSettingRow,
)
from bisheng.knowledge.domain.schemas.knowledge_space_file_change_schema import (
    KnowledgeSpaceFileChangeConfigurationResp,
    KnowledgeSpaceFileChangePolicyUpdateReq,
    KnowledgeSpaceFileChangeSettingBulkItem,
    KnowledgeSpaceFileChangeSettingResp,
    KnowledgeSpaceFileChangeSettingsResp,
)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class KnowledgeSpaceFileChangePolicyService:
    """Resolve F046 policy strictly within the active tenant context."""

    _VALID_SCOPES = {
        KnowledgeSpaceFileChangePolicyScope.ALL_SPACES,
        KnowledgeSpaceFileChangePolicyScope.PER_SPACE,
    }

    def __init__(self, *, session_factory: SessionFactory = get_async_db_session) -> None:
        self.session_factory = session_factory

    @staticmethod
    def _tenant_id() -> int:
        tenant_id = get_current_tenant_id()
        if tenant_id is None:
            raise RuntimeError("tenant context is required for file change policy")
        return int(tenant_id)

    @classmethod
    def _validate_scope(cls, scope: str) -> str:
        normalized = str(scope)
        if normalized not in cls._VALID_SCOPES:
            raise ValueError(f"unsupported file change policy scope: {scope}")
        return normalized

    async def get_policy(
        self,
        *,
        session: AsyncSession | None = None,
        for_update: bool = False,
    ) -> KnowledgeSpaceFileChangePolicy:
        tenant_id = self._tenant_id()
        if session is not None:
            row = await KnowledgeSpaceFileChangeRepository(session).get_policy(
                tenant_id=tenant_id,
                for_update=for_update,
            )
            return row or KnowledgeSpaceFileChangePolicy(tenant_id=tenant_id)

        async with self.session_factory() as owned_session:
            row = await KnowledgeSpaceFileChangeRepository(owned_session).get_policy(
                tenant_id=tenant_id,
                for_update=for_update,
            )
            return row or KnowledgeSpaceFileChangePolicy(tenant_id=tenant_id)

    async def ensure_policy_row(
        self,
        *,
        session: AsyncSession,
        for_update: bool = True,
    ) -> KnowledgeSpaceFileChangePolicy:
        return await KnowledgeSpaceFileChangeRepository(session).ensure_policy_row(
            tenant_id=self._tenant_id(),
            for_update=for_update,
        )

    async def save_policy(
        self,
        *,
        enabled: bool,
        scope: str,
        session: AsyncSession | None = None,
    ) -> KnowledgeSpaceFileChangePolicy:
        tenant_id = self._tenant_id()
        normalized_scope = self._validate_scope(scope)
        if session is not None:
            row = await KnowledgeSpaceFileChangeRepository(session).save_policy(
                tenant_id=tenant_id,
                enabled=enabled,
                scope=normalized_scope,
            )
            await ensure_system_file_change_scenario(
                tenant_id=tenant_id,
                session=session,
            )
            return row

        async with self.session_factory() as owned_session:
            async with owned_session.begin():
                row = await KnowledgeSpaceFileChangeRepository(owned_session).save_policy(
                    tenant_id=tenant_id,
                    enabled=enabled,
                    scope=normalized_scope,
                )
                await ensure_system_file_change_scenario(
                    tenant_id=tenant_id,
                    session=owned_session,
                )
            await owned_session.refresh(row)
            return row

    async def save_space_setting(
        self,
        *,
        space_id: int,
        approval_required: bool,
        session: AsyncSession | None = None,
    ) -> KnowledgeSpaceFileChangeSetting:
        tenant_id = self._tenant_id()
        if session is not None:
            await self._require_space(
                repository=KnowledgeSpaceFileChangeRepository(session),
                tenant_id=tenant_id,
                space_id=space_id,
            )
            return await KnowledgeSpaceFileChangeRepository(session).save_setting(
                tenant_id=tenant_id,
                space_id=space_id,
                approval_required=approval_required,
            )

        async with self.session_factory() as owned_session:
            async with owned_session.begin():
                repository = KnowledgeSpaceFileChangeRepository(owned_session)
                await self._require_space(
                    repository=repository,
                    tenant_id=tenant_id,
                    space_id=space_id,
                )
                row = await repository.save_setting(
                    tenant_id=tenant_id,
                    space_id=space_id,
                    approval_required=approval_required,
                )
            await owned_session.refresh(row)
            return row

    async def save_configuration(
        self,
        *,
        policy: KnowledgeSpaceFileChangePolicyUpdateReq | None,
        settings: Sequence[KnowledgeSpaceFileChangeSettingBulkItem],
    ) -> KnowledgeSpaceFileChangeConfigurationResp:
        """Atomically save the current tenant's policy and changed space settings."""

        tenant_id = self._tenant_id()
        normalized_settings = sorted(settings, key=lambda item: int(item.space_id))
        async with self.session_factory() as session:
            async with session.begin():
                repository = KnowledgeSpaceFileChangeRepository(session)
                space_ids = [int(item.space_id) for item in normalized_settings]
                locked_spaces = await repository.lock_spaces_by_ids(
                    tenant_id=tenant_id,
                    space_ids=space_ids,
                )
                if [int(space.id) for space in locked_spaces] != space_ids:
                    raise LookupError("knowledge space not found")

                for item in normalized_settings:
                    await repository.save_setting(
                        tenant_id=tenant_id,
                        space_id=int(item.space_id),
                        approval_required=item.approval_required,
                    )

                policy_row = await repository.get_policy(
                    tenant_id=tenant_id,
                    for_update=True,
                )
                if policy is not None:
                    if policy_row is None:
                        policy_row = KnowledgeSpaceFileChangePolicy(tenant_id=tenant_id)
                    policy_row.enabled = policy.enabled
                    policy_row.scope = self._validate_scope(policy.scope.value)
                    session.add(policy_row)
                    await session.flush()

                await ensure_system_file_change_scenario(
                    tenant_id=tenant_id,
                    session=session,
                )
                effective_policy = policy_row or KnowledgeSpaceFileChangePolicy(tenant_id=tenant_id)
                setting_rows = []
                for item in normalized_settings:
                    row = await repository.get_space_setting_row(
                        tenant_id=tenant_id,
                        space_id=int(item.space_id),
                    )
                    if row is None:  # pragma: no cover - protected by locked space set
                        raise LookupError("knowledge space not found")
                    setting_rows.append(self._setting_response(row=row, policy=effective_policy))

                return KnowledgeSpaceFileChangeConfigurationResp(
                    policy=effective_policy,
                    settings=setting_rows,
                )

    async def is_approval_required(
        self,
        *,
        space_id: int,
        session: AsyncSession | None = None,
    ) -> bool:
        tenant_id = self._tenant_id()
        if session is not None:
            return await self._is_approval_required(
                repository=KnowledgeSpaceFileChangeRepository(session),
                tenant_id=tenant_id,
                space_id=space_id,
            )

        async with self.session_factory() as owned_session:
            return await self._is_approval_required(
                repository=KnowledgeSpaceFileChangeRepository(owned_session),
                tenant_id=tenant_id,
                space_id=space_id,
            )

    async def list_space_settings(
        self,
        *,
        space_ids: Sequence[int],
        session: AsyncSession | None = None,
    ) -> dict[int, bool]:
        """Return saved values only; absent spaces retain the default True."""
        tenant_id = self._tenant_id()
        if session is not None:
            rows = await KnowledgeSpaceFileChangeRepository(session).get_settings_by_space_ids(
                tenant_id=tenant_id,
                space_ids=space_ids,
            )
        else:
            async with self.session_factory() as owned_session:
                rows = await KnowledgeSpaceFileChangeRepository(owned_session).get_settings_by_space_ids(
                    tenant_id=tenant_id,
                    space_ids=space_ids,
                )
        return {int(row.space_id): bool(row.approval_required) for row in rows}

    async def get_space_settings_page(
        self,
        *,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> KnowledgeSpaceFileChangeSettingsResp:
        tenant_id = self._tenant_id()
        async with self.session_factory() as session:
            repository = KnowledgeSpaceFileChangeRepository(session)
            policy = await repository.get_policy(tenant_id=tenant_id)
            rows, total = await repository.list_space_setting_rows(
                tenant_id=tenant_id,
                keyword=keyword,
                page=page,
                page_size=page_size,
            )
        return KnowledgeSpaceFileChangeSettingsResp(
            data=[self._setting_response(row=row, policy=policy) for row in rows],
            total=total,
        )

    async def update_space_setting(
        self,
        *,
        space_id: int,
        approval_required: bool,
    ) -> KnowledgeSpaceFileChangeSettingResp:
        tenant_id = self._tenant_id()
        async with self.session_factory() as session:
            async with session.begin():
                repository = KnowledgeSpaceFileChangeRepository(session)
                await self._require_space(
                    repository=repository,
                    tenant_id=tenant_id,
                    space_id=space_id,
                )
                await repository.save_setting(
                    tenant_id=tenant_id,
                    space_id=space_id,
                    approval_required=approval_required,
                )
                row = await repository.get_space_setting_row(
                    tenant_id=tenant_id,
                    space_id=space_id,
                )
                policy = await repository.get_policy(tenant_id=tenant_id)
                if row is None:  # pragma: no cover - protected by the locked space lookup above
                    raise LookupError(f"knowledge space not found: {space_id}")
                return self._setting_response(row=row, policy=policy)

    @staticmethod
    def _setting_response(
        *,
        row: KnowledgeSpaceFileChangeSettingRow,
        policy: KnowledgeSpaceFileChangePolicy | None,
    ) -> KnowledgeSpaceFileChangeSettingResp:
        auth_type = row.space.auth_type
        auth_type_value = auth_type.value if isinstance(auth_type, AuthTypeEnum) else str(auth_type)
        approval_required = True if row.setting is None else bool(row.setting.approval_required)
        if auth_type_value == AuthTypeEnum.PRIVATE.value:
            effective_required = False
        elif policy is not None and not bool(policy.enabled):
            effective_required = False
        elif policy is not None and policy.scope == KnowledgeSpaceFileChangePolicyScope.ALL_SPACES:
            effective_required = True
        else:
            effective_required = approval_required
        return KnowledgeSpaceFileChangeSettingResp(
            space_id=int(row.space.id),
            name=row.space.name,
            auth_type=auth_type_value,
            space_kind="department" if row.is_department else "normal",
            approval_required=approval_required,
            effective_required=effective_required,
        )

    async def _is_approval_required(
        self,
        *,
        repository: KnowledgeSpaceFileChangeRepository,
        tenant_id: int,
        space_id: int,
    ) -> bool:
        space = await self._require_space(
            repository=repository,
            tenant_id=tenant_id,
            space_id=space_id,
        )
        if space.auth_type == AuthTypeEnum.PRIVATE:
            return False

        policy = await repository.get_policy(tenant_id=tenant_id)
        if policy is None:
            enabled = True
            scope = KnowledgeSpaceFileChangePolicyScope.PER_SPACE
        else:
            enabled = bool(policy.enabled)
            scope = policy.scope
        if not enabled:
            return False
        if scope == KnowledgeSpaceFileChangePolicyScope.ALL_SPACES:
            return True
        if scope != KnowledgeSpaceFileChangePolicyScope.PER_SPACE:
            raise RuntimeError(f"invalid persisted file change policy scope: {scope}")

        setting = await repository.get_setting(tenant_id=tenant_id, space_id=space_id)
        return True if setting is None else bool(setting.approval_required)

    @staticmethod
    async def _require_space(
        *,
        repository: KnowledgeSpaceFileChangeRepository,
        tenant_id: int,
        space_id: int,
    ):
        space = await repository.get_space(tenant_id=tenant_id, space_id=space_id)
        if space is None:
            raise LookupError(f"knowledge space not found: {space_id}")
        return space
