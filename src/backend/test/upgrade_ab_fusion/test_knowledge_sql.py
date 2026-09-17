"""知识库 SQL: INSERT 新 ID, 不 UPDATE, 不碰 A 原空间."""

import pytest

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.knowledge_sql import assert_write_set_skips_a_spaces, generate_knowledge_sql, rewrite_object_key


def test_rewrite_object_key_keeps_prefix():
    assert rewrite_object_key("original/12.pdf", "90") == "original/90.pdf"
    assert rewrite_object_key("preview/12.docx", "90") == "preview/90.docx"


def test_insert_only_and_skips_a_space_ids():
    sql, kmaps, fmaps = generate_knowledge_sql(
        batch="b1",
        knowledges=[{"id": "5", "name": "库", "type": 0, "user_id": "7", "tenant_id": "1", "state": 1}],
        files=[
            {
                "id": "12",
                "knowledge_id": "5",
                "user_id": "7",
                "file_name": "a.pdf",
                "object_name": "original/12.pdf",
                "thumbnails": "thumbnails/12.jpg",
                "tenant_id": "1",
                "status": 2,
            }
        ],
        user_map={"7": "100"},
        tenant_map={"1": "1"},
        model_map={},
        a_knowledge_names={"库"},
        a_existing_ids={1, 2},
        next_knowledge_id=10,
        next_file_id=20,
        a_tenant_default="1",
        a_space_ids={3, 4},
    )
    assert "UPDATE knowledge" not in sql.upper()
    assert "INSERT INTO knowledge" in sql
    assert "[B迁移]" in sql
    assert kmaps[0]["a_id"] == "10"
    assert "b5_col_10" in sql
    assert fmaps[0]["dst_object_key"] == "original/20.pdf"
    assert any(j["dst"] == "thumbnails/20.jpg" for j in fmaps[0]["extra_jobs"])
    assert_write_set_skips_a_spaces(kmaps, {3, 4})


def test_owner_unmapped_raises():
    with pytest.raises(ValueError, match="未映射"):
        generate_knowledge_sql(
            batch="b1",
            knowledges=[{"id": "5", "name": "库", "type": 0, "user_id": "7", "tenant_id": "1"}],
            files=[],
            user_map={},
            tenant_map={"1": "1"},
            model_map={},
            a_knowledge_names=set(),
            a_existing_ids=set(),
            next_knowledge_id=10,
            next_file_id=20,
            a_tenant_default="1",
            a_space_ids=set(),
        )


def test_skip_b_space_when_flag_off():
    sql, kmaps, fmaps = generate_knowledge_sql(
        batch="b1",
        knowledges=[
            {"id": "5", "name": "库", "type": 0, "user_id": "7", "tenant_id": "1"},
            {"id": "9", "name": "空间", "type": 3, "user_id": "7", "tenant_id": "1"},
        ],
        files=[
            {"id": "1", "knowledge_id": "5", "user_id": "7", "file_name": "a.pdf", "object_name": "original/1.pdf"},
            {"id": "2", "knowledge_id": "9", "user_id": "7", "file_name": "b.pdf", "object_name": "original/2.pdf"},
        ],
        user_map={"7": "100"},
        tenant_map={"1": "1"},
        model_map={},
        a_knowledge_names=set(),
        a_existing_ids=set(),
        next_knowledge_id=10,
        next_file_id=20,
        a_tenant_default="1",
        a_space_ids={3},
        migrate_b_spaces=False,
    )
    assert len(kmaps) == 1
    assert kmaps[0]["b_id"] == "5"
    assert len(fmaps) == 1
    assert "type=3" not in sql


def test_dry_run_skips_b_spaces_without_blocking():
    from fusion.dry_run import dry_run_knowledge

    out = dry_run_knowledge(
        [
            {"id": "5", "type": 0, "user_id": "7"},
            {"id": "9", "type": 3, "user_id": "7"},
        ],
        {"7": "100"},
        {3},
        migrate_b_spaces=False,
    )
    assert out["ok"] == ["5"]
    assert out["skipped"][0]["id"] == "9"
    assert out["blocked"] == []


def test_protect_hits_a_space():
    with pytest.raises(ValueError, match="A 原空间"):
        assert_write_set_skips_a_spaces([{"a_id": "3"}], {3})


def test_skip_existing_knowledge_and_insert_new_file():
    sql, kmaps, fmaps = generate_knowledge_sql(
        batch="b1",
        knowledges=[{"id": "5", "name": "库", "type": 0, "user_id": "7", "tenant_id": "1"}],
        files=[
            {
                "id": "12",
                "knowledge_id": "5",
                "user_id": "7",
                "file_name": "old.pdf",
                "object_name": "original/12.pdf",
            },
            {
                "id": "13",
                "knowledge_id": "5",
                "user_id": "7",
                "file_name": "new.pdf",
                "object_name": "original/13.pdf",
            },
        ],
        user_map={"7": "100"},
        tenant_map={"1": "1"},
        model_map={},
        a_knowledge_names=set(),
        a_existing_ids={10},
        next_knowledge_id=11,
        next_file_id=21,
        a_tenant_default="1",
        a_space_ids={3},
        existing_knowledge={"5": "10"},
        existing_files={"12": "20"},
    )
    assert "INSERT INTO knowledge (" not in sql
    assert sql.count("INSERT INTO knowledgefile") == 1
    assert "original/21.pdf" in sql
    assert any(m["b_id"] == "5" and m["a_id"] == "10" for m in kmaps)
    assert {m["b_id"] for m in fmaps} == {"12", "13"}
    assert "UPDATE knowledge" not in sql.upper()


def test_unmapped_embedding_model_raises():
    with pytest.raises(ValueError, match="模型"):
        generate_knowledge_sql(
            batch="b1",
            knowledges=[
                {
                    "id": "5",
                    "name": "库",
                    "type": 0,
                    "user_id": "7",
                    "tenant_id": "1",
                    "model": "3",
                }
            ],
            files=[],
            user_map={"7": "100"},
            tenant_map={"1": "1"},
            model_map={},
            a_knowledge_names=set(),
            a_existing_ids=set(),
            next_knowledge_id=10,
            next_file_id=20,
            a_tenant_default="1",
            a_space_ids=set(),
        )
