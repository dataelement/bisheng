"""传统库标签新建, 跳过空间文件和未映射资源."""

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.tag_sql import generate_tag_sql


def test_creates_tag_for_mapped_file_skips_space_file():
    sql, tmaps, lmaps = generate_tag_sql(
        batch="b1",
        tags=[
            {
                "id": "1",
                "name": "合同",
                "business_type": "knowledge",
                "business_id": "5",
                "user_id": "7",
                "tenant_id": "1",
                "resource_type": "manual_tag",
            },
            {
                "id": "2",
                "name": "空间标签",
                "business_type": "knowledge_space",
                "business_id": "9",
                "user_id": "7",
            },
        ],
        links=[
            {
                "id": "11",
                "tag_id": "1",
                "resource_id": "12",
                "resource_type": 9,
                "user_id": "7",
            },
            {
                "id": "12",
                "tag_id": "2",
                "resource_id": "99",
                "resource_type": 8,
                "user_id": "7",
            },
        ],
        maps={
            "user": {"7": "100"},
            "tenant": {"1": "1"},
            "knowledge": {"5": "10"},
            "file": {"12": "20"},
        },
        a_tag_ids=set(),
        a_link_ids=set(),
        next_tag_id=30,
        next_link_id=40,
        a_tenant_default="1",
    )
    assert "INSERT INTO review_tag" in sql
    assert "INSERT INTO review_tag_link" in sql
    assert tmaps[0]["a_id"] == "30"
    assert lmaps[0]["a_id"] == "40"
    assert "空间标签" not in sql
    assert len(tmaps) == 1
    assert len(lmaps) == 1
