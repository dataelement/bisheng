"""F026 external listing and delivery. HTTP routes and response adaptation belong to Wave 4.

A handle is an untrusted locator, not a grant. The caller must enter ``open``
for the lifetime of the response, including disconnects and Range requests.
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass

from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.repositories.provider_read_repository import SqlReadFacts
from bisheng.permission.application.access import get_f048_resource_adapter


class ReadAuthority:
    """Shared API/worker adapter over existing business-target verification and F048."""

    def __init__(self, *, spaces, files, runtime):
        self._adapters = {"knowledge_space": spaces, "folder": files, "knowledge_file": files}
        self._runtime = runtime

    async def visible(self, actor, space_id, rows):
        from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao

        space = await KnowledgeDao.aquery_by_id(space_id)
        if space is None or space.tenant_id != actor.current_tenant_id or space.type != KnowledgeTypeEnum.SPACE.value:
            return set()
        visible = set()
        for start in range(0, len(rows), 200):
            files = await KnowledgeFileDao.aget_file_by_ids([r.resource_id for r in rows[start : start + 200]])
            targets = await self._adapters["knowledge_file"].resolve_permission_targets_from_rows(
                rows=files,
                knowledge=space,
                actor=actor,
                action="visible",
            )
            decisions = await self._runtime.batch_check_actions(actor, targets, "visible")
            visible.update(
                (t.resource_type, int(t.resource_id)) for t, allowed in zip(targets, decisions, strict=True) if allowed
            )
        return visible

    async def check_action(self, *, actor, resource_type, resource_id, action):
        return await self._adapters[resource_type].check_action(
            actor=actor, resource_type=resource_type, resource_id=resource_id, action=action
        )


@dataclass(frozen=True, slots=True)
class Entry:
    resource_id: int
    kind: str
    name: str


@dataclass(frozen=True, slots=True)
class Listing:
    items: tuple[Entry, ...]
    total: int


@dataclass(frozen=True, slots=True)
class ReadHandle:
    space_id: int
    file_id: int
    version_id: int
    generation: int
    epoch: int
    operation: str


class ProviderReads:
    def __init__(self, *, store, permissions, resolver):
        self._store, self._permissions, self._resolver = store, permissions, resolver

    @classmethod
    async def from_runtime(cls, resolver):
        return cls(
            store=SqlReadFacts(), permissions=await get_f048_resource_adapter("provider_reads"), resolver=resolver
        )

    async def _allowed(self, actor, kind, local_id, action):
        return await self._permissions.check_action(
            actor=actor, resource_type=kind, resource_id=str(local_id), action=action
        )

    async def _require_space(self, actor, space_id):
        if not await self._allowed(actor, "knowledge_space", space_id, "visible"):
            raise PermissionDeniedError()

    async def managed_card_count(self, actor, space_id):
        """Match the managed-cards entry: visible + edit, raw root files only."""
        await self._require_space(actor, space_id)
        if not await self._allowed(actor, "knowledge_space", space_id, "edit"):
            raise PermissionDeniedError()
        return await self._store.count_files(tenant_id=actor.current_tenant_id, space_id=space_id, root_card=True)

    async def detail_count(self, actor, space_id):
        """Space-visible detail badge: ready primary files across the whole tree."""
        await self._require_space(actor, space_id)
        return await self._store.count_files(tenant_id=actor.current_tenant_id, space_id=space_id, root_card=False)

    async def list(
        self,
        actor,
        space_id,
        *,
        parent_id=None,
        all_folders=False,
        kind=None,
        query="",
        descending=False,
        offset=0,
        limit=50,
    ):
        if offset < 0 or not 1 <= limit <= 200 or kind not in (None, "folder", "knowledge_file"):
            raise ValueError("invalid list parameters")
        await self._require_space(actor, space_id)
        rows = await self._store.load(tenant_id=actor.current_tenant_id, space_id=space_id)
        allowed = await self._permissions.visible(actor, space_id, rows)
        visible = [r for r in rows if (r.kind, r.resource_id) in allowed]
        if parent_id is not None and not any(r.kind == "folder" and r.resource_id == parent_id for r in visible):
            raise PermissionDeniedError()
        matches = [
            r
            for r in visible
            if (all_folders or r.parent_id == parent_id)
            and (kind is None or r.kind == kind)
            and query.casefold() in r.name.casefold()
        ]
        matches.sort(key=lambda r: (r.name.casefold(), r.resource_id), reverse=descending)
        return Listing(
            tuple(Entry(r.resource_id, r.kind, r.name) for r in matches[offset : offset + limit]),
            len(matches),
        )

    async def visible_facts(self, actor, space_id, parent_id=None):
        await self._require_space(actor, space_id)
        rows = await self._store.load(tenant_id=actor.current_tenant_id, space_id=space_id)
        allowed = await self._permissions.visible(actor, space_id, rows)
        if parent_id is not None and ('folder', parent_id) not in allowed:
            raise PermissionDeniedError()
        return [r for r in rows if (r.kind, r.resource_id) in allowed]

    async def _locate(self, actor, space_id, file_id, operation):
        if operation not in ("preview", "download"):
            raise PermissionDeniedError()
        await self._require_space(actor, space_id)
        rows = await self._store.load(tenant_id=actor.current_tenant_id, space_id=space_id, resource_id=file_id)
        if len(rows) != 1:
            raise PermissionDeniedError()
        r = rows[0]
        if r.kind != "knowledge_file" or not r.version_id or not await self._allowed(actor, r.kind, file_id, "visible"):
            raise PermissionDeniedError()
        if operation == "download" and not await self._allowed(actor, r.kind, file_id, "download"):
            raise PermissionDeniedError()
        c = r.context
        return ReadHandle(space_id, file_id, r.version_id, c.generation, r.epoch, operation), r

    def _port(self, row, operation):
        c = row.context
        return self._resolver.resolve(
            tenant_id=c.tenant_id,
            space_id=c.space_id,
            provider_key=c.provider_key,
            operation=operation,
            binding={
                "tenant_id": c.tenant_id,
                "space_id": c.space_id,
                "provider_key": c.provider_key,
                "state": "ready",
                "instance_id": c.instance_id,
                "generation": c.generation,
                "remote_scope_id": c.remote_scope_id,
                "remote_kb_id": c.remote_kb_id,
            },
        )

    async def issue(self, actor, space_id, file_id, operation):
        handle, fact = await self._locate(actor, space_id, file_id, operation)
        self._port(fact, operation)  # No handle without current positive capability proof.
        return handle

    async def issue_downloads(self, actor, space_id, file_ids):
        """No partially authorized batch or pre-opened upstream on a later denial."""
        handles = [await self.issue(actor, space_id, file_id, "download") for file_id in dict.fromkeys(file_ids)]
        return tuple(handles)

    @asynccontextmanager
    async def open(self, actor, handle, *, range_header=None):
        current, fact = await self._locate(actor, handle.space_id, handle.file_id, handle.operation)
        if current != handle:
            raise PermissionDeniedError()
        port = self._port(fact, handle.operation)
        async with port.open_stream(fact.remote_id, range_header=range_header) as upstream:
            yield upstream
