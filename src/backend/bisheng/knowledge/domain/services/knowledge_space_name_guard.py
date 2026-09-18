"""知识库创建和改名共用的跨租户名称互斥保护。"""

from collections.abc import Awaitable, Callable
from functools import wraps
from inspect import signature
from typing import Any, TypeVar

from bisheng.common.errcode.knowledge_space import PersonalDefaultSpaceCreationBusyError, SpaceNameAllocationBusyError
from bisheng.knowledge.domain.repositories.implementations.knowledge_migration_lock_repository_impl import (
    KnowledgeMigrationLockRepositoryImpl,
)
from bisheng.knowledge.domain.services.personal_default_space_creation_guard import PersonalDefaultSpaceCreationGuard

T = TypeVar("T")


class KnowledgeSpaceNameGuard(PersonalDefaultSpaceCreationGuard):
    def __init__(self) -> None:
        # 不按租户或姓名分锁, 避免跨租户及数据库字符排序规则差异造成穿透。
        self.key = "knowledge:space-name:global-write"
        self.repository = KnowledgeMigrationLockRepositoryImpl(key=self.key)

    async def run(self, operation: Callable[[], Awaitable[T]]) -> T:
        try:
            return await super().run(operation)
        except PersonalDefaultSpaceCreationBusyError as exc:
            raise SpaceNameAllocationBusyError() from exc


def serialize_space_name_write(*, only_when_named: bool = False) -> Callable:
    def decorate(method: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        method_signature = signature(method)

        @wraps(method)
        async def wrapped(*args: Any, **kwargs: Any) -> T:
            if only_when_named and method_signature.bind(*args, **kwargs).arguments.get("name") is None:
                return await method(*args, **kwargs)
            return await KnowledgeSpaceNameGuard().run(lambda: method(*args, **kwargs))

        return wrapped

    return decorate
