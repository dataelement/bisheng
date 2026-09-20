"""llm_server / llm_model 新建并拷 config 密钥."""

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.llm_sql import generate_llm_sql


def test_create_copies_config_and_allocates():
    sql, extra = generate_llm_sql(
        batch="b1",
        servers=[
            {
                "id": "1",
                "name": "openai",
                "type": "openai",
                "config": {"openai_api_key": "sk-b"},
                "user_id": "7",
                "tenant_id": "1",
            }
        ],
        models=[
            {
                "id": "2",
                "server_id": "1",
                "name": "gpt-4",
                "model_name": "gpt-4",
                "model_type": "llm",
                "config": {"api_key": "mk-b"},
                "user_id": "7",
                "tenant_id": "1",
                "online": True,
            }
        ],
        server_map=[{"b_server_id": "1", "a_server_id": "", "action": "create"}],
        model_map=[{"b_model_id": "2", "a_model_id": "", "action": "create"}],
        user_map={"7": "100"},
        tenant_map={"1": "1"},
        a_server_ids=set(),
        a_model_ids=set(),
        a_server_names={"openai"},
        a_server_models=[],
        next_server_id=9,
        next_model_id=11,
        a_tenant_default="1",
    )
    assert "INSERT INTO llm_server" in sql
    assert "INSERT INTO llm_model" in sql
    assert "sk-b" in sql
    assert "mk-b" in sql
    assert extra["server_alloc"]["1"] == "9"
    assert extra["model_alloc"]["2"] == "11"
    assert "[B迁移]" in sql


def test_bind_does_not_insert():
    sql, extra = generate_llm_sql(
        batch="b1",
        servers=[{"id": "1", "name": "openai", "type": "openai", "config": {"k": "x"}}],
        models=[],
        server_map=[{"b_server_id": "1", "a_server_id": "3", "action": "bind"}],
        model_map=[],
        user_map={},
        tenant_map={"1": "1"},
        a_server_ids={3},
        a_model_ids=set(),
        a_server_names={"openai"},
        a_server_models=[],
        next_server_id=9,
        next_model_id=11,
        a_tenant_default="1",
    )
    assert "INSERT INTO llm_server" not in sql
    assert extra["server_alloc"]["1"] == "3"
    assert "'x'" not in sql
