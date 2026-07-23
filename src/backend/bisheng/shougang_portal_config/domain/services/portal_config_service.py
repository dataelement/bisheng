from __future__ import annotations

from loguru import logger
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from bisheng.common.errcode.tenant import NoTenantContextError
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.shougang_portal_config.domain.repositories.implementations.portal_admin_config_repository_impl import (
    PortalAdminConfigRepositoryImpl,
)
from bisheng.shougang_portal_config.domain.schemas.portal_config_schema import (
    ShougangPortalAdminConfig,
)
from bisheng.shougang_portal_config.domain.services.department_business_domain_service import (
    DepartmentBusinessDomainService,
)

SHOUGANG_PORTAL_CONFIG_KEY = 'shougang_portal_config'


def _enqueue_recommendation_config_post_commit(**kwargs) -> None:
    from bisheng.worker.knowledge.portal_recommendation import (
        enqueue_portal_recommendation_config_post_commit,
    )

    enqueue_portal_recommendation_config_post_commit(**kwargs)


class ShougangPortalConfigService:
    _MAX_SAVE_ATTEMPTS = 3

    @classmethod
    def _resolve_tenant_id(cls, tenant_id: int | None) -> int:
        current_tenant_id = get_current_tenant_id()
        if tenant_id is not None:
            resolved = int(tenant_id)
            if resolved <= 0:
                raise ValueError("tenant_id must be positive")
            if current_tenant_id is not None and resolved != int(current_tenant_id):
                raise ValueError("tenant_id does not match the current tenant context")
            return resolved
        if current_tenant_id is not None:
            return int(current_tenant_id)
        if settings.multi_tenant.enabled:
            raise NoTenantContextError()
        return DEFAULT_TENANT_ID

    @classmethod
    async def get_config(cls, *, tenant_id: int | None = None) -> ShougangPortalAdminConfig | None:
        resolved_tenant_id = cls._resolve_tenant_id(tenant_id)
        async with get_async_db_session() as session:
            repository = PortalAdminConfigRepositoryImpl(session)
            config_record = await repository.get(resolved_tenant_id)
            if config_record is None or not config_record.value:
                return None
            try:
                return ShougangPortalAdminConfig.model_validate_json(config_record.value)
            except ValidationError:
                logger.exception("invalid shougang portal config in config table")
                raise

    @classmethod
    async def save_config(
        cls,
        payload: ShougangPortalAdminConfig,
        *,
        tenant_id: int | None = None,
        create_user: int | None = None,
    ) -> ShougangPortalAdminConfig:
        # Kept in the public signature for compatibility with the endpoint;
        # the aggregate Config model has no creator column.
        del create_user
        resolved_tenant_id = cls._resolve_tenant_id(tenant_id)
        normalized_input = ShougangPortalAdminConfig.model_validate(payload.model_dump(mode="json"))

        for attempt in range(cls._MAX_SAVE_ATTEMPTS):
            try:
                return await cls._save_config_once(
                    normalized_input,
                    tenant_id=resolved_tenant_id,
                )
            except IntegrityError:
                if attempt + 1 >= cls._MAX_SAVE_ATTEMPTS:
                    raise
                logger.warning(
                    "portal config first-row conflict; retrying tenant={} attempt={}",
                    resolved_tenant_id,
                    attempt + 2,
                )
        raise RuntimeError("portal config save retry loop exited unexpectedly")

    @classmethod
    async def _save_config_once(
        cls,
        payload: ShougangPortalAdminConfig,
        *,
        tenant_id: int,
    ) -> ShougangPortalAdminConfig:
        affected_department_ids: list[int] = []
        rebuild_pools = False
        async with get_async_db_session() as session:
            config_repository = PortalAdminConfigRepositoryImpl(session)
            async with session.begin():
                stored = await config_repository.get_for_update(tenant_id)
                stored_version = 0
                if stored is not None and stored.value:
                    stored_config = ShougangPortalAdminConfig.model_validate_json(stored.value)
                    stored_version = max(int(stored_config.version), 0)
                else:
                    stored_config = None

                normalized = payload.model_copy(deep=True)
                normalized.version = stored_version + 1
                old_bindings = (
                    DepartmentBusinessDomainService.domain_department_pairs(
                        stored_config.portal.domains,
                    )
                    if stored_config is not None
                    else set()
                )
                new_bindings = DepartmentBusinessDomainService.domain_department_pairs(
                    normalized.portal.domains,
                )
                if old_bindings != new_bindings:
                    affected_department_ids = sorted(
                        {department_id for department_id, _code in old_bindings | new_bindings}
                    )
                old_recommendation = stored_config.portal.recommendation if stored_config else None
                rebuild_pools = old_recommendation is None or any(
                    (
                        old_recommendation.hot_half_life_days
                        != normalized.portal.recommendation.hot_half_life_days,
                        old_recommendation.home_entry_source_weight
                        != normalized.portal.recommendation.home_entry_source_weight,
                    )
                )

                await config_repository.write_value(tenant_id, normalized.model_dump_json())
        try:
            _enqueue_recommendation_config_post_commit(
                tenant_id=tenant_id,
                department_ids=affected_department_ids,
                rebuild_pools=rebuild_pools,
            )
        except Exception:
            logger.exception("failed to enqueue portal recommendation config post-commit hooks")
        return normalized
