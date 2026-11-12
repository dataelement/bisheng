"""Copy independent objects and complete index pages; never remove source data."""

import asyncio
import hashlib
import re
from contextlib import aclosing
from copy import deepcopy
from dataclasses import dataclass
from io import BytesIO
from urllib.parse import quote, unquote, urlsplit

from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.worker.knowledge.move_worker import (
    _clear,
    _digest,
    _dimension,
    _es_pages,
    _fields,
    _guard,
    _Multiset,
    _valid_vector,
    _verify,
)


@dataclass(frozen=True, slots=True)
class SpaceCopyResult:
    file_id: int
    source_count: int
    milvus_count: int
    es_count: int
    target_payload_digest: str
    user_metadata: dict | None

    def __post_init__(self):
        if (
            type(self.file_id) is not int
            or self.file_id <= 0
            or any(
                type(value) is not int or value < 0 for value in (self.source_count, self.milvus_count, self.es_count)
            )
            or not isinstance(self.target_payload_digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.target_payload_digest) is None
            or (self.user_metadata is not None and not isinstance(self.user_metadata, dict))
        ):
            raise ValueError("copy result requires complete typed native counts and digest")


class CopyObjects:
    def __init__(self, storage, *, source_id, target_id, file_ids, object_map):
        self.storage, self.source_id, self.target_id = storage, source_id, target_id
        self.file_ids, self.copied, self.object_map = file_ids, set(), object_map
        self.prefixes = set()

    def mapped(self, key):
        match = re.fullmatch(r"knowledge/images/([1-9][0-9]*)/([1-9][0-9]*)/(.+)", key)
        if (
            match is None
            or match[2] not in self.file_ids
            or any(part in {"", ".", ".."} for part in match[3].split("/"))
            or any(ord(char) < 32 or ord(char) == 127 for char in key)
        ):
            raise ValueError("copy attachment is outside the accepted source files")
        return f"knowledge/images/{self.target_id}/{self.file_ids[match[2]]}/{match[3]}"

    def image_prefix(self, key):
        # Space is a historical storage prefix, while the globally unique File
        # ID must belong to the actual accepted copy scope. Never list a bucket.
        match = re.match(r"knowledge/images/([1-9][0-9]*)/([1-9][0-9]*)/", key)
        if match is None or match[2] not in self.file_ids:
            raise ValueError("copy image prefix is outside the accepted source files")
        prefix = match[0]
        if key != prefix:
            self.mapped(key)
        if prefix in self.prefixes:
            return
        self.prefixes.add(prefix)
        for row in self.storage.minio_client_sync.list_objects(self.storage.bucket, prefix=prefix, recursive=True):
            self.copy(row.object_name, self.mapped(row.object_name))

    def copy(self, old, new):
        if (old, new) in self.copied:
            return
        client, bucket = self.storage.minio_client_sync, self.storage.bucket
        source = client.stat_object(bucket, old)
        self.storage.copy_object_sync(source_bucket=bucket, source_object=old, dest_bucket=bucket, dest_object=new)
        actual = client.stat_object(bucket, new)
        if (actual.size, actual.etag) != (source.size, source.etag):
            raise ValueError("copy object ACK does not match source bytes")
        self.copied.add((old, new))

    def rewrite(self, value):
        if isinstance(value, dict):
            return {key: self.rewrite(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.rewrite(item) for item in value]
        if not isinstance(value, str):
            return value

        def replace(match):
            raw = match[0]
            parsed = urlsplit(raw)
            key = unquote(parsed.path.lstrip("/"))
            if key.startswith(self.storage.bucket + "/"):
                key = key[len(self.storage.bucket) + 1 :]
            new = self.object_map.get(key)
            if key.startswith("knowledge/images/"):
                mapped = self.mapped(key)
                self.image_prefix(key)
                new = new or mapped
            if new is None:
                return raw
            self.copy(key, new)
            offset = parsed.path.find(key)
            # Preserve only the original public bucket/host prefix. A signed
            # query for the old key must never be attached to the new key.
            if offset < 0:
                encoded = quote(key, safe="/")
                offset = parsed.path.find(encoded)
            prefix = parsed.path[:offset] if offset >= 0 else ""
            if parsed.scheme:
                prefix = f"{parsed.scheme}://{parsed.netloc}" + prefix
            return prefix + quote(new, safe="/")

        return re.sub(
            r"(?:https?://[^/\s]+/|/)?(?:[A-Za-z0-9_%.-]+/)+[A-Za-z0-9_%./~-]+(?:\?[^\s<>\"'()\[\]]*)?", replace, value
        )

    def objects(self, source, target):
        prefix = f"knowledge/images/{self.source_id}/{source['id']}/"
        self.image_prefix(prefix)
        for name in ("object_name", "preview_file_object_name", "bbox_object_name", "thumbnails"):
            old, new = source.get(name), target.get(name)
            if not old:
                continue
            old = unquote(urlsplit(old).path.lstrip("/")) if "://" in old else old
            if old.startswith(self.storage.bucket + "/"):
                old = old[len(self.storage.bucket) + 1 :]
            if not new or new == old:
                raise ValueError("copy requires an independent object key")
            if old.startswith("knowledge/images/"):
                self.image_prefix(old)
            if name in {"preview_file_object_name", "bbox_object_name"}:
                content = self.storage.get_object_sync(object_name=old)
                if content is None:
                    raise ValueError("copy source preview is missing")
                try:
                    rendered = self.rewrite(content.decode("utf-8")).encode("utf-8")
                except UnicodeDecodeError:
                    rendered = content
                self.storage.put_object_sync(object_name=new, file=BytesIO(rendered))
                actual = self.storage.get_object_sync(object_name=new)
                if actual is None or hashlib.sha256(actual).digest() != hashlib.sha256(rendered).digest():
                    raise ValueError("copy rewritten object did not verify")
            else:
                self.copy(old, new)
        return self.rewrite(deepcopy(source.get("user_metadata")))


async def apply_space_copy_item(*, operation_id, snapshot, file_ids, invoke_user_id, guard, object_map=None):
    await _guard(guard)
    source, destination = Knowledge(**snapshot["source"]), Knowledge(**snapshot["destination"])
    before, copied = snapshot["source_file"], snapshot["target_file"]
    if (
        source.id == destination.id
        or before["id"] == copied["id"]
        or file_ids.get(str(before["id"])) != copied["id"]
        or source.model != destination.model
        or before["knowledge_id"] != source.id
        or copied["knowledge_id"] != destination.id
    ):
        raise ValueError("copy requires exact independent native source and target")
    objects = CopyObjects(
        get_minio_storage_sync(),
        source_id=source.id,
        target_id=destination.id,
        file_ids=file_ids,
        object_map=object_map
        or {
            before[key]: copied[key]
            for key in ("object_name", "preview_file_object_name", "bbox_object_name", "thumbnails")
            if before.get(key) and copied.get(key)
        },
    )
    values = await asyncio.to_thread(objects.objects, before, copied)
    await _guard(guard)
    stores = []
    try:
        for row in (source, destination):
            stores.append(
                await KnowledgeRag.init_knowledge_es_vectorstore(
                    knowledge=row,
                    expected_model_config_revision=row.model_config_revision,
                    expected_index_generation=row.index_generation,
                )
            )
        old_es, new_es = stores
        vector = await KnowledgeRag.init_knowledge_milvus_vectorstore(
            invoke_user_id,
            knowledge=destination,
            expected_model_config_revision=destination.model_config_revision,
            expected_index_generation=destination.index_generation,
        )
        fields, dimension = _fields(vector.col), _dimension(vector.col)
        await _clear(new_es, destination.index_name, vector.col, copied["id"], guard)
        expected_mv, expected_es, source_rows, seen = _Multiset(), _Multiset(), _Multiset(), set()
        async with aclosing(_es_pages(old_es, source.index_name, before["id"], guard)) as pages:
            async for hits in pages:
                texts, metadatas, ids = [], [], []
                for hit in hits:
                    ident, body = hit.get("_id"), hit.get("_source")
                    if (
                        not isinstance(ident, str)
                        or not ident
                        or ident in seen
                        or not isinstance(body, dict)
                        or not isinstance(body.get("text"), str)
                        or not isinstance(body.get("metadata"), dict)
                    ):
                        raise ValueError("copy source chunk is incomplete")
                    seen.add(ident)
                    if (
                        body["metadata"].get("document_id") != before["id"]
                        or body["metadata"].get("knowledge_id") != source.id
                    ):
                        raise ValueError("copy source chunk belongs to another file")
                    source_rows.add([ident, body])
                    text = await asyncio.to_thread(objects.rewrite, body["text"])
                    metadata = await asyncio.to_thread(objects.rewrite, deepcopy(body["metadata"]))
                    metadata.pop("pk", None)
                    metadata.update(document_id=copied["id"], knowledge_id=destination.id)
                    if metadata.get("source") == before.get("object_name"):
                        metadata["source"] = copied["object_name"]
                    texts.append(text)
                    metadatas.append(metadata)
                    ids.append(_digest([operation_id, copied["id"], snapshot["target_version"]["id"], ident]))
                    expected_mv.add(
                        {
                            "text": text,
                            **{key: metadata.get(key) for key in fields if key not in {"pk", "vector", "text"}},
                        }
                    )
                    expected_es.add([ids[-1], {"text": text, "metadata": metadata}])
                await _guard(guard)
                embeddings = await vector.embedding_func.aembed_documents(texts)
                if (
                    not isinstance(embeddings, list)
                    or len(embeddings) != len(texts)
                    or any(not _valid_vector(value, dimension) for value in embeddings)
                ):
                    raise ValueError("copy embedding response is incomplete")
                await _guard(guard)
                rows = [
                    {
                        "text": text,
                        "vector": embedding,
                        **{name: metadata.get(name) for name in fields if name not in {"pk", "vector", "text"}},
                    }
                    for text, embedding, metadata in zip(texts, embeddings, metadatas, strict=True)
                ]
                inserted = vector.col.insert(rows)
                if getattr(inserted, "insert_count", None) != len(rows):
                    raise ValueError("copy Milvus insert is incomplete")
                await _guard(guard)
                if (
                    await new_es.aadd_texts(
                        texts=texts,
                        metadatas=metadatas,
                        ids=ids,
                        refresh_indices=True,
                        create_index_if_not_exists=False,
                    )
                    != ids
                ):
                    raise ValueError("copy ES write is incomplete")
        await _guard(guard)
        vector.col.flush()
        mv, es, digest = await _verify(new_es, destination, vector.col, copied["id"], guard)
        if (
            mv.count != source_rows.count
            or es.count != source_rows.count
            or mv.digest() != expected_mv.digest()
            or es.digest() != expected_es.digest()
        ):
            raise ValueError("copy complete target content differs from source")
        await _guard(guard)
        return SpaceCopyResult(copied["id"], source_rows.count, mv.count, es.count, digest, values)
    finally:
        for store in stores:
            await store.client.close()
