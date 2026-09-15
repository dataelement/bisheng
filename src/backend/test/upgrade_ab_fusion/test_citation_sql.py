"""消息引用重写 message_id, citation_id 换新."""

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.citation_sql import generate_citation_sql


def test_rewrites_message_and_new_citation_id():
    sql, cmaps, rmaps = generate_citation_sql(
        batch="b1",
        citations=[
            {
                "id": "1",
                "citation_id": "old-cid",
                "message_id": "10",
                "chat_id": "c1",
                "flow_id": "f1",
                "citation_type": "file",
                "source_payload": {"knowledge_id": 5},
            }
        ],
        relations=[{"id": "2", "message_id": "10", "citation_id": "old-cid", "tenant_id": "1"}],
        maps={
            "message": {"10": "50"},
            "chat": {"c1": "c1"},
            "flow": {"f1": "aabb"},
            "knowledge": {"5": "10"},
            "tenant": {"1": "1"},
        },
        a_citation_ids={"old-cid"},
        a_citation_pks={1},
        a_relation_ids=set(),
        next_citation_id=8,
        next_relation_id=9,
        a_tenant_default="1",
    )
    assert "INSERT INTO message_citation" in sql
    assert "INSERT INTO message_citation_relation" in sql
    assert cmaps[0]["a_id"] == "8"
    assert cmaps[0]["citation_id"] != "old-cid"
    assert rmaps[0]["a_id"] == "9"
    assert "50" in sql
    assert "'aabb'" in sql


def test_skips_unmapped_message():
    sql, cmaps, rmaps = generate_citation_sql(
        batch="b1",
        citations=[{"id": "1", "citation_id": "x", "message_id": "99"}],
        relations=[],
        maps={"message": {}, "chat": {}, "flow": {}, "tenant": {"1": "1"}},
        a_citation_ids=set(),
        a_citation_pks=set(),
        a_relation_ids=set(),
        next_citation_id=1,
        next_relation_id=1,
        a_tenant_default="1",
    )
    assert cmaps == []
    assert rmaps == []
    assert "INSERT INTO message_citation (" not in sql
