"""工具分类新建且清空 api_key, 不写子工具."""

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.tool_type_sql import generate_tool_type_sql, redact_extra


def test_redact_extra_drops_secrets():
    out = redact_extra('{"api_key":"k","api_location":"header"}')
    assert "k" not in out
    assert "header" in out


def test_insert_clears_api_key_and_suffixes_name():
    sql, maps, gaps = generate_tool_type_sql(
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
    )
    assert maps[0]["a_id"] == "20"
    assert "[B迁移]" in maps[0]["name"]
    assert "INSERT INTO t_gpts_tools_type" in sql
    assert "INSERT INTO t_gpts_tools " not in sql
    assert "real-secret" not in sql
    assert "secret" not in sql
    assert gaps and gaps[0]["reason"].startswith("api_key")
    assert any(j["dst"] == "logo/20.png" for j in maps[0]["extra_jobs"])
