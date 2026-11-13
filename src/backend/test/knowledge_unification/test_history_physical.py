"""Selected payloads are backed, scoped and replayable; live neighbors survive."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pymilvus import DataType
from scripts.f118_history_physical import OrphanPayloads

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError


class Iterator:
    def __init__(self, rows):
        self.rows = list(rows)

    def next(self):
        result, self.rows = self.rows, []
        return result

    def close(self):
        pass


@pytest.fixture
def payloads(tmp_path):
    objects = {"uploads/orphan.pdf": b"orphan bytes", "uploads/live.pdf": b"live bytes"}
    es_rows = {
        "orphan-slice": {"document_id": 9, "knowledge_id": 10},
        "live-slice": {"document_id": 8, "knowledge_id": 10},
    }
    mv_rows = {
        91: {"id": 91, "document_id": 9, "knowledge_id": 10, "vector": [0.1, 0.2]},
        81: {"id": 81, "document_id": 8, "knowledge_id": 10, "vector": [0.2, 0.3]},
    }

    async def search(**kwargs):
        terms = kwargs["query"]["bool"]["filter"]
        assert terms == [{"term": {"metadata.document_id": 9}}, {"term": {"metadata.knowledge_id": 10}}]
        return {
            "_scroll_id": "scroll",
            "_shards": {"failed": 0},
            "hits": {
                "hits": [
                    {"_id": key, "_source": {"metadata": value}, "_seq_no": 3, "_primary_term": 1}
                    for key, value in es_rows.items()
                    if value["document_id"] == 9
                ]
            },
        }

    async def delete(**kwargs):
        assert kwargs["index"] == "original-es" and kwargs["if_seq_no"] == 3 and kwargs["if_primary_term"] == 1
        es_rows.pop(kwargs["id"])

    fields = {name: {"type": "long"} for name in ("document_id", "knowledge_id")}
    es = SimpleNamespace(
        indices=SimpleNamespace(
            exists=AsyncMock(return_value=True),
            get_mapping=AsyncMock(
                return_value={"original-es": {"mappings": {"properties": {"metadata": {"properties": fields}}}}}
            ),
        ),
        search=AsyncMock(side_effect=search),
        delete=AsyncMock(side_effect=delete),
        scroll=AsyncMock(return_value={"_shards": {"failed": 0}, "hits": {"hits": []}}),
        clear_scroll=AsyncMock(),
    )

    def mv_delete(**kwargs):
        assert kwargs["collection_name"] == "original-mv"
        for ident in kwargs["ids"]:
            mv_rows.pop(ident)

    def query(**kwargs):
        assert kwargs["filter"] == "document_id == 9 and knowledge_id == 10"
        assert kwargs["output_fields"] == ["*"] and kwargs["consistency_level"] == "Strong"
        return Iterator(row for row in mv_rows.values() if row["document_id"] == 9)

    mv = SimpleNamespace(
        has_collection=lambda **kw: True,
        describe_collection=lambda **kw: {
            "fields": [
                {"name": "id", "type": DataType.INT64, "is_primary": True},
                {"name": "document_id", "type": DataType.INT64},
                {"name": "knowledge_id", "type": DataType.INT64},
                {"name": "vector", "type": DataType.FLOAT_VECTOR},
            ]
        },
        query_iterator=query,
        delete=mv_delete,
        flush=lambda **kw: None,
    )
    adapter = OrphanPayloads(
        SimpleNamespace(_es=es, _milvus=mv, _storage=SimpleNamespace(bucket="bucket")), tmp_path / "payloads"
    )

    async def stat(key):
        return {"etag": objects[key].hex(), "size": len(objects[key]), "version_id": None} if key in objects else None

    async def get(bucket, key, **kwargs):
        return SimpleNamespace(read=AsyncMock(return_value=objects[key]), close=lambda: None)

    async def remove(bucket, key, **kwargs):
        objects.pop(key, None)

    async def listing(bucket, *, prefix, recursive):
        assert prefix == "knowledge/images/10/9/" and recursive
        for key in objects:
            if key.startswith(prefix):
                yield SimpleNamespace(object_name=key, is_dir=False)

    adapter._stat = stat
    adapter.storage._client = SimpleNamespace(get_object=get, remove_object=remove, list_objects=listing)
    request = {
        "file": {"id": 9, "object_name": "uploads/orphan.pdf"},
        "knowledge": {"id": 10, "type": 3, "index_name": "original-es", "collection_name": "original-mv"},
    }
    return adapter, request, objects, es_rows, mv_rows


async def test_backups_precede_exact_payload_deletion_and_same_plan_resume(payloads):
    adapter, item, objects, es, mv = payloads
    await adapter.capture([item], surviving_files=[{"object_name": "uploads/live.pdf"}])
    assert len(objects) == len(es) == len(mv) == 2
    assert all(path.stat().st_mode & 0o077 == 0 for path in adapter.directory.iterdir())
    await adapter.apply([item])
    await adapter.apply([item])
    assert list(objects) == ["uploads/live.pdf"] and list(es) == ["live-slice"] and list(mv) == [81]


async def test_physical_drift_blocks_before_deleting_anything(payloads):
    adapter, item, objects, es, mv = payloads
    await adapter.capture([item], surviving_files=[])
    es["orphan-slice"]["unexpected"] = "changed"
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await adapter.apply([item])
    assert len(objects) == len(es) == len(mv) == 2


async def test_shared_original_object_blocks_preview_without_deletion(payloads):
    adapter, item, objects, es, mv = payloads
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await adapter.capture([item], surviving_files=[{"object_name": "uploads/orphan.pdf"}])
    assert len(objects) == len(es) == len(mv) == 2


async def test_backup_tamper_blocks_before_effects(payloads):
    adapter, item, objects, es, mv = payloads
    await adapter.capture([item], surviving_files=[])
    (adapter.directory / item["payload_backup"]).write_bytes(b"tampered")
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await adapter.apply([item])
    assert len(objects) == len(es) == len(mv) == 2


async def test_orphan_images_are_backed_and_only_the_exact_file_prefix_is_removed(payloads):
    adapter, item, objects, _es, _mv = payloads
    objects["knowledge/images/10/9/page.png"] = b"orphan image"
    objects["knowledge/images/10/8/page.png"] = b"live image"
    await adapter.capture([item], surviving_files=[])
    await adapter.apply([item])
    assert "knowledge/images/10/9/page.png" not in objects
    assert objects["knowledge/images/10/8/page.png"] == b"live image"


async def test_new_image_after_preview_prevents_any_delete(payloads):
    adapter, item, objects, es, mv = payloads
    await adapter.capture([item], surviving_files=[])
    objects["knowledge/images/10/9/new.png"] = b"new image"
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await adapter.apply([item])
    assert len(es) == len(mv) == 2 and objects["uploads/orphan.pdf"] == b"orphan bytes"
