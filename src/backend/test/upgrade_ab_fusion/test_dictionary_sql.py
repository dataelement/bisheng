"""字典同键 bind, 新键 create, 不改 A 已有值."""

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.dictionary_sql import generate_dictionary_sql


def test_bind_existing_and_create_new():
    sql, maps = generate_dictionary_sql(
        batch="b1",
        b_rows=[
            {
                "id": "1",
                "type": "expert_major",
                "dict_key": "steel",
                "dict_value": "B值",
                "tenant_id": "1",
            },
            {
                "id": "2",
                "type": "expert_major",
                "dict_key": "newkey",
                "dict_value": "新",
                "tenant_id": "1",
            },
        ],
        a_rows=[{"id": "9", "type": "expert_major", "dict_key": "steel", "tenant_id": "1"}],
        tenant_map={"1": "1"},
        a_existing_ids={9},
        next_id=20,
        a_tenant_default="1",
    )
    assert any(r["action"] == "bind" and r["a_id"] == "9" for r in maps)
    assert any(r["action"] == "create" and r["a_id"] == "20" for r in maps)
    assert "UPDATE system_dictionary" not in sql
    assert "B值" not in sql
    assert "INSERT INTO system_dictionary" in sql
    assert "'newkey'" in sql
