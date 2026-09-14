"""收藏/置顶 SQL: 映不上跳过, 映得上才写 user_link。"""

from __future__ import annotations

from test.upgrade_ab_fusion._packutil import P5, load_module

rel = load_module("fusion_relations_sql", P5 / "relations_to_sql.py")


def test_pin_remap_and_skip_unmapped():
    sql, skipped = rel.generate_sql(
        {
            "pins": [
                {"user_id": 1, "type_detail": "10"},
                {"user_id": 2, "type_detail": "10"},
            ],
            "member_pins": [{"user_id": 1, "business_id": "10"}],
            "favorite_refs": [{"id": 8, "reference_document_id": 9}],
        },
        user_map={1: 100},
        space_map={10: 500},
        file_map={8: 80},
        doc_map={9: 90},
        batch_no="r1",
    )
    assert "knowledge_space_pin" in sql
    assert "500" in sql
    assert "user_id=100" in sql or "100," in sql
    assert "is_pinned=1" in sql
    assert "reference_document_id=90" in sql
    assert any("a_user=2" in item["detail"] for item in skipped)
