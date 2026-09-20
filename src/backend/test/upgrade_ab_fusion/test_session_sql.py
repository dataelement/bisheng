"""会话 chat_id 冲突与消息顺序."""

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.session_sql import generate_session_sql, pick_chat_id


def test_keep_chat_id_when_free():
    dst, action = pick_chat_id("c1", set(), False)
    assert dst == "c1"
    assert action == "keep"


def test_new_chat_id_when_conflict_different_content():
    dst, action = pick_chat_id("c1", {"c1"}, False)
    assert dst != "c1"
    assert action == "new_id"


def test_dedupe_when_digest_matches():
    sql, smaps, mmaps, _ex = generate_session_sql(
        batch="b1",
        sessions=[
            {"chat_id": "c1", "user_id": "7", "digest": "abc", "flow_id": "f1", "flow_type": 10, "group_ids": []}
        ],
        messages=[{"id": "1", "chat_id": "c1", "user_id": "7", "type": "text", "category": "question"}],
        maps={"user": {"7": "100"}, "flow": {"f1": "f1"}, "tenant": {"1": "1"}, "group": {}},
        a_chat_ids={"c1"},
        a_session_digest={"c1": "abc"},
        next_message_id=50,
        a_tenant_default="1",
    )
    assert smaps[0]["action"] == "dedupe"
    assert "INSERT INTO message_session" not in sql
    assert mmaps == []


def test_insert_messages_preserve_src_order_with_new_ids():
    sql, smaps, mmaps, _ex = generate_session_sql(
        batch="b1",
        sessions=[{"chat_id": "c9", "user_id": "7", "flow_id": "f1", "flow_type": 10, "group_ids": "[2]"}],
        messages=[
            {"id": "20", "chat_id": "c9", "user_id": "7", "type": "t", "category": "q", "message": "second"},
            {
                "id": "10",
                "chat_id": "c9",
                "user_id": "7",
                "type": "t",
                "category": "q",
                "message": "first",
                "files": [{"filepath": "chat/10.png"}],
            },
        ],
        maps={"user": {"7": "100"}, "flow": {"f1": "aabb"}, "tenant": {"1": "1"}, "group": {"2": "8"}},
        a_chat_ids=set(),
        a_session_digest={},
        next_message_id=50,
        a_tenant_default="1",
    )
    assert smaps[0]["action"] == "keep"
    assert mmaps[0]["b_id"] == "10"
    assert mmaps[0]["a_id"] == "50"
    assert mmaps[1]["b_id"] == "20"
    assert "first" in sql
    pos_first = sql.index("first")
    pos_second = sql.index("second")
    assert pos_first < pos_second
    assert "chat/50.png" in sql
    assert mmaps[0]["extra_jobs"]


def test_skip_existing_chat_inserts_new_message():
    sql, smaps, mmaps, _ex = generate_session_sql(
        batch="b1",
        sessions=[{"chat_id": "c9", "user_id": "7", "flow_id": "f1", "flow_type": 10, "group_ids": []}],
        messages=[
            {"id": "10", "chat_id": "c9", "user_id": "7", "type": "t", "category": "q", "message": "old"},
            {"id": "11", "chat_id": "c9", "user_id": "7", "type": "t", "category": "q", "message": "new"},
        ],
        maps={
            "user": {"7": "100"},
            "flow": {"f1": "aabb"},
            "tenant": {"1": "1"},
            "group": {},
            "chat": {"c9": "c9"},
            "message": {"10": "50"},
        },
        a_chat_ids={"c9"},
        a_session_digest={},
        next_message_id=51,
        a_tenant_default="1",
    )
    assert "INSERT INTO message_session" not in sql
    assert "new" in sql
    assert "old" not in sql
    assert smaps[0]["action"] == "keep"
    assert {m["b_id"] for m in mmaps} == {"10", "11"}


def test_unmapped_group_ids_dropped_and_listed():
    sql, smaps, _mmaps, ex = generate_session_sql(
        batch="b1",
        sessions=[
            {
                "chat_id": "c9",
                "user_id": "7",
                "flow_id": "f1",
                "flow_type": 10,
                "group_ids": [2, 99],
            }
        ],
        messages=[],
        maps={
            "user": {"7": "100"},
            "flow": {"f1": "aabb"},
            "tenant": {"1": "1"},
            "group": {"2": "8"},
        },
        a_chat_ids=set(),
        a_session_digest={},
        next_message_id=50,
        a_tenant_default="1",
    )
    assert "INSERT INTO message_session" in sql
    assert smaps[0]["action"] == "keep"
    assert len(ex) == 1
    assert ex[0]["dropped_group_ids"] == "99"
    assert "dropped group_ids 99" in sql


def test_skips_existing_a_message_primary_keys():
    sql, _smaps, mmaps, _ex = generate_session_sql(
        batch="b1",
        sessions=[{"chat_id": "c9", "user_id": "7", "flow_id": "f1", "flow_type": 10, "group_ids": []}],
        messages=[{"id": "10", "chat_id": "c9", "user_id": "7", "type": "t", "category": "q", "message": "hi"}],
        maps={"user": {"7": "100"}, "flow": {"f1": "aabb"}, "tenant": {"1": "1"}, "group": {}},
        a_chat_ids=set(),
        a_session_digest={},
        next_message_id=50,
        a_tenant_default="1",
        a_existing_message_ids={50},
    )
    assert mmaps[0]["a_id"] == "51"
    assert "INSERT INTO chatmessage (id" in sql
    assert (
        sql.split("INSERT INTO chatmessage")[1].startswith(" (id, is_bot")
        or "VALUES (51," in sql.split("INSERT INTO chatmessage", 1)[1]
    )
    assert "VALUES (51," in sql
