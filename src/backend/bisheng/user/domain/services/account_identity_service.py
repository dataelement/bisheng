"""Human account policy and unambiguous identity resolution (F011)."""

from starlette.concurrency import run_in_threadpool

from bisheng.common.errcode.user import AmbiguousAccountError
from bisheng.database.constants import DefaultRole
from bisheng.user.domain.models.user import User
from bisheng.user.domain.repositories.account_identity_repository import AccountIdentityRepository
from bisheng.user.domain.rules.identity import (
    resolve_external_candidates,
    resolve_login_candidates,
    validate_account,
    validate_nickname,
)


class AccountIdentityService:
    repository = AccountIdentityRepository

    @classmethod
    def create_local(
        cls,
        user: User,
        *,
        role_ids: list[int] | None = None,
        group_ids: list[int] | None = None,
        bootstrap: bool = False,
    ) -> User:
        validate_account(user.external_id)
        validate_nickname(user.user_name)
        return cls.repository.create(
            user,
            exact=True,
            role_ids=[DefaultRole] if role_ids is None else role_ids,
            group_ids=group_ids or [],
            bootstrap=bootstrap,
        )

    @classmethod
    async def acreate_local(cls, user: User, **kwargs) -> User:
        return await run_in_threadpool(cls.create_local, user, **kwargs)

    @classmethod
    def create_external(
        cls,
        user: User,
        *,
        role_ids: list[int] | None = None,
        group_ids: list[int] | None = None,
    ) -> User:
        validate_nickname(user.user_name)
        return cls.repository.create(
            user,
            exact=False,
            role_ids=[DefaultRole] if role_ids is None else role_ids,
            group_ids=group_ids or [],
        )

    @classmethod
    async def acreate_external(cls, user: User, **kwargs) -> User:
        return await run_in_threadpool(cls.create_external, user, **kwargs)

    @classmethod
    def resolve_login(cls, raw_account: str) -> User | None:
        return resolve_login_candidates(cls.repository.login_candidates(raw_account))

    @classmethod
    async def aresolve_login(cls, raw_account: str) -> User | None:
        return await run_in_threadpool(cls.resolve_login, raw_account)

    @classmethod
    def resolve_external(cls, raw_account: str, source: str | None = None) -> User | None:
        return resolve_external_candidates(cls.repository.find_external(raw_account, source=source))

    @classmethod
    async def aresolve_external(cls, raw_account: str, source: str | None = None) -> User | None:
        return await run_in_threadpool(cls.resolve_external, raw_account, source=source)

    @classmethod
    def resolve_deprecated_sso(cls, external_id: str | None, legacy_name: str) -> User | None:
        if external_id is not None:
            return cls.resolve_external(external_id)
        # Captured provider identifiers survive manual display-name changes;
        # an unrelated new nickname must not steal that established binding.
        for captured_only in (True, False):
            candidates = cls.repository.find_deprecated_sso_name(legacy_name, captured_only=captured_only)
            if len(candidates) > 1:
                raise AmbiguousAccountError()
            if candidates:
                return candidates[0]
        return cls.resolve_external(legacy_name)

    @classmethod
    async def aresolve_deprecated_sso(cls, external_id: str | None, legacy_name: str) -> User | None:
        return await run_in_threadpool(cls.resolve_deprecated_sso, external_id, legacy_name)
