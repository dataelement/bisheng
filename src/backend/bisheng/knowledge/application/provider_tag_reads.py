"""Bound WeKnora vocabulary and manual tag CAS. Remote identities never enter browser DTOs."""

import hashlib
import json
import re

import httpx

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.application.provider_tags import ProviderTags, TagConflict, TagScope, TagWriteRejected
from bisheng.knowledge.application.provider_v1_runtime import (
    ProviderFeatureUnavailable,
    instance_client,
    resolve_space_route,
)
from bisheng.knowledge.domain.repositories.provider_retrieval_repository import (
    ProviderRetrievalRepository,
    RetrievalFactsUnavailable,
)
from bisheng.knowledge.domain.repositories.provider_tag_repository import ProviderTagRepository

MAX_SAFE = 2**53 - 1


def edit_revision(route, file_id, file, revision):
    # A numeric browser ETag, not an authorization token. A remapped document
    # may start again at the same upstream revision; never CAS against that one.
    identities = [
        route.tenant_id,
        route.space_id,
        route.generation,
        route.instance_id,
        route.capability_revision,
        route.remote_scope_id,
        route.remote_kb_id,
        file_id,
        *file,
        revision,
    ]
    digest = hashlib.sha256(json.dumps(identities, separators=(",", ":")).encode()).digest()
    return int.from_bytes(digest[:7], "big") >> 3  # exactly 53 bits


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,255}", value):
        raise ProviderFeatureUnavailable()
    return value


def uint(value):
    if type(value) is not int or not 0 <= value <= MAX_SAFE:
        raise ProviderFeatureUnavailable()
    return value


def envelope(response):
    if response.status_code != 200:
        raise ProviderFeatureUnavailable()
    try:
        wire = response.json()
    except ValueError:
        raise ProviderFeatureUnavailable() from None
    if not isinstance(wire, dict) or wire.get("success") is not True or not isinstance(wire.get("data"), dict):
        raise ProviderFeatureUnavailable()
    return wire["data"]


class WeKnoraTagPort:
    def __init__(self, route, client):
        self.route, self.client = route, client
        self.kb = safe_id(route.remote_kb_id)

    async def page(self, scope, page, page_size):
        try:
            data = envelope(
                await self.client.get(f"knowledge-bases/{self.kb}/tags", params={"page": page, "page_size": page_size})
            )
        except httpx.HTTPError:
            raise ProviderFeatureUnavailable() from None
        total = uint(data.get("total"))
        tags = data.get("data")
        if (
            (uint(data.get("page")), uint(data.get("page_size"))) != (page, page_size)
            or not isinstance(tags, list)
            or len(tags) != min(page_size, max(0, total - (page - 1) * page_size))
        ):
            raise ProviderFeatureUnavailable()
        rows = []
        for tag in tags:
            if (
                not isinstance(tag, dict)
                or tag.get("knowledge_base_id") != self.kb
                or str(tag.get("tenant_id")) != self.route.remote_scope_id
            ):
                raise ProviderFeatureUnavailable()
            name = tag.get("name")
            if not isinstance(name, str) or not name.strip() or len(name) > 128:
                raise ProviderFeatureUnavailable()
            rows.append((safe_id(tag.get("id")), name))
        if len({remote for remote, _ in rows}) != len(rows):
            raise ProviderFeatureUnavailable()
        return rows, total


class WeKnoraFileTagPort(WeKnoraTagPort):
    """Only the dedicated versioned path. Never issue the legacy /knowledge/tags PUT."""

    def __init__(self, route, client, file_id, remote):
        super().__init__(route, client)
        self.file_id, self.remote = file_id, safe_id(remote)
        self.path = f"knowledge-bases/{self.kb}/documents/{self.remote}/manual-tags-v1"

    def selection(self, response):
        data = envelope(response)
        if (
            data.get("contract"),
            str(data.get("tenant_id")),
            data.get("knowledge_base_id"),
            data.get("knowledge_id"),
        ) != ("manual-tags-v1", self.route.remote_scope_id, self.kb, self.remote):
            raise ProviderFeatureUnavailable()
        ids = data.get("tag_ids")
        if not isinstance(ids, list) or len({safe_id(tag) for tag in ids}) != len(ids):
            raise ProviderFeatureUnavailable()
        return ids, uint(data.get("revision"))

    async def read(self):
        try:
            return self.selection(await self.client.get(self.path))
        except httpx.HTTPError:
            raise ProviderFeatureUnavailable() from None

    async def edit_manual(self, scope, file_id, mode, remote, expected_revision):
        if file_id != self.file_id:
            raise TagConflict("file changed")
        try:
            response = await self.client.put(
                self.path, json={"mode": mode, "tag_ids": list(remote), "expected_revision": expected_revision}
            )
        except httpx.HTTPError:
            # Unknown outcome: retain the shared slot, do not retry the write.
            raise ProviderFeatureUnavailable() from None
        if response.status_code == 409:
            raise TagConflict("revision conflict")
        if response.status_code in (400, 401, 403, 404, 405, 422):
            raise TagWriteRejected()
        ids, revision = self.selection(response)
        if set(ids) != set(remote) or revision not in (expected_revision, expected_revision + 1):
            raise ProviderFeatureUnavailable()
        return revision


class TagRequest:
    """Pin route and primary file/version/epoch, then recheck at IO boundaries."""

    def __init__(self, service, space_id, generation, file_id=None, *, write=False):
        self.service, self.space_id, self.generation = service, space_id, generation
        self.file_id, self.write = file_id, write
        self.repo = ProviderTagRepository(get_async_db_session)
        self.mapping = ProviderRetrievalRepository()

    async def target(self):
        if self.file_id is None:
            await self.service._require_action("knowledge_space", self.space_id, "visible")
        else:
            await self.service._require_file_action(
                self.file_id, "rename" if self.write else "visible", space_id=self.space_id
            )
        route = await resolve_space_route(self.space_id)
        if not route or route.provider_key != "weknora" or route.capability_revision <= 0:
            raise ProviderFeatureUnavailable()
        if route.generation != self.generation:
            raise KnowledgeOperationPlanConflictError()
        if self.file_id is None:
            return route, None
        try:
            rows, _ = await self.mapping.load_candidates(route, file_ids=[self.file_id], tag_ref_ids=[])
        except RetrievalFactsUnavailable:
            raise ProviderFeatureUnavailable() from None
        if len(rows) != 1:
            raise ProviderFeatureUnavailable()
        remote, file_id, version, document, epoch, ready, _, _ = rows[0]
        if file_id != self.file_id or not version or not document or not epoch:
            raise ProviderFeatureUnavailable()
        return route, (safe_id(remote), version, document, epoch, ready)

    async def verify(self, frozen):
        if await self.target() != frozen:
            raise KnowledgeOperationPlanConflictError()

    def tags(self, frozen, port):
        route, _ = frozen

        async def authorize(scope, action, file_id):
            if (
                scope != TagScope(route.tenant_id, self.space_id, self.generation)
                or action != ("edit_file" if self.write else "view")
                or file_id != self.file_id
            ):
                return False
            await self.verify(frozen)
            return True

        return ProviderTags(self.repo, port, authorize=authorize)

    async def page(self, page, page_size):
        frozen = await self.target()
        route, _ = frozen
        scope = TagScope(route.tenant_id, self.space_id, self.generation)
        async with instance_client(route) as client:
            try:
                result = await self.tags(frozen, WeKnoraTagPort(route, client)).page(
                    scope, page=page, page_size=page_size
                )
            except TagConflict:
                raise KnowledgeOperationPlanConflictError() from None
        await self.verify(frozen)
        return {**result, "generation": self.generation}

    async def file_selection(self, command=None):
        frozen = await self.target()
        route, file = frozen
        scope = TagScope(route.tenant_id, self.space_id, self.generation)
        if self.write != (command is not None) or file is None:
            raise ProviderFeatureUnavailable()
        async with instance_client(route) as client:
            port = WeKnoraFileTagPort(route, client, self.file_id, file[0])
            ids, revision = await port.read()  # Positive, per-document contract proof; null is never an empty set.
            await self.verify(frozen)
            try:
                if command is None:
                    refs = await self.repo.refs(scope, ids)
                else:
                    if edit_revision(route, self.file_id, file, revision) != command.expected_revision:
                        raise TagConflict("stale document revision")
                    refs = command.tag_ref_ids
                    revision = await self.tags(frozen, port).edit(
                        scope,
                        self.file_id,
                        command.mode,
                        refs,
                        expected_revision=revision,
                        before_send=lambda: self.verify(frozen),
                    )
            except TagConflict:
                raise KnowledgeOperationPlanConflictError() from None
            except TagWriteRejected:
                raise ProviderFeatureUnavailable() from None
        await self.verify(frozen)
        return {
            "tag_ref_ids": refs,
            "revision": edit_revision(route, self.file_id, file, revision),
            "generation": self.generation,
            "edit_contract": "manual-tags-v1",
        }
