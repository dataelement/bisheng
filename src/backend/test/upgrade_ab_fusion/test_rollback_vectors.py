"""回滚向量名单: 含 skip 留下的旧 Collection, 不碰 A 原空间名."""

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.rollback_vectors import collect_rollback_vector_stores
from fusion.vector_names import target_collection_name, target_index_name


def _names(rows: list[dict], kind: str) -> set[str]:
    return {r["name"] for r in rows if r["kind"] == kind}


def test_snapshot_includes_skip_leftover_and_split_es_name():
    rows = collect_rollback_vector_stores(
        knowledge_stores=[
            {
                "id": "3842",
                "collection_name": "b7_col_1746682905_f4d79537_new",
                "index_name": "b7_col_1746682905_f4d79537_new",
            },
            {
                "id": "3838",
                "collection_name": "b3_partition_1_knowledge_1",
                "index_name": "b3_col_1745483532_b9d61fd4",
            },
        ]
    )
    assert "b7_col_1746682905_f4d79537_new" in _names(rows, "milvus")
    assert "b7_col_1746682905_f4d79537_new" in _names(rows, "es")
    assert "b3_partition_1_knowledge_1" in _names(rows, "milvus")
    assert "b3_col_1745483532_b9d61fd4" in _names(rows, "es")
    assert "b3_partition_1_knowledge_1" not in _names(rows, "es")


def test_vector_jobs_skip_used_when_mysql_already_gone():
    rows = collect_rollback_vector_stores(
        knowledge_stores=[],
        vector_jobs=[
            {
                "b_id": "7",
                "verdict": "skip",
                "a_collection": "b7_col_1746682905_f4d79537_new",
                "a_index": "b7_col_1746682905_f4d79537_new",
            },
            {
                "b_id": "99",
                "verdict": "exception",
                "a_collection": "should_not_drop",
                "a_index": "should_not_drop_es",
            },
        ],
    )
    assert _names(rows, "milvus") == {"b7_col_1746682905_f4d79537_new"}
    assert "should_not_drop" not in _names(rows, "milvus")


def test_forbid_drops_a_space_store_even_if_snapshot_has_it():
    rows = collect_rollback_vector_stores(
        knowledge_stores=[
            {"id": "3", "collection_name": "a_space_col", "index_name": "a_space_idx"},
            {"id": "3840", "collection_name": "b5_col_x", "index_name": "b5_col_x"},
        ],
        forbid={"a_space_col", "a_space_idx"},
    )
    assert _names(rows, "milvus") == {"b5_col_x"}
    assert "a_space_col" not in _names(rows, "milvus")


def test_reconstruct_from_b_name_when_jobs_missing():
    rows = collect_rollback_vector_stores(
        knowledge_maps=[{"b_id": "7", "a_id": "3842", "action": "create"}],
        b_knowledges=[
            {
                "id": "7",
                "collection_name": "col_1746682905_f4d79537_new",
                "index_name": "col_1746682905_f4d79537_new",
            }
        ],
    )
    expect = target_collection_name("7", "col_1746682905_f4d79537_new", "3842")
    assert expect == "b7_col_1746682905_f4d79537_new"
    assert expect in _names(rows, "milvus")
    assert target_index_name("7", "col_1746682905_f4d79537_new", "3842") in _names(rows, "es")


def test_bind_knowledge_map_not_reconstructed():
    rows = collect_rollback_vector_stores(
        knowledge_maps=[
            {
                "b_id": "1",
                "a_id": "3",
                "action": "bind",
                "a_collection": "original_a_col",
            }
        ]
    )
    assert rows == []


def test_knowledge_map_without_store_names_does_not_invent():
    rows = collect_rollback_vector_stores(knowledge_maps=[{"b_id": "7", "a_id": "3842", "action": "create"}])
    assert rows == []


def test_dedup_snapshot_and_jobs():
    rows = collect_rollback_vector_stores(
        knowledge_stores=[{"id": "3842", "collection_name": "b7_col_x", "index_name": "b7_col_x"}],
        vector_jobs=[
            {
                "b_id": "7",
                "verdict": "skip",
                "a_collection": "b7_col_x",
                "a_index": "b7_col_x",
            }
        ],
        vector_created=[{"kind": "milvus", "name": "b7_col_x", "b_id": "7"}],
    )
    milvus = [r for r in rows if r["kind"] == "milvus"]
    assert len(milvus) == 1
    assert milvus[0]["source"] == "knowledge_snapshot"
