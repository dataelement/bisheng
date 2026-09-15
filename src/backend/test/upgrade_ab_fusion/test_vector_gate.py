"""Milvus/ES 门禁, ID 重写, 拒绝写入 A 空间 Collection."""

import json

import pytest

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.vector_gate import CONVERT, COPY, EXCEPTION, gate_knowledge, parse_dim
from fusion.vector_jobs import build_vector_jobs, generate_exception_sql
from fusion.vector_names import target_collection_name
from fusion.vector_rewrite import rewrite_entity


def _schema(dim=768, knowledge_dtype="INT64"):
    return {
        "fields": [
            {"name": "pk", "dtype": "INT64", "is_primary": True, "auto_id": True},
            {"name": "text", "dtype": "VARCHAR", "params": {"max_length": 65535}},
            {"name": "vector", "dtype": "FLOAT_VECTOR", "params": {"dim": dim}},
            {"name": "file_id", "dtype": "INT64"},
            {"name": "document_id", "dtype": "INT64"},
            {"name": "knowledge_id", "dtype": knowledge_dtype},
        ],
        "indexes": [{"field": "vector", "index_type": "HNSW", "metric_type": "L2"}],
    }


def _es():
    return {"mappings": {"properties": {"text": {"type": "text"}}}}


def test_prefix_avoids_a_name():
    assert target_collection_name("5", "col_1", "10") == "b5_col_1"


def test_rewrite_ids_and_image_path():
    out = rewrite_entity(
        {
            "pk": 9,
            "file_id": 12,
            "document_id": 12,
            "knowledge_id": 5,
            "tenant_id": 1,
            "text": "见图 knowledge/images/files/12/a.png 和 original/12.pdf",
            "vector": [0.1, 0.2],
            "extra": json.dumps({"file_id": 12, "knowledge_id": 5}),
        },
        file_map={"12": "20"},
        knowledge_map={"5": "10"},
        tenant_map={"1": "1"},
        field_types={"file_id": "INT64", "knowledge_id": "INT64"},
    )
    assert "pk" not in out
    assert out["file_id"] == 20
    assert out["document_id"] == 20
    assert out["knowledge_id"] == 10
    assert "knowledge/images/files/20/a.png" in out["text"]
    assert "original/20.pdf" in out["text"]
    extra = json.loads(out["extra"])
    assert extra["file_id"] == 20
    assert extra["knowledge_id"] == 10


def test_rewrite_nested_es_and_varchar_knowledge_id():
    out = rewrite_entity(
        {
            "text": "qa",
            "metadata": {"file_id": 12, "knowledge_id": "5"},
            "vector": [0.1],
        },
        file_map={"12": "20"},
        knowledge_map={"5": "10"},
        tenant_map={},
        field_types={"knowledge_id": "VARCHAR"},
    )
    assert out["metadata"]["file_id"] == 20
    assert out["metadata"]["knowledge_id"] == "10"


def test_unmapped_file_raises():
    with pytest.raises(ValueError, match="未映射"):
        rewrite_entity(
            {"file_id": 99, "text": "x", "vector": [0.1]},
            file_map={"12": "20"},
            knowledge_map={"5": "10"},
            tenant_map={},
        )


def test_gate_copy_when_compatible():
    result = gate_knowledge(
        src_id="5",
        dst_id="10",
        ktype=0,
        b_collection="col_5",
        b_index="idx_5",
        b_model="3",
        a_model="9",
        b_schema=_schema(),
        b_es=_es(),
        a_collections={"col_a"},
        a_indices={"idx_a"},
        a_space_collections={"col_space_1"},
        a_space_indices={"idx_space_1"},
        b_model_dim=768,
        a_model_dim=768,
        described=True,
    )
    assert result["verdict"] in {COPY, CONVERT}
    assert result["a_collection"] == "b5_col_5"
    assert "knowledge_id_filter" in result["conversions"]


def test_gate_dim_mismatch_need_reparse():
    result = gate_knowledge(
        src_id="5",
        dst_id="10",
        ktype=0,
        b_collection="col_5",
        b_index="idx_5",
        b_model="3",
        a_model="9",
        b_schema=_schema(dim=1024),
        b_es=_es(),
        a_collections=set(),
        a_indices=set(),
        a_space_collections=set(),
        a_space_indices=set(),
        b_model_dim=1024,
        a_model_dim=768,
        described=True,
    )
    assert result["verdict"] == EXCEPTION
    assert result["disposition"] == "need_reparse"


def test_gate_refuses_a_space_dest_name():
    result = gate_knowledge(
        src_id="5",
        dst_id="10",
        ktype=0,
        b_collection="col_space_1",
        b_index="idx_5",
        b_model="3",
        a_model="9",
        b_schema=_schema(),
        b_es=_es(),
        a_collections=set(),
        a_indices=set(),
        a_space_collections={"b5_col_space_1", "col_space_1"},
        a_space_indices=set(),
        b_model_dim=768,
        a_model_dim=768,
        described=True,
    )
    assert result["verdict"] == EXCEPTION
    assert "空间" in result["reason"]


def test_gate_unmapped_model():
    result = gate_knowledge(
        src_id="5",
        dst_id="10",
        ktype=0,
        b_collection="col_5",
        b_index="idx_5",
        b_model="3",
        a_model=None,
        b_schema=_schema(),
        b_es=_es(),
        a_collections=set(),
        a_indices=set(),
        a_space_collections=set(),
        a_space_indices=set(),
        b_model_dim=None,
        a_model_dim=None,
        described=True,
    )
    assert result["verdict"] == EXCEPTION


def test_build_jobs_skips_b_space_and_writes_exception_sql():
    schema = _schema()
    jobs, exc = build_vector_jobs(
        batch="b1",
        knowledges=[
            {
                "id": "5",
                "type": 0,
                "collection_name": "col_5",
                "index_name": "idx_5",
                "model": "3",
            },
            {
                "id": "9",
                "type": 3,
                "collection_name": "col_space",
                "index_name": "idx_space",
                "model": "3",
            },
        ],
        knowledge_map={"5": "10", "9": "99"},
        model_map={"3": "9"},
        b_describe={"collections": {"col_5": schema}, "indices": {"idx_5": _es()}},
        a_describe={"collections": {}, "indices": {}},
        a_space_collections={"col_space_1"},
        a_space_indices={"idx_space_1"},
        a_existing_collections=set(),
        a_existing_indices=set(),
        b_model_dims={"3": 768},
        a_model_dims={"9": 768},
        described=True,
    )
    assert len(jobs) == 1
    assert jobs[0]["a_collection"] == "b5_col_5"
    sql = generate_exception_sql("b1", exc)
    assert "INSERT INTO fusion_exception" not in sql or exc == []


def test_conflict_existing_dest_is_exception():
    jobs, exc = build_vector_jobs(
        batch="b1",
        knowledges=[
            {
                "id": "5",
                "type": 0,
                "collection_name": "col_5",
                "index_name": "idx_5",
                "model": "3",
            }
        ],
        knowledge_map={"5": "10"},
        model_map={"3": "9"},
        b_describe={
            "collections": {"col_5": _schema()},
            "indices": {"idx_5": _es()},
        },
        a_describe={"collections": {"b5_col_5": {}}, "indices": {}},
        a_space_collections=set(),
        a_space_indices=set(),
        a_existing_collections=set(),
        a_existing_indices=set(),
        b_model_dims={},
        a_model_dims={},
        described=True,
    )
    assert jobs == []
    assert exc[0]["disposition"] == "need_reparse"


def test_parse_dim():
    assert parse_dim({"dimensions": 768}) == 768
    assert parse_dim('{"dim": 1024}') == 1024
