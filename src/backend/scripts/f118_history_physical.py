"""Exact orphan payload backup/deletion port, owned by prepare_f118_history.

Never creates a RAG collection/index, resolves embeddings, or drops a store.
All business writers must be stopped by the operator before preview/apply.
"""

import asyncio
import json
import os
from hashlib import sha256
from pathlib import Path

from scripts.prepare_f118_history import blocked, canonical, checksum

OBJECT_FIELDS = (
    "object_name",
    "bbox_object_name",
    "preview_file_object_name",
    "thumbnails",
    "html_snapshot_object_name",
)


def object_keys(row):
    # Stored fields plus the two actual legacy writer naming rules. The file
    # PK is globally unique. No bucket/prefix/KB-name sweep is permitted.
    from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils

    keys = {row[name] for name in OBJECT_FIELDS if row.get(name)}
    if row.get("file_type", 1) == 1 and row.get("id"):
        keys.add(str(row["id"]))  # Legacy converted PDF object.
        preview = KnowledgeUtils.resolve_preview_object_name(
            row["id"], row.get("file_name"), row.get("preview_file_object_name")
        )
        if preview:
            keys.add(preview)
        source = KnowledgeUtils.resolve_source_object_name(row["id"], row.get("file_name"), row.get("object_name"))
        if source:
            keys.add(source)
    return keys


def body(value):
    return getattr(value, "body", value)


class OrphanPayloads:
    def __init__(self, reader, directory, *, environment="local-test"):
        self.environment = environment
        self.es, self.mv = reader._es, reader._milvus
        self.storage, self.directory = reader._storage, Path(directory)

    def _save(self, data):
        digest = sha256(data).hexdigest()
        path = self.directory / digest
        if not path.exists():
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        if sha256(path.read_bytes()).hexdigest() != digest:
            blocked("physical_backup_changed")
        return digest

    def _load(self, digest):
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            blocked("physical_backup_identity_invalid")
        path = self.directory / digest
        if path.is_symlink():
            blocked("physical_backup_identity_invalid")
        data = path.read_bytes()
        if sha256(data).hexdigest() != digest:
            blocked("physical_backup_changed")
        return data

    async def _stat(self, key):
        from miniopy_async.error import S3Error

        from bisheng.knowledge.application.unification_minio import validate_object_key

        validate_object_key(key)
        try:
            stat = await self.storage._client.stat_object(self.storage.bucket, key)
        except S3Error as error:
            if error.code in {"NoSuchKey", "NoSuchObject"}:
                return None
            raise
        return {"etag": stat.etag, "size": stat.size, "version_id": stat.version_id}

    async def _images(self, prefix):
        keys = set()
        async for obj in self.storage._client.list_objects(self.storage.bucket, prefix=prefix, recursive=True):
            if not obj.object_name.startswith(prefix) or obj.is_dir:
                blocked("orphan_image_scope_changed")
            keys.add(obj.object_name)
        return keys

    async def _es_rows(self, index, ident, knowledge):
        if not index:
            return {"exists": False, "rows": []}
        if not body(await self.es.indices.exists(index=index)):
            return {"exists": False, "rows": []}
        mappings = body(await self.es.indices.get_mapping(index=index))
        if set(mappings) != {index}:  # Aliases/patterns cannot own deletion.
            blocked("physical_es_concrete_index_required")
        fields = mappings[index].get("mappings", {}).get("properties", {}).get("metadata", {}).get("properties", {})
        if fields.get("document_id", {}).get("type") not in {"long", "integer"}:
            blocked("physical_es_file_identity_unavailable")
        terms = [{"term": {"metadata.document_id": ident}}]
        if fields.get("knowledge_id", {}).get("type") in {"long", "integer"}:
            terms.append({"term": {"metadata.knowledge_id": knowledge}})
        query = {"bool": {"filter": terms}}
        rows, scroll = [], None
        try:
            page = body(await self.es.search(index=index, query=query, size=500, scroll="2m", seq_no_primary_term=True))
            while True:
                scroll = page.get("_scroll_id", scroll)
                if page.get("_shards", {}).get("failed") != 0 or page.get("timed_out"):
                    blocked("physical_es_scan_incomplete")
                hits = page["hits"]["hits"]
                rows.extend({k: hit[k] for k in ("_id", "_source", "_seq_no", "_primary_term")} for hit in hits)
                if not hits:
                    break
                if not scroll:
                    blocked("physical_es_scan_incomplete")
                page = body(await self.es.scroll(scroll_id=scroll, scroll="2m"))
        finally:
            if scroll:
                await self.es.clear_scroll(scroll_id=scroll)
        return {"exists": True, "mapping": checksum(mappings), "rows": sorted(rows, key=lambda r: r["_id"])}

    async def _mv_rows(self, collection, ident, knowledge):
        if not collection or not await asyncio.to_thread(self.mv.has_collection, collection_name=collection):
            return {"exists": False, "rows": []}
        from pymilvus import DataType

        schema = await asyncio.to_thread(self.mv.describe_collection, collection_name=collection)
        fields = {f["name"]: f for f in schema["fields"]}
        if fields.get("document_id", {}).get("type") not in {DataType.INT64, DataType.INT32}:
            blocked("physical_milvus_file_identity_unavailable")
        primary = [name for name, f in fields.items() if f.get("is_primary")]
        if len(primary) != 1:
            blocked("physical_milvus_primary_unavailable")
        expression = f"document_id == {ident}"
        if fields.get("knowledge_id", {}).get("type") in {DataType.INT64, DataType.INT32}:
            expression += f" and knowledge_id == {knowledge}"
        iterator = await asyncio.to_thread(
            self.mv.query_iterator,
            collection_name=collection,
            filter=expression,
            output_fields=["*"],
            batch_size=500,
            consistency_level="Strong",
        )
        rows = []
        try:
            while batch := await asyncio.to_thread(iterator.next):
                rows.extend(batch)
        finally:
            await asyncio.to_thread(iterator.close)
        key = primary[0]
        return canonical(
            {
                "exists": True,
                "schema": checksum(canonical(schema)),
                "primary": key,
                "rows": sorted(rows, key=lambda r: str(r[key])),
            }
        )

    async def capture(self, requests, *, surviving_files):
        self.directory.mkdir(mode=0o700, parents=False, exist_ok=False)
        shared = {key for row in surviving_files for key in object_keys(row)}
        for item in requests:
            file, root = item["file"], item["knowledge"]
            # QA storage has a different row ownership protocol; no guessing.
            if root["type"] not in {0, 3}:
                blocked("orphan_payload_domain_unsupported")
            objects = []
            prefix = f"knowledge/images/{root['id']}/{file['id']}/"
            keys = object_keys(file) | await self._images(prefix)
            for key in sorted(keys):
                if key in shared:
                    blocked("orphan_object_shared_with_live_file")
                stat = await self._stat(key)
                saved = None
                if stat:
                    response = await self.storage._client.get_object(
                        self.storage.bucket, key, version_id=stat["version_id"]
                    )
                    try:
                        data = await response.read()
                    finally:
                        response.close()
                    if len(data) != stat["size"] or await self._stat(key) != stat:
                        blocked("orphan_object_changed_during_backup")
                    saved = self._save(data)
                objects.append({"key": key, "stat": stat, "backup": saved})
            es = await self._es_rows(root.get("index_name"), file["id"], root["id"])
            mv = await self._mv_rows(root.get("collection_name"), file["id"], root["id"])
            item["physical_environment"] = self.environment
            item["payload_backup"] = self._save(
                json.dumps({"objects": objects, "image_prefix": prefix, "es": es, "mv": mv}, sort_keys=True).encode()
            )

    async def apply(self, requests):
        # Validate every backup before deleting any payload; interrupted runs
        # accept exact original records or absence, never new/changed records.
        if any(item.get("physical_environment") != self.environment for item in requests):
            blocked("physical_environment_changed")
        saved = [(item, json.loads(self._load(item["payload_backup"]))) for item in requests]
        for _, snapshot in saved:
            for obj in snapshot["objects"]:
                if obj["backup"]:
                    self._load(obj["backup"])
        for item, snapshot in saved:
            file, root = item["file"], item["knowledge"]
            if await self._images(snapshot["image_prefix"]) - {obj["key"] for obj in snapshot["objects"]}:
                blocked("orphan_image_scope_changed")
            es = await self._es_rows(root.get("index_name"), file["id"], root["id"])
            mv = await self._mv_rows(root.get("collection_name"), file["id"], root["id"])
            for kind, current in (("es", es), ("mv", mv)):
                original = snapshot[kind]
                if {k: v for k, v in current.items() if k != "rows"} != {
                    k: v for k, v in original.items() if k != "rows"
                }:
                    blocked("orphan_index_identity_changed")
                if any(row not in original["rows"] for row in current["rows"]):
                    blocked("orphan_index_contents_changed")
            for obj in snapshot["objects"]:
                stat = await self._stat(obj["key"])
                if stat is not None and stat != obj["stat"]:
                    blocked("orphan_object_changed")
            for row in es["rows"]:
                await self.es.delete(
                    index=root["index_name"],
                    id=row["_id"],
                    if_seq_no=row["_seq_no"],
                    if_primary_term=row["_primary_term"],
                    refresh=True,
                )
            if mv["rows"]:
                await asyncio.to_thread(
                    self.mv.delete,
                    collection_name=root["collection_name"],
                    ids=[row[mv["primary"]] for row in mv["rows"]],
                )
                await asyncio.to_thread(self.mv.flush, collection_name=root["collection_name"])
            for obj in snapshot["objects"]:
                if obj["stat"] is not None:
                    await self.storage._client.remove_object(
                        self.storage.bucket, obj["key"], version_id=obj["stat"]["version_id"]
                    )
            if (await self._es_rows(root.get("index_name"), file["id"], root["id"]))["rows"] or (
                await self._mv_rows(root.get("collection_name"), file["id"], root["id"])
            )["rows"]:
                blocked("orphan_index_delete_incomplete")
            if any([await self._stat(obj["key"]) is not None for obj in snapshot["objects"]]):
                blocked("orphan_object_delete_incomplete")
            if await self._images(snapshot["image_prefix"]):
                blocked("orphan_image_delete_incomplete")
