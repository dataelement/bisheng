"""回滚不得删除 bind 的 A 原对象."""

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.rollback_sql import generate_rollback_sql


def test_rollback_skips_a_spaces_and_deletes_created_only():
    sql = generate_rollback_sql(
        batch="b1",
        maps={
            "knowledge": [("5", "10")],
            "chat": [("c1", "c1")],
            "user_create": [("7", "200")],
            "role": [("9", "40")],
            "qa": [("3", "20")],
            "review_tag": [("1", "30")],
            "review_tag_link": [("11", "40")],
            "group_resource": [("8", "50")],
            "dictionary": [("2", "21")],
            "citation": [("1", "60")],
            "citation_relation": [("2", "61")],
            "mark_task": [("3", "70")],
            "mark_record": [("4", "71")],
            "mark_app_user": [("5", "72")],
            "report": [("6", "80")],
            "tool_type": [("7", "90")],
            "role_access": [("8", "91")],
        },
        a_space_ids={3, 4},
    )
    assert "DELETE FROM knowledge WHERE id IN (10)" in sql
    assert "DELETE FROM message_session WHERE chat_id IN ('c1')" in sql
    assert "DELETE FROM `user` WHERE user_id IN (200)" in sql
    assert "DELETE FROM role WHERE id IN (40)" in sql
    assert "DELETE FROM qaknowledge WHERE id IN (20)" in sql
    assert "DELETE FROM review_tag WHERE id IN (30)" in sql
    assert "DELETE FROM review_tag_link WHERE id IN (40)" in sql
    assert "DELETE FROM groupresource WHERE id IN (50)" in sql
    assert "DELETE FROM system_dictionary WHERE id IN (21)" in sql
    assert "DELETE FROM message_citation WHERE id IN (60)" in sql
    assert "DELETE FROM message_citation_relation WHERE id IN (61)" in sql
    assert "DELETE FROM marktask WHERE id IN (70)" in sql
    assert "DELETE FROM markrecord WHERE id IN (71)" in sql
    assert "DELETE FROM markappuser WHERE id IN (72)" in sql
    assert "DELETE FROM t_report WHERE id IN (80)" in sql
    assert "DELETE FROM t_gpts_tools_type WHERE id IN (90)" in sql
    assert "DELETE FROM roleaccess WHERE id IN (91)" in sql


def test_rollback_refuses_a_space_id():
    import pytest

    with pytest.raises(ValueError, match="A 原空间"):
        generate_rollback_sql(
            batch="b1",
            maps={"knowledge": [("1", "3")]},
            a_space_ids={3},
        )
