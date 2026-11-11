"""Nickname entry points: self target is derived from the authenticated actor."""

from loguru import logger
from starlette.concurrency import run_in_threadpool

from bisheng.common.errcode.user import UserForbiddenError
from bisheng.user.domain.repositories.nickname_repository import NicknameRepository
from bisheng.user.domain.schemas.nickname import NicknameActor


class NicknameService:
    repository = NicknameRepository

    @staticmethod
    def profile_enabled() -> bool:
        from bisheng.user.domain.services.user import UserService

        return UserService._dsh_enabled()

    @classmethod
    def rename_self(cls, actor: NicknameActor, proposed: str):
        if actor.user_id <= 0:
            raise UserForbiddenError()
        return cls.repository.rename(actor.user_id, proposed, actor, profile_enabled=cls.profile_enabled())

    @classmethod
    async def arename_self(cls, actor: NicknameActor, proposed: str):
        return await run_in_threadpool(cls.rename_self, actor, proposed)

    @classmethod
    def rename_managed(cls, user_id: int, proposed: str, actor: NicknameActor):
        # The department owner verifies scope and finishes its existing writes
        # first. Nickname, protection, version and audit share this final commit.
        return cls.repository.rename(user_id, proposed, actor, profile_enabled=cls.profile_enabled())

    @classmethod
    async def arename_managed(cls, user_id: int, proposed: str, actor: NicknameActor):
        return await run_in_threadpool(cls.rename_managed, user_id, proposed, actor)

    @classmethod
    def record_failure(cls, user_id: int, proposed: str, actor: NicknameActor, *, reason: str):
        logger.info("Nickname change rejected actor={} target={}", actor.user_id, user_id)
        cls.repository.record_failure(user_id, proposed, actor, reason=reason)

    @classmethod
    async def arecord_failure(cls, user_id: int, proposed: str, actor: NicknameActor, *, reason: str):
        await run_in_threadpool(cls.record_failure, user_id, proposed, actor, reason=reason)
