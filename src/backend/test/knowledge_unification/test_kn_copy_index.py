"""Real copy index/object adapter with native transport doubles and independent IDs."""

from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.knowledge.domain.repositories.space_copy_repository import root_facts
from bisheng.worker.knowledge import space_copy_worker as module
from test.knowledge_unification import test_move_worker as native
from test.knowledge_unification.test_metadata_index_worker import response


class Collection(native.NativeCollection):
    def delete(self, expr):
        assert expr == "document_id == 181"
        self.rows = [row for row in self.rows if row["document_id"] != 181]
        self.events.append("target_mv_delete")
        return SimpleNamespace(delete_count=0)

    def query_iterator(self, *, batch_size, limit, expr, output_fields):
        assert batch_size == 1000 and limit == -1 and expr == "document_id == 181"
        return native.NativeIterator([row for row in self.rows if row["document_id"] == 181], self.events)


class ES(native.NativeES):
    async def search(self, *, index, body=None, query=None, size=1000, **kwargs):
        wanted = (body or {"query": query})["query"]["term"]["metadata.document_id"]
        assert wanted == (81 if self.name == "source" else 181)
        found = [row for row in self.rows if row["_source"]["metadata"]["document_id"] == wanted]
        ident = f"{self.name}-{len(self.cursors)}"
        self.cursors[ident] = (deepcopy(found), size)
        return response(
            {
                "_scroll_id": ident,
                "_shards": {"failed": 0},
                "timed_out": False,
                "hits": {"total": {"value": len(found), "relation": "eq"}, "hits": deepcopy(found[:size])},
            }
        )

    async def delete_by_query(self, *, index, body=None, query=None, refresh):
        wanted = (body or {"query": query})["query"]["term"]["metadata.document_id"]
        assert self.name == "target" and wanted == 181 and refresh
        matched = [row for row in self.rows if row["_source"]["metadata"]["document_id"] == wanted]
        self.rows = [row for row in self.rows if row not in matched]
        return response(
            {"total": len(matched), "deleted": len(matched), "version_conflicts": 0, "timed_out": False, "failures": []}
        )


class Objects:
    bucket = "bucket"

    def __init__(self):
        self.values = {
            "original/81.txt": b"source bytes",
            "preview/81.md": b"![image](/bucket/knowledge/images/40/81/same.png)",
            "knowledge/images/40/81/same.png": b"image bytes",
        }
        self.minio_client_sync = self

    def stat_object(self, bucket, key):
        value = self.values[key]
        return SimpleNamespace(size=len(value), etag=sha256(value).hexdigest())

    def list_objects(self, bucket, *, prefix, recursive):
        return [SimpleNamespace(object_name=key) for key in tuple(self.values) if key.startswith(prefix)]

    def copy_object_sync(self, *, source_bucket, source_object, dest_bucket, dest_object):
        assert source_bucket == dest_bucket == self.bucket and source_object != dest_object
        self.values[dest_object] = self.values[source_object]

    def get_object_sync(self, *, object_name):
        return self.values.get(object_name)

    def put_object_sync(self, *, object_name, file):
        self.values[object_name] = file.read()


@pytest.fixture
async def copying(monkeypatch):
    events = []
    old_es, new_es = ES("source", [native.chunk(1), native.chunk(2)], events), ES("target", [], events)
    collection, objects = Collection(events), Objects()
    source = native.Knowledge(
        id=40, tenant_id=101, name="source", type=3, model="11", index_name="source", collection_name="source"
    )
    target = native.Knowledge(
        id=50, tenant_id=101, name="copy", type=3, model="11", index_name="target", collection_name="target"
    )

    async def elasticsearch(*, knowledge, **kwargs):
        return old_es if knowledge.id == 40 else new_es

    async def vector(*args, **kwargs):
        return SimpleNamespace(
            col=collection,
            embedding_func=SimpleNamespace(
                aembed_documents=AsyncMock(side_effect=lambda texts: [[0.1, 0.2] for _ in texts])
            ),
        )

    monkeypatch.setattr(module.KnowledgeRag, "init_knowledge_es_vectorstore", elasticsearch)
    monkeypatch.setattr(module.KnowledgeRag, "init_knowledge_milvus_vectorstore", vector)
    monkeypatch.setattr(module, "get_minio_storage_sync", lambda: objects)
    snapshot = {
        "source": root_facts(source),
        "destination": root_facts(target),
        "source_file": {
            "id": 81,
            "knowledge_id": 40,
            "object_name": "original/81.txt",
            "preview_file_object_name": "preview/81.md",
            "user_metadata": {"image": "knowledge/images/40/81/same.png"},
        },
        "target_file": {
            "id": 181,
            "knowledge_id": 50,
            "object_name": "original/181.txt",
            "preview_file_object_name": "preview/181.md",
        },
        "target_version": {"id": 281},
    }
    return SimpleNamespace(old=old_es, new=new_es, col=collection, objects=objects, snapshot=snapshot)


async def apply(context):
    return await module.apply_space_copy_item(
        operation_id="copy",
        snapshot=context.snapshot,
        file_ids={"81": 181},
        invoke_user_id=7,
        guard=AsyncMock(return_value=None),
    )


async def test_copy_rewrites_independent_objects_images_manual_chunks_and_preserves_source(copying):
    original = deepcopy(copying.old.rows)
    result = await apply(copying)
    assert (result.file_id, result.source_count, result.milvus_count, result.es_count) == (181, 2, 2, 2)
    assert copying.old.rows == original
    assert all(
        row["_source"]["metadata"]["knowledge_id"] == 50
        and row["_source"]["metadata"]["document_id"] == 181
        and "/50/181/" in row["_source"]["text"]
        for row in copying.new.rows
    )
    assert copying.objects.values["original/81.txt"] == copying.objects.values["original/181.txt"]
    assert b"/50/181/" in copying.objects.values["preview/181.md"]
    assert result.user_metadata == {"image": "knowledge/images/50/181/same.png"}
    assert copying.old.closed and copying.new.closed


async def test_incomplete_index_ack_is_visible_and_never_removes_source(copying):
    original = deepcopy(copying.old.rows)
    copying.new.fail_add = RuntimeError("ES write ACK failed")
    with pytest.raises(RuntimeError, match="ACK failed"):
        await apply(copying)
    assert copying.old.rows == original and copying.objects.values["original/81.txt"] == b"source bytes"


def test_copy_of_previously_moved_file_rewrites_its_original_image_namespace(copying):
    # Actual move retains original object/image keys while current File ownership
    # changes. File 81 is accepted in space 41; its original image namespace is 40.
    objects = module.CopyObjects(
        copying.objects,
        source_id=41,
        target_id=50,
        file_ids={"81": 181},
        object_map={"original/81.txt": "original/181.txt", "preview/81.md": "preview/181.md"},
    )
    before = deepcopy(copying.objects.values)
    copied = objects.objects(copying.snapshot["source_file"], copying.snapshot["target_file"])
    assert b"/50/181/" in copying.objects.values["preview/181.md"]
    assert copied == {"image": "knowledge/images/50/181/same.png"}
    assert copying.objects.values["knowledge/images/50/181/same.png"] == b"image bytes"
    assert all(copying.objects.values[key] == value for key, value in before.items())


@pytest.mark.parametrize(
    "key",
    [
        "knowledge/images/40/999/foreign.png",
        "knowledge/images/0/81/bad.png",
        "knowledge/images/40/81/../escape.png",
        "knowledge/images/40/81/a/../../escape.png",
    ],
)
def test_historical_namespace_does_not_authorize_foreign_file_or_path_escape(copying, key):
    from copy import deepcopy

    before = deepcopy(copying.objects.values)
    objects = module.CopyObjects(copying.objects, source_id=41, target_id=50, file_ids={"81": 181}, object_map={})
    with pytest.raises(ValueError):
        objects.rewrite(key)
    assert copying.objects.values == before


async def test_copy_after_move_rewrites_current_index_chunks_without_changing_source(copying, monkeypatch):
    copying.snapshot["source"]["id"] = 41
    copying.snapshot["source_file"]["knowledge_id"] = 41
    for row in copying.old.rows:
        row["_source"]["metadata"]["knowledge_id"] = 41
    before = deepcopy(copying.old.rows)

    async def current_es(*, knowledge, **kwargs):
        return copying.old if knowledge.id == 41 else copying.new

    monkeypatch.setattr(module.KnowledgeRag, "init_knowledge_es_vectorstore", current_es)
    result = await apply(copying)
    assert result.milvus_count == result.es_count == 2
    assert all("/50/181/" in row["_source"]["text"] for row in copying.new.rows)
    assert copying.old.rows == before
