"""Request-local provider retrieval. The port factory receives only verified routing facts.

The transport and optional relation/metadata readers are provisioned by the server,
never by a retrieval request. Readers must return a complete, consistent set or raise.
"""

from dataclasses import dataclass
from urllib.parse import quote

import httpx
from langchain_core.documents import Document

from bisheng.knowledge.application.provider_resolver import BindingUnavailable, CapabilityUnavailable
from bisheng.knowledge.domain.repositories.provider_retrieval_repository import ProviderRetrievalRepository


@dataclass(frozen=True)
class MetadataPredicate:
    field: str
    operator: str
    value: object


@dataclass(frozen=True)
class RetrievalSelection:
    file_ids: tuple[int, ...] | None = None
    tag_ref_ids: tuple[int, ...] = ()
    tag_mode: str = "any"
    metadata: tuple[MetadataPredicate, ...] = ()

    def __post_init__(self):
        if self.tag_mode not in ("any", "all") or any(
            type(i) is not int or i <= 0 for i in (*self.tag_ref_ids, *(self.file_ids or ()))
        ):
            raise ValueError("invalid local retrieval selection")


@dataclass(frozen=True)
class TagAssociations:
    """One complete revision of the requested library-local tag relations."""

    by_tag: dict[str, set[str]]
    revision: int
    complete: bool


class WeKnoraSearchPort:
    def __init__(self, client, route, associated=None, metadata_types=None, filter_metadata=None):
        self.client = client
        self.route = route
        self.associated = associated
        self.metadata_types = metadata_types or {}
        self.filter_metadata = filter_metadata

    async def constrain(self, ids, tags, selection):
        for p in selection.metadata:
            if self.filter_metadata is None or self.metadata_types.get((p.field, p.operator)) is not type(p.value):
                raise CapabilityUnavailable("metadata filter equivalence not verified")
        if tags:
            if self.associated is None:
                raise CapabilityUnavailable("current tag associations unavailable")
            snapshot = await self.associated(tuple(tags))
            if (
                snapshot.complete is not True
                or type(snapshot.revision) is not int
                or snapshot.revision < 0
                or set(snapshot.by_tag) != set(tags)
            ):
                raise CapabilityUnavailable("incomplete provider tag relations")
            sets = [snapshot.by_tag[tag] for tag in tags]
            ids &= (set.union if selection.tag_mode == "any" else set.intersection)(*sets)
        for p in selection.metadata:
            ids &= await self.filter_metadata(p)
        return ids

    async def recall(self, query, ids):
        if not ids:
            return []
        try:
            response = await self.client.post(
                "knowledge-bases/" + quote(self.route.remote_kb_id, safe="") + "/hybrid-search",
                json={"query_text": query, "knowledge_ids": sorted(ids), "skip_context_enrichment": True},
                follow_redirects=False,
            )
        except httpx.RequestError:
            # Deliberately omit credentials, provider URL and upstream response body.
            raise RuntimeError(f"provider retrieval failed for space {self.route.space_id}") from None
        if response.status_code != 200:
            raise RuntimeError(f"provider retrieval failed for space {self.route.space_id}")
        data = response.json()
        if isinstance(data, dict) and data.get("success") is True and "data" in data and data["data"] is None:
            return []  # A Go nil result slice encodes as JSON null.
        if not isinstance(data, dict) or data.get("success") is not True or not isinstance(data.get("data"), list):
            raise ValueError("invalid provider retrieval result")
        return data["data"]


class ProviderRetrieval:
    def __init__(self, port_factory, *, repository=None):
        self.repository = repository if repository is not None else ProviderRetrievalRepository()
        self.port_factory = port_factory

    async def route(self, space):
        return await self.repository.route(space)

    async def candidates(self, route, selection, port, visibility):
        rows, tags = await self.repository.load_candidates(
            route, file_ids=selection.file_ids, tag_ref_ids=selection.tag_ref_ids
        )
        visible = await visibility.post_filter_visible_files(route.space_id, [r[1] for r in rows])
        mappings = {r[0]: tuple(r[1:]) for r in rows if r[1] in visible}
        constrained = await port.constrain(set(mappings), tags, selection)
        return {k: v for k, v in mappings.items() if k in constrained}

    async def retrieve(self, space, route, selection, query, max_content, visibility):
        from inspect import isawaitable

        port = self.port_factory(route)
        if isawaitable(port):
            port = await port
        allowed = await self.candidates(route, selection, port, visibility)
        if not allowed:
            return []
        if await self.route(space) != route:
            raise BindingUnavailable("retrieval binding changed")
        hits = await port.recall(query, allowed.keys())
        current = await self.candidates(route, selection, port, visibility)
        if await self.route(space) != route:
            raise BindingUnavailable("retrieval binding changed")
        results = []
        size = 0
        for hit in hits:
            remote = hit["knowledge_id"]
            if (
                remote not in allowed
                or current.get(remote) != allowed[remote]
                or hit.get("knowledge_base_id", route.remote_kb_id) != route.remote_kb_id
            ):
                continue
            file_id, version, logical, epoch, _, name, version_no = allowed[remote]
            doc = Document(
                page_content=hit["content"],
                metadata={
                    "knowledge_id": space.id,
                    "document_id": file_id,
                    "logical_document_id": logical,
                    "version_id": version,
                    "version_no": version_no,
                    "generation": route.generation,
                    "document_name": name,
                    "operation_epoch": epoch,
                    **({"chunk_index": hit["chunk_index"]} if type(hit.get("chunk_index")) is int else {}),
                    "chunk_id": hit["id"],
                },
            )
            results.append((space.id, doc))
            size += len(doc.page_content)
            if size > max_content:
                break
        return results
