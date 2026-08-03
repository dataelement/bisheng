import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import HTTPException

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.core.context.tenant import (
    DEFAULT_TENANT_ID,
    bypass_tenant_filter,
    set_visible_tenant_ids,
    visible_tenant_ids,
)
from bisheng.developer_token.domain.schemas import DeveloperTokenPrincipal
from bisheng.user.domain.repositories.interfaces.user_repository import UserRepository

logger = logging.getLogger(__name__)

EXTERNAL_USER_ID_MAX_LENGTH = 255


class FilelibUserContextService:
    """Resolve the business user independently from token authentication."""

    def __init__(self, user_repository: UserRepository) -> None:
        self.user_repository = user_repository

    @staticmethod
    def normalize_external_id(external_id: str | None) -> str | None:
        if external_id is None:
            return None
        normalized = external_id.strip()
        if not normalized or len(normalized) > EXTERNAL_USER_ID_MAX_LENGTH:
            raise HTTPException(status_code=422, detail="invalid external_id")
        return normalized

    @asynccontextmanager
    async def use_user(
        self,
        principal: DeveloperTokenPrincipal,
        external_id: str | None,
    ) -> AsyncIterator[UserPayload]:
        normalized_external_id = self.normalize_external_id(external_id)
        if normalized_external_id is None:
            yield principal.user
            return

        visible_token = set_visible_tenant_ids(None)
        try:
            with bypass_tenant_filter():
                candidates = await self.user_repository.list_active_by_external_id(
                    normalized_external_id,
                )
                if len(candidates) != 1:
                    logger.warning(
                        "filelib external user resolution denied token_id=%s reason=%s",
                        principal.token_id,
                        "not_unique" if candidates else "not_found",
                    )
                    raise UnAuthorizedError.http_exception()

                candidate = candidates[0]
                login_user = await UserPayload.init_login_user(
                    user_id=int(candidate.user_id),
                    user_name=str(candidate.user_name or ""),
                    tenant_id=DEFAULT_TENANT_ID,
                    token_version=int(getattr(candidate, "token_version", 0) or 0),
                )
                yield login_user
        finally:
            visible_tenant_ids.reset(visible_token)
