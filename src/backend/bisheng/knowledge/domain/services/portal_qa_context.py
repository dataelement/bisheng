"""Request-local QA facts; preparation may perform I/O, filtering never does."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from typing import Any

from loguru import logger

from bisheng.knowledge.domain.models.knowledge import KnowledgeState, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.services.department_file_view_access_service import (
    DepartmentFileAccessStatus,
    DepartmentFileViewAccessService,
)
from bisheng.knowledge.domain.services.portal_search_context import PortalSearchContext
from bisheng.permission.domain.services.permission_read_context import PermissionReadContext


class QaPermissionReadContext(PermissionReadContext):
    async def read(self, key, loader, *, io: bool = False):
        async def measured():
            # Count actual client invocations, including failed attempts, not cache requests.
            if isinstance(key, tuple) and key[0] in {"tuples", "level_checks"}:
                self.stats[f"fga.{key[0]}.calls"] += 1
            return await loader()

        return await super().read(key, measured, io=io)


class PortalQaContext(PortalSearchContext):
    def __init__(self, *, phase: str = "candidates", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.phase = phase
        self.permissions = QaPermissionReadContext(tenant_id=self.identity[0], user_id=self.identity[1])
        self.permissions.department_loader = lambda ids: self.ensure("departments", ids)
        self.decisions: dict[int, bool] = {}
        self.entry_lock = asyncio.Lock()
        self.login_user = None
        self.loads: set[asyncio.Task] = set()

    async def ensure(self, kind: str, ids, *, loader=None) -> dict[int, Any]:
        # Own each in-flight load so explicit close also cancels reads, not only awaiters.
        async def load(missing):
            task = asyncio.create_task(loader(missing) if loader else self.repository.load(kind, missing))
            self.loads.add(task)
            try:
                return await task
            finally:
                self.loads.discard(task)

        return await super().ensure(kind, ids, loader=load)

    def bind_scope(self, scope: Any) -> None:
        self.require_identity(tenant_id=scope.tenant_id, user_id=scope.user_id, routing_version=scope.routing_version)
        if frozenset(scope.requested_space_ids) != self.space_ids:
            raise ValueError("QA context scope changed")
        self.bind_filters(repr((tuple(scope.requested_space_ids), sorted(scope.explicit_entry_ids_by_space.items()))))

    async def prepare_entries(self, owner: Any, entries: Sequence[KnowledgeFile]) -> None:
        self.require_identity(
            tenant_id=owner.login_user.tenant_id, user_id=owner.login_user.user_id, routing_version=self.identity[2]
        )
        async with self.entry_lock:
            if self.closed:
                raise RuntimeError("QA context closed")
            pending = {int(file.id): file for file in entries if int(file.id) not in self.decisions}
            if not pending:
                return
            started = time.monotonic()
            # Publish decisions only after all required reads and business effects succeed.
            decisions = dict.fromkeys(pending, False)
            valid = [
                file
                for file in pending.values()
                if file.knowledge_id in self.space_ids
                and int(getattr(file, "tenant_id", 0) or 0) == self.identity[0]
                and file.status == KnowledgeFileStatus.SUCCESS.value
                and getattr(file, "deleted_at", None) is None
            ]
            self.seed("files", {int(file.id): file for file in valid})
            ids = {int(file.knowledge_id) for file in valid}
            spaces = await self.ensure("spaces", ids)
            scopes = await self.ensure("scopes", ids)
            private = []
            for file in valid:
                sid = int(file.knowledge_id)
                space = spaces.get(sid)
                if (
                    space is None
                    or space.type != KnowledgeTypeEnum.SPACE.value
                    or getattr(space, "state", None) == KnowledgeState.DELETING.value
                ):
                    continue
                level = getattr(space, "space_level", None) or getattr(scopes.get(sid), "level", None)
                if getattr(level, "value", level) == "public":
                    decisions[int(file.id)] = True
                else:
                    private.append(file)
            if private:
                if self.login_user is None:
                    self.login_user = await self.phase_user(owner.login_user)
                bindings = await self.ensure("bindings", {int(file.knowledge_id) for file in private})
                departments = await self.ensure(
                    "departments", {int(row.department_id) for rows in bindings.values() for row in rows}
                )
                resources = DepartmentFileViewAccessService.build_resources(
                    private, spaces, scopes, bindings, departments
                )
                guarded = [file for file in private if resources[int(file.id)].applicable]
                ordinary = [file for file in private if not resources[int(file.id)].applicable]
                if guarded:
                    decisions.update(await self._prepare_department(owner, guarded, resources))
                if ordinary:
                    decisions.update(await self._prepare_ordinary(owner, ordinary))
            self.decisions.update(decisions)
            self.stats["authorization.entries"] += len(pending)
            self.stats["authorization.elapsed_ms"] += int((time.monotonic() - started) * 1000)

    async def _prepare_department(self, owner: Any, files: list[KnowledgeFile], resources: dict) -> dict[int, bool]:
        service = owner.department_file_view_access_service
        if service is None:
            raise RuntimeError("QA department authorization unavailable")
        valid = {fid: row for fid, row in resources.items() if row.applicable and row.valid}
        grant_resources = {(int(row.file.knowledge_id), fid): int(row.department_id) for fid, row in valid.items()}
        approvers = await self.approvers({int(row.department_id) for row in valid.values()})
        grants = await self.active_grants(
            tenant_id=self.identity[0], user_id=self.identity[1], resources=grant_resources
        )
        # Reuse the same evaluator, but feed already hydrated file/space/organization facts.
        evaluator = DepartmentFileViewAccessService(
            grant_repository=service.grant_repository,
            permission_read_context=self.permissions,
        )
        permissions = await evaluator._resolve_permission_ids(self.login_user, files)
        if service.persist_stale_grant_revalidation:
            from bisheng.knowledge.domain.models.department_file_view_grant import DepartmentFileViewGrantStatus

            stale = {
                (int(row.space_id), int(row.file_id)): grant_resources[(int(row.space_id), int(row.file_id))]
                for rows in self.data.get("grants", {}).values()
                for row in rows
                if row.status == DepartmentFileViewGrantStatus.ACTIVE
                and (int(row.space_id), int(row.file_id)) in grant_resources
                and int(row.department_id) != grant_resources[(int(row.space_id), int(row.file_id))]
            }
            if stale:
                # Mutation keeps its locking read and audit; never write detached cached rows.
                await service._invalidate_stale_grants(
                    tenant_id=self.identity[0],
                    user_id=self.identity[1],
                    resources=stale,
                )
        decisions = DepartmentFileViewAccessService.evaluate_prepared(
            login_user=self.login_user,
            files=files,
            resources=resources,
            permission_map=permissions,
            approver_map=approvers,
            grant_map=grants,
        )
        return {fid: decision.status == DepartmentFileAccessStatus.ALLOWED for fid, decision in decisions.items()}

    async def _prepare_ordinary(self, owner: Any, files: list[KnowledgeFile]) -> dict[int, bool]:
        from bisheng.knowledge.domain.services.knowledge_space_service import (
            KnowledgeSpaceService,
            _SPACE_MEMBER_ROLE_TO_RELATION,
        )
        from bisheng.permission.domain.knowledge_space_permission_template import default_permission_ids_for_relation
        from bisheng.permission.domain.services.fine_grained_permission_service import FineGrainedPermissionService

        members = await self.ensure("members", {int(file.knowledge_id) for file in files})
        semaphore = asyncio.Semaphore(16)

        async def prepare(file: KnowledgeFile) -> tuple[int, bool]:
            async with semaphore:
                permissions, matched = await FineGrainedPermissionService.get_effective_permission_ids_async(
                    self.login_user,
                    "knowledge_file",
                    int(file.id),
                    lineage=KnowledgeSpaceService._build_item_lineage(file, int(file.knowledge_id)),
                    nearest_binding_wins=True,
                    return_match_metadata=True,
                    use_permission_level_fallback=False,
                    read_context=self.permissions,
                )
                if not matched:
                    # Preserve the original last-active-member mapping semantics.
                    active = [row for row in members.get(int(file.knowledge_id), []) if row.is_active]
                    if active:
                        permissions.update(
                            default_permission_ids_for_relation(
                                _SPACE_MEMBER_ROLE_TO_RELATION.get(active[-1].user_role, "")
                            )
                        )
                return int(file.id), "view_file" in permissions

        tasks = [asyncio.create_task(prepare(file)) for file in files]
        try:
            return dict(await asyncio.gather(*tasks))
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            # Results/errors were propagated above; finish cancellation of this batch.
            await asyncio.gather(*tasks, return_exceptions=True)

    def evaluate_entries(self, entries: Sequence[KnowledgeFile]) -> dict[int, bool]:
        if self.closed:
            raise RuntimeError("QA context closed")
        if any(int(file.id) not in self.decisions for file in entries):
            raise RuntimeError("QA entries were not prepared")
        started = time.monotonic()
        result = {int(file.id): self.decisions[int(file.id)] for file in entries}
        self.stats["filter.elapsed_ms"] += int((time.monotonic() - started) * 1000)
        return result

    def report(self) -> None:
        rows = {
            kind: sum(len(value) if isinstance(value, list) else 1 for value in values.values())
            for kind, values in self.data.items()
        }
        logger.info(
            "portal_qa_context phase={} rows={} data_stats={} permission_stats={} sql_stats={}",
            self.phase,
            rows,
            dict(self.stats),
            dict(self.permissions.stats),
            dict(getattr(self.repository, "query_counts", {})),
        )

    async def close(self) -> None:
        self.closed = True
        tasks = list(self.loads)
        for task in tasks:
            task.cancel()
        # Reads propagate errors to their original awaiters; wait for ownership to end.
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.permissions.close()
        async with self.entry_lock:
            async with self.lock:
                self.report()
                self.decisions.clear()
                self.data.clear()
                self.loaded.clear()
                self.permissions.files.clear()
                self.permissions.spaces.clear()
                self.permissions.scopes.clear()
                self.login_user = None
