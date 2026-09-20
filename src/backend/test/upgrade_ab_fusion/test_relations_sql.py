"""分享链接在 A 重新生成 token, 不复制密钥."""

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.relations_sql import generate_relations_sql


def test_share_link_has_token_and_mode():
    sql, _smaps = generate_relations_sql(
        batch="b1",
        user_links=[],
        share_links=[
            {
                "id": "old",
                "resource_id": "ffff",
                "resource_type": "workflow",
                "create_user_id": "7",
                "share_mode": "read_only",
            }
        ],
        maps={"user": {"7": "100"}, "flow": {"ffff": "aabb"}, "tenant": {"1": "1"}},
        a_tenant_default="1",
    )
    assert "share_token" in sql
    assert "share_mode" in sql
    assert "INSERT INTO share_link" in sql
    assert "access_count" in sql
    assert "old" in sql
    assert "aabb" in sql
