"""工具分类/子工具新建并拷 api_key 与 extra."""

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.tool_type_sql import extra_sql, generate_tool_type_sql


def test_extra_sql_keeps_secrets():
    out = extra_sql('{"api_key":"k","api_location":"header"}')
    assert "k" in out
    assert "header" in out


def test_insert_copies_api_key_and_children():
    sql, maps, extra = generate_tool_type_sql(
        batch="b1",
        rows=[
            {
                "id": "4",
                "name": "搜索",
                "logo": "logo/4.png",
                "extra": '{"api_key":"secret","foo":"1"}',
                "description": "d",
                "api_key": "real-secret",
                "user_id": "7",
                "tenant_id": "1",
                "openapi_schema": "{}",
            }
        ],
        maps={"user": {"7": "100"}, "tenant": {"1": "1"}},
        a_existing_ids=set(),
        a_names={"搜索"},
        next_id=20,
        a_tenant_default="1",
        tools=[
            {
                "id": "8",
                "name": "搜一下",
                "desc": "x",
                "tool_key": "search.q",
                "type": "4",
                "extra": '{"token":"t1"}',
                "api_params": [{"name": "q"}],
                "user_id": "7",
                "tenant_id": "1",
            }
        ],
        tool_map=[
            {
                "b_tool_id": "8",
                "a_tool_id": "",
                "action": "create",
                "b_tool_key": "search.q",
                "a_tool_key": "search.q",
            }
        ],
        a_tool_ids=set(),
        a_tool_keys=set(),
        next_tool_id=30,
    )
    assert maps[0]["a_id"] == "20"
    assert "[B迁移]" in maps[0]["name"]
    assert "INSERT INTO t_gpts_tools_type" in sql
    assert "INSERT INTO t_gpts_tools " in sql
    assert "real-secret" in sql
    assert "secret" in sql
    assert "t1" in sql
    assert extra["gaps"] == []
    assert extra["tool_alloc"]["8"] == "30"
    assert any(j["dst"] == "logo/20.png" for j in maps[0]["extra_jobs"])
