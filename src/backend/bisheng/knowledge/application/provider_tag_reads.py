"""Bound WeKnora vocabulary and manual tag CAS. Remote identities never enter browser DTOs."""

import hashlib
import json
import re

import httpx

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.application.provider_tags import (
    ProviderTags,
    TagConflict,
    TagContractUnavailable,
    TagScope,
    TagWriteRejected,
)
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
MANUAL_CONTRACT = "manual-tags-v1"
WHOLE_CONTRACT = "whole-tags-v1"


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


def safe_name(value):
    """A display name only: never an identity, never accepted back as a tag reference."""
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise ProviderFeatureUnavailable()
    return value


def whole_revision(route, doc, ids):
    """Opaque local token for a whole-set snapshot the upstream itself cannot version.

    The remote ignores revisions, so this token is only comparable to another
    snapshot of the same document taken by us; it never leaves the browser as a
    remote identity and grants no authority.
    """
    identities = [
        route.tenant_id,
        route.space_id,
        route.generation,
        route.instance_id,
        route.capability_revision,
        route.remote_scope_id,
        route.remote_kb_id,
        doc,
        sorted(ids),
    ]
    digest = hashlib.sha256(json.dumps(identities, separators=(",", ":")).encode()).digest()
    return int.from_bytes(digest[:7], "big") >> 3


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

    async def page(self, scope, page, page_size, keyword=None):
        params = {"page": page, "page_size": page_size}
        if keyword is not None:
            params["keyword"] = keyword
        try:
            data = envelope(await self.client.get(f"knowledge-bases/{self.kb}/tags", params=params))
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

    async def create_word(self, scope, name):
        """Create one word in the bound library, reusing a same-name word already there."""
        try:
            response = await self.client.post(f"knowledge-bases/{self.kb}/tags", json={"name": name})
        except httpx.HTTPError:
            # Unknown outcome: keep the write slot, let the caller reconcile.
            raise ProviderFeatureUnavailable() from None
        if response.status_code == 409:
            # A same-name word exists. Reusing its identity keeps one tag per name
            # instead of failing an action the user cannot resolve, and it also
            # recovers a create whose response was lost after the remote commit.
            try:
                rows, _ = await self.page(scope, 1, 200, keyword=name)
            except (httpx.HTTPError, ProviderFeatureUnavailable):
                raise TagConflict("duplicate tag name") from None
            matches = [remote for remote, existing in rows if existing == name]
            if len(matches) != 1:
                raise TagConflict("duplicate tag name")
            return matches[0]
        if response.status_code in (400, 401, 403, 404, 405, 422):
            raise TagWriteRejected()
        data = envelope(response)
        if (
            data.get("knowledge_base_id"),
            str(data.get("tenant_id")),
            data.get("name"),
        ) != (self.kb, self.route.remote_scope_id, name):
            raise ProviderFeatureUnavailable()
        return safe_id(data.get("id"))


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
            response = await self.client.get(self.path)
        except httpx.HTTPError:
            raise ProviderFeatureUnavailable() from None
        if response.status_code in (404, 405):
            # The route itself is absent: this upstream has no per-document contract.
            raise TagContractUnavailable()
        return self.selection(response)

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


class WeKnoraWholeTagPort(WeKnoraTagPort):
    """Documented whole-set fallback for an upstream without `manual-tags-v1`.

    The remote stores one tag list per document (manual and automatic together)
    and its batch write replaces that whole list with no revision guard. Every
    write therefore re-reads first and refuses a snapshot the caller never saw.
    """

    def __init__(self, route, client, doc):
        super().__init__(route, client)
        self.doc = safe_id(doc)
        self.path = f"knowledge/{self.doc}"

    def _tag_rows(self, data):
        if (
            data.get("id"),
            data.get("knowledge_base_id"),
            str(data.get("tenant_id")),
        ) != (self.doc, self.kb, self.route.remote_scope_id):
            raise ProviderFeatureUnavailable()
        if "tags" not in data:
            raise ProviderFeatureUnavailable()
        # This upstream marshals a nil relation slice as null, which is its own
        # representation of "no tags" (its editor reads it the same way). A field
        # that is absent entirely is still refused as an unproven payload.
        tags = data.get("tags")
        if tags is None:
            return []
        if not isinstance(tags, list):
            raise ProviderFeatureUnavailable()
        rows = []
        for tag in tags:
            if (
                not isinstance(tag, dict)
                or tag.get("knowledge_base_id") != self.kb
                or str(tag.get("tenant_id")) != self.route.remote_scope_id
            ):
                raise ProviderFeatureUnavailable()
            # A name is optional here: a tag's identity is the reference, and the
            # display path validates the name at its own boundary.
            name = tag.get("name")
            rows.append((safe_id(tag.get("id")), name if isinstance(name, str) else None))
        if len({remote for remote, _ in rows}) != len(rows):
            raise ProviderFeatureUnavailable()
        return rows

    def _tags(self, data):
        return [remote for remote, _ in self._tag_rows(data)]

    async def detail(self):
        try:
            return self._tag_rows(envelope(await self.client.get(self.path)))
        except httpx.HTTPError:
            raise ProviderFeatureUnavailable() from None

    async def snapshot(self):
        rows = await self.detail()
        ids = [remote for remote, _ in rows]
        return ids, whole_revision(self.route, self.doc, ids)

    async def replace(self, expected, token_of, remote):
        """Write the whole set after proving the read the browser confirmed is current."""
        _, revision = await self.snapshot()
        if token_of(revision) != expected:
            raise TagConflict("stale whole-set snapshot")
        try:
            response = await self.client.put(
                "knowledge/tags", json={"kb_id": self.kb, "updates": {self.doc: sorted(set(remote))}}
            )
        except httpx.HTTPError:
            # Unknown outcome: the caller keeps the write slot and never retries.
            raise ProviderFeatureUnavailable() from None
        if response.status_code in (400, 401, 403, 404, 405, 422):
            raise TagWriteRejected()
        if response.status_code != 200:
            raise ProviderFeatureUnavailable()
        try:
            wire = response.json()
        except ValueError:
            raise ProviderFeatureUnavailable() from None
        # The legacy route answers with a bare success flag, so confirmation is a re-read.
        if not isinstance(wire, dict) or wire.get("success") is not True:
            raise ProviderFeatureUnavailable()
        confirmed, after = await self.snapshot()
        if sorted(confirmed) != sorted(set(remote)):
            raise ProviderFeatureUnavailable()
        return after


class TagRequest:
    """Pin route and primary file/version/epoch, then recheck at IO boundaries."""

    def __init__(self, service, space_id, generation, file_id=None, *, write=False):
        self.service, self.space_id, self.generation = service, space_id, generation
        self.file_id, self.write = file_id, write
        self.repo = ProviderTagRepository(get_async_db_session)
        self.mapping = ProviderRetrievalRepository()

    async def space_route(self, action):
        """Resolve the frozen route for a space-level action; a file target is not allowed."""
        if self.file_id is not None:
            raise ProviderFeatureUnavailable()
        await self.service._require_action("knowledge_space", self.space_id, action)
        route = await resolve_space_route(self.space_id)
        if not route or route.provider_key != "weknora" or route.capability_revision <= 0:
            raise ProviderFeatureUnavailable()
        if route.generation != self.generation:
            raise KnowledgeOperationPlanConflictError()
        return route, None

    async def target(self):
        if self.file_id is None:
            return await self.space_route("visible")
        await self.service._require_file_action(
            self.file_id, "rename" if self.write else "visible", space_id=self.space_id
        )
        route = await resolve_space_route(self.space_id)
        if not route or route.provider_key != "weknora" or route.capability_revision <= 0:
            raise ProviderFeatureUnavailable()
        if route.generation != self.generation:
            raise KnowledgeOperationPlanConflictError()
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
        from bisheng.knowledge.application.provider_external_token import provider_external_identity

        frozen = await self.target()
        route, _ = frozen
        scope = TagScope(route.tenant_id, self.space_id, self.generation)
        with provider_external_identity(self.service.login_user.user_id):
            async with instance_client(route) as client:
                try:
                    result = await self.tags(frozen, WeKnoraTagPort(route, client)).page(
                        scope, page=page, page_size=page_size
                    )
                except TagConflict:
                    raise KnowledgeOperationPlanConflictError() from None
        await self.verify(frozen)
        return {**result, "generation": self.generation}

    async def create_word(self, name):
        """Space tag management action: create one word, independent of any file association."""
        from bisheng.knowledge.application.provider_external_token import provider_external_identity

        frozen = await self.space_route("edit")
        route, _ = frozen
        scope = TagScope(route.tenant_id, self.space_id, self.generation)

        async def authorize(candidate, action, file_id):
            if candidate != scope or action != "edit_space" or file_id is not None:
                return False
            await self.verify(frozen)
            return True

        with provider_external_identity(self.service.login_user.user_id):
            async with instance_client(route) as client:
                try:
                    ref = await ProviderTags(self.repo, WeKnoraTagPort(route, client), authorize=authorize).create_word(
                        scope, name
                    )
                except TagConflict:
                    raise KnowledgeOperationPlanConflictError() from None
                except TagWriteRejected:
                    raise ProviderFeatureUnavailable() from None
        await self.verify(frozen)
        return {"tag_ref_id": ref, "name": name, "generation": self.generation}

    async def file_labels(self):
        """Display-only tag names for one document, in one remote read.

        A provider listing carries no per-row tags and the upstream has no batch tag
        read, so the file list asks for this only when the user opens one row. It is
        a *read* of the document's full tag set (manual and automatic), never a
        selection the caller may submit back.
        """
        from bisheng.knowledge.application.provider_external_token import provider_external_identity

        if self.write:
            raise ProviderFeatureUnavailable()
        frozen = await self.target()
        route, file = frozen
        if file is None:
            raise ProviderFeatureUnavailable()
        with provider_external_identity(self.service.login_user.user_id):
            async with instance_client(route) as client:
                rows = await WeKnoraWholeTagPort(route, client, file[0]).detail()
        await self.verify(frozen)
        return {"names": [safe_name(name) for _, name in rows], "generation": self.generation}

    async def file_selection(self, command=None):
        from bisheng.knowledge.application.provider_external_token import provider_external_identity

        frozen = await self.target()
        route, file = frozen
        scope = TagScope(route.tenant_id, self.space_id, self.generation)
        if self.write != (command is not None) or file is None:
            raise ProviderFeatureUnavailable()
        with provider_external_identity(self.service.login_user.user_id):
            async with instance_client(route) as client:
                port = WeKnoraFileTagPort(route, client, self.file_id, file[0])
                whole = None
                try:
                    # Positive, per-document contract proof; null is never an empty set.
                    ids, revision = await port.read()
                    contract = MANUAL_CONTRACT
                except TagContractUnavailable:
                    # Deployment chose the whole-set fallback for upstreams without the
                    # dedicated route; it carries no upstream revision and says so.
                    whole = WeKnoraWholeTagPort(route, client, file[0])
                    ids, revision = await whole.snapshot()
                    contract = WHOLE_CONTRACT
                await self.verify(frozen)

                def token(raw):
                    return edit_revision(route, self.file_id, file, raw)

                try:
                    if command is None:
                        refs = await self.repo.refs(scope, ids)
                    else:
                        if token(revision) != command.expected_revision:
                            raise TagConflict("stale document revision")
                        refs = command.tag_ref_ids
                        if whole is None:
                            revision = await self.tags(frozen, port).edit(
                                scope,
                                self.file_id,
                                command.mode,
                                refs,
                                expected_revision=revision,
                                before_send=lambda: self.verify(frozen),
                            )
                        else:
                            revision = await self.tags(frozen, whole).edit_whole(
                                scope,
                                self.file_id,
                                command.mode,
                                refs,
                                write=lambda remote: whole.replace(command.expected_revision, token, remote),
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
            "edit_contract": contract,
        }
