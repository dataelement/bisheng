"""单次请求、单个校验阶段的权限资料读取；不改变授权规则。"""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from copy import deepcopy
from typing import Any, Awaitable, Callable, Hashable


class PermissionReadContext:
    def __init__(self, *, tenant_id: int, user_id: int) -> None:
        self.identity = (int(tenant_id), int(user_id))
        self.cache: dict[Hashable, Any] = {}
        self.pending: dict[Hashable, asyncio.Task] = {}
        self.stats = Counter()
        self.semaphore = asyncio.Semaphore(16)
        self.closed = False
        self.files: dict[int, Any] = {}
        self.spaces: dict[int, Any] = {}
        self.scopes: dict[int, Any] = {}
        self.department_loader = None

    async def department_paths(self, bindings, subjects):
        from bisheng.permission.domain.services.fine_grained_permission_service import FineGrainedPermissionService

        if self.department_loader is None:
            return await FineGrainedPermissionService.get_binding_department_paths(bindings)
        ids = {
            int(binding["subject_id"])
            for binding in bindings
            if binding.get("subject_type") == "department" and binding.get("include_children")
        }
        ids.update(
            int(subject.split(":", 1)[1].split("#", 1)[0]) for subject in subjects if subject.startswith("department:")
        )
        rows = await self.department_loader(ids)
        return {sid: getattr(rows.get(sid), "path", "") or "" for sid in ids}

    async def read(self, key: Hashable, loader: Callable[[], Awaitable[Any]], *, io: bool = False) -> Any:
        if self.closed:
            raise RuntimeError("权限读取阶段已关闭")
        if key in self.cache:
            self.stats["cache_hits"] += 1
            return deepcopy(self.cache[key])
        task = self.pending.get(key)
        if task is None:

            async def run():
                started = time.monotonic()
                try:
                    if io:
                        async with self.semaphore:
                            value = await loader()
                    else:
                        value = await loader()
                    if not self.closed:
                        self.cache[key] = deepcopy(value)
                    self.stats["loads"] += 1
                    return value
                finally:
                    self.stats["elapsed_ms"] += int((time.monotonic() - started) * 1000)
                    self.pending.pop(key, None)

            task = asyncio.create_task(run())
            # 等待者取消时任务仍归整个请求所有，消费异常避免无人等待警告。
            task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
            self.pending[key] = task
        else:
            self.stats["inflight_waits"] += 1
        return deepcopy(await asyncio.shield(task))

    async def close(self) -> None:
        self.closed = True
        tasks = list(self.pending.values())
        for task in tasks:
            task.cancel()
        # 这里只清理已传播给等待者的异常或取消。
        await asyncio.gather(*tasks, return_exceptions=True)
        self.pending.clear()
        self.cache.clear()

    def public_permissions(self, lineage: list, *, portal: bool = False) -> set[str] | None:
        from bisheng.knowledge.domain.models.knowledge import KnowledgeState, KnowledgeTypeEnum
        from bisheng.permission.domain.knowledge_space_permission_template import (
            default_permission_ids_for_relation as default_knowledge_space_permissions,
        )

        sid = next((int(value) for kind, value in lineage if kind == "knowledge_space"), None)
        if sid is None or sid not in self.spaces:
            return None
        space = self.spaces[sid]
        if space is None or space.type != KnowledgeTypeEnum.SPACE.value:
            return set()
        if portal and getattr(space, "state", None) == KnowledgeState.DELETING.value:
            return set()
        level = getattr(space, "space_level", None)
        if level is None:
            level = getattr(self.scopes.get(sid), "level", None)
        return default_knowledge_space_permissions("viewer") if getattr(level, "value", level) == "public" else set()

    def creator(self, object_type: str, object_id: str) -> tuple[bool, int | None]:
        # 原规则：文件隐式 owner 是所属知识库创建者，而非上传者。
        if object_type == "folder":
            return True, None
        sid = None
        if object_type == "knowledge_file" and int(object_id) in self.files:
            file = self.files[int(object_id)]
            if file is None:
                return True, None
            sid = int(file.knowledge_id)
        elif object_type == "knowledge_space":
            sid = int(object_id)
        if sid is not None and sid in self.spaces:
            space = self.spaces[sid]
            if object_type == "knowledge_space":
                from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum

                if space is None or space.type != KnowledgeTypeEnum.SPACE.value:
                    return True, None
            return True, getattr(space, "user_id", None)
        return False, None
