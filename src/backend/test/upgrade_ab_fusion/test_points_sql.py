"""积分 SQL: A 规则覆盖, 账户按映射改写, 未映射跳过。"""

from __future__ import annotations

from test.upgrade_ab_fusion._packutil import P4, load_module

points = load_module("fusion_points_sql", P4 / "points_to_sql.py")


def test_rule_overwrite_and_skip_unmapped_user():
    payload = {
        "rules": [
            {
                "tenant_id": 1,
                "rule_code": "G1",
                "rule_type": "earn",
                "name": "A规则",
                "display_name": "A展示",
                "score_expr": {"const": 3},
                "status": "enabled",
                "sort_order": 1,
            }
        ],
        "accounts": [
            {"tenant_id": 1, "user_id": 10, "balance": 5, "lifetime_earned": 5, "lifetime_deducted": 0},
            {"tenant_id": 1, "user_id": 99, "balance": 1, "lifetime_earned": 1, "lifetime_deducted": 0},
        ],
        "logs": [
            {
                "tenant_id": 1,
                "user_id": 10,
                "delta": 5,
                "balance_after": 5,
                "direction": "earn",
                "title": "G1",
                "source": "auto",
                "idempotency_key": "old-key",
                "occurred_at": "2026-01-01 00:00:00",
            }
        ],
    }
    sql, skipped = points.generate_sql(payload, {10: 200}, "b1")
    assert "ON DUPLICATE KEY UPDATE" in sql
    assert "display_name=VALUES(display_name)" in sql
    assert "user_id, 200" in sql.replace("\n", " ") or "200," in sql
    assert "fm:b1:old-key" in sql
    assert any(item["a_user_id"] == 99 for item in skipped)
    assert "(1, 99" not in sql


def test_idempotency_truncated_when_too_long():
    key = "k" * 200
    out = points.remap_idempotency("batch", key)
    assert len(out) <= 128
    assert out.startswith("fm:batch:")
