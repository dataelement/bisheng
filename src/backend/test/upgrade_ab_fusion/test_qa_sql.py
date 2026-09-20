"""QA 问答对只跟已映射传统库走."""

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.qa_sql import generate_qa_sql


def test_inserts_mapped_qa_and_skips_unmapped_knowledge():
    sql, maps = generate_qa_sql(
        batch="b1",
        qas=[
            {
                "id": "3",
                "knowledge_id": "5",
                "user_id": "7",
                "questions": ["q1"],
                "answers": "a1",
                "tenant_id": "1",
            },
            {"id": "4", "knowledge_id": "9", "user_id": "7", "questions": ["x"]},
        ],
        knowledge_map={"5": "10"},
        user_map={"7": "100"},
        tenant_map={"1": "1"},
        a_existing_ids={1},
        next_qa_id=20,
        a_tenant_default="1",
    )
    assert "INSERT INTO qaknowledge" in sql
    assert maps[0]["a_id"] == "20"
    assert "knowledge 5->10" in sql
    assert len(maps) == 1
    assert "id=4" not in sql


def test_unmapped_user_raises():
    import pytest

    with pytest.raises(ValueError, match="未映射"):
        generate_qa_sql(
            batch="b1",
            qas=[{"id": "3", "knowledge_id": "5", "user_id": "7", "questions": ["q"]}],
            knowledge_map={"5": "10"},
            user_map={},
            tenant_map={"1": "1"},
            a_existing_ids=set(),
            next_qa_id=1,
            a_tenant_default="1",
        )


def test_skip_existing_qa():
    sql, maps = generate_qa_sql(
        batch="b1",
        qas=[
            {
                "id": "3",
                "knowledge_id": "5",
                "user_id": "7",
                "questions": ["q1"],
                "answers": "a1",
                "tenant_id": "1",
            },
            {
                "id": "4",
                "knowledge_id": "5",
                "user_id": "7",
                "questions": ["q2"],
                "answers": "a2",
                "tenant_id": "1",
            },
        ],
        knowledge_map={"5": "10"},
        user_map={"7": "100"},
        tenant_map={"1": "1"},
        a_existing_ids={20},
        next_qa_id=21,
        a_tenant_default="1",
        existing_qa={"3": "20"},
    )
    assert sql.count("INSERT INTO qaknowledge") == 1
    assert maps[0]["a_id"] == "20"
    assert any(m["b_id"] == "4" and m["a_id"] == "21" for m in maps)
