"""Managed Wiki. The injected GET port is bound to the frozen provider instance/KB.

GET never acknowledges a write. Only a writer with its operation-specific target
revision may checkpoint convergence in the transaction that finishes the write.
"""

from urllib.parse import quote

from bisheng.knowledge.domain.repositories.provider_wiki_repository import (
    WikiControl,
    WikiObservation,
    WikiUnavailable,
    read_proof,
)
from bisheng.permission.application.business_authorization import check_business_action


async def scoped_wiki_get(scope, path, params):
    import httpx

    from bisheng.knowledge.application.provider_v1_runtime import instance_client
    from bisheng.knowledge.infrastructure.providers.registry import PortContext

    kb = scope.remote_kb_id
    if not kb or kb in (".", "..") or any(c in kb for c in "/\\%?#"):
        raise WikiUnavailable()
    ctx = PortContext(
        scope.tenant_id,
        scope.space_id,
        "weknora",
        "wiki_read",
        scope.instance_id,
        scope.generation,
        scope.remote_scope_id,
        kb,
    )
    async with instance_client(ctx) as client:
        try:
            response = await client.get("knowledgebase/" + quote(kb, safe="") + "/wiki/" + path, params=params)
            response.raise_for_status()
            row = response.json()
        except (httpx.HTTPError, ValueError):
            if path == "source-revision":
                return {}  # missing/failed proof is query_failed, never an empty or ready Wiki
            raise WikiUnavailable() from None
        if not isinstance(row, dict):
            raise WikiUnavailable()
        return row


async def observe_revision(get, scope):
    """Read from the frozen library, with no local or remote write."""
    return WikiObservation(scope, await get(scope, "source-revision", {"min_revision": scope.target}))


def _slug(value):
    if (
        not isinstance(value, str)
        or len(value) > 255
        or any(p in ("", ".", "..") for p in value.split("/"))
        or any(c in value for c in "%?#\\")
        or not value.isprintable()
    ):
        raise WikiUnavailable()
    return value


class WikiApplication:
    def __init__(self, *, get, control=None, allowed=check_business_action):
        self.get, self.control, self.allowed = get, control or WikiControl(), allowed

    @classmethod
    def from_runtime(cls, resolver):
        """Use only a capability-proven KB-bound port; the port prefixes the Wiki base path."""

        async def get(scope, path, params):
            binding = {
                "tenant_id": scope.tenant_id,
                "space_id": scope.space_id,
                "provider_key": "weknora",
                "state": scope.state,
                "generation": scope.generation,
                "instance_id": scope.instance_id,
                "remote_scope_id": scope.remote_scope_id,
                "remote_kb_id": scope.remote_kb_id,
            }
            port = resolver.resolve(
                tenant_id=scope.tenant_id,
                space_id=scope.space_id,
                provider_key="weknora",
                binding=binding,
                operation="wiki_read",
            )
            return await port.get(path, params=params)

        return cls(get=get)

    async def _scope(self, user, space, generation=None):
        if not await self.allowed(user, resource_type="knowledge_space", resource_id=space, action="visible"):
            raise WikiUnavailable()
        scope = await self.control.scope(space)
        if generation is not None and (type(generation) is not int or generation != scope.generation):
            raise WikiUnavailable()
        return scope

    async def _finish(self, user, scope):
        if await self._scope(user, scope.space_id) != scope:
            raise WikiUnavailable()

    async def _state(self, scope):
        if scope.state != "ready":
            return "preparing"
        if scope.pending is not None or scope.target != scope.applied:
            return "updating"
        wire = (await observe_revision(self.get, scope)).wire
        if not read_proof(wire, scope.target):
            if (
                isinstance(wire, dict)
                and wire.get("success") is True
                and isinstance(row := wire.get("data"), dict)
                and row.get("ready") is False
            ):
                return "generating"
            return "query_failed"
        return "empty" if wire["data"]["empty"] else "ready"

    async def status_detail(self, user, space):
        scope = await self._scope(user, space)
        state = await self._state(scope)
        await self._finish(user, scope)
        return {"state": state, "generation": scope.generation}

    async def status(self, user, space):
        return (await self.status_detail(user, space))["state"]

    async def _read(self, scope, path, **params):
        if await self._state(scope) not in ("empty", "ready"):
            raise WikiUnavailable()
        return await self.get(scope, path, {"min_revision": scope.target, **params})

    async def _file(self, user, scope, remote_id, action):
        file_id = await self.control.source(scope, remote_id)
        if file_id is None or not await self.allowed(
            user, resource_type="knowledge_file", resource_id=file_id, action="visible"
        ):
            return None
        if action == "visible" or await self.allowed(
            user, resource_type="knowledge_file", resource_id=file_id, action=action
        ):
            return file_id
        return None

    async def source(self, user, space, *, generation, remote_id, action):
        scope = await self._scope(user, space, generation)
        if generation is None or action not in ("visible", "download") or scope.state != "ready" or scope.pending:
            raise WikiUnavailable()
        file_id = await self._file(user, scope, remote_id, action)
        if file_id is None:
            raise WikiUnavailable()
        await self._finish(user, scope)
        return file_id  # local resource only, never a provider URL or a download credential

    def _summary(self, scope, row):
        if row["knowledge_base_id"] != scope.remote_kb_id:
            raise WikiUnavailable()
        return {"slug": _slug(row["slug"]), **{k: row[k] for k in ("title", "page_type", "summary")}}

    async def page(self, user, space, *, generation, slug):
        scope = await self._scope(user, space, generation)
        if generation is None:
            raise WikiUnavailable()
        row = await self._read(scope, "pages/" + quote(_slug(slug), safe="/"))
        page = self._summary(scope, row)
        if page["slug"] != slug:
            raise WikiUnavailable()
        page.update(
            content=row["content"],
            in_links=[_slug(s) for s in row.get("in_links") or ()],
            out_links=[_slug(s) for s in row.get("out_links") or ()],
            sources=[],
        )
        for ref in row.get("source_refs") or ():
            file_id = await self._file(user, scope, ref.partition("|")[0], "visible")
            page["sources"].append({"file_id": file_id} if file_id else {"restricted": True})
        await self._finish(user, scope)
        return page

    async def graph(self, user, space, *, generation=None):
        scope = await self._scope(user, space, generation)
        row = await self._read(scope, "graph")
        result = {
            "nodes": [
                {"slug": _slug(n["slug"]), "page_type": n["page_type"], "title": n["title"]} for n in row["nodes"] or ()
            ],
            "edges": [{k: _slug(e[k]) for k in ("source", "target")} for e in row["edges"] or ()],
        }
        await self._finish(user, scope)
        return result

    async def search(self, user, space, query, *, generation=None):
        scope = await self._scope(user, space, generation)
        row = await self._read(scope, "search", q=query)
        result = [self._summary(scope, p) for p in row["pages"] or ()]
        await self._finish(user, scope)
        return result
