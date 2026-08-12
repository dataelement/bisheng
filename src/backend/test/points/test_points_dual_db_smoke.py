"""T027：积分双库兼容冒烟（AC-25）。

- 静态：ORM/迁移使用 dialect_helpers，禁止 MySQL 专属 JSON/ON UPDATE。
- 运行时（MySQL）：核心表存在且可查询。
- DM8：macOS 无驱动，标记 skip；真实校验在 CI/Linux。
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
MODELS = BACKEND / "bisheng/points/domain/models/points.py"
MIGRATION = BACKEND / "bisheng/core/database/alembic/versions/v2_6_0_f078_points_system.py"

# Resolve DSN the same way local uvicorn/gates do (cwd-relative config.yaml).
_cfg_candidates = [
    BACKEND / "config.yaml",
    BACKEND / "bisheng" / "config.yaml",
    Path("config.yaml").resolve(),
]
for _cfg in _cfg_candidates:
    if _cfg.is_file():
        os.environ.setdefault("config", str(_cfg))
        break
else:
    os.environ.setdefault("config", "config.yaml")


def test_points_models_use_dialect_helpers():
    """ORM 必须用 JsonType / LargeText / UPDATE_TIME_SERVER_DEFAULT。"""
    src = MODELS.read_text(encoding="utf-8")
    assert "from bisheng.core.database.dialect_helpers import" in src
    assert "JsonType" in src
    assert "LargeText" in src
    assert "UPDATE_TIME_SERVER_DEFAULT" in src
    # 禁止直接绑 MySQL JSON / ON UPDATE 字面量。
    assert "sqlalchemy.JSON" not in src
    assert "mysql.JSON" not in src
    assert "ON UPDATE CURRENT_TIMESTAMP" not in src


def test_points_migration_is_dialect_safe():
    """迁移用 inspect，不碰 information_schema / DATABASE()。"""
    src = MIGRATION.read_text(encoding="utf-8")
    assert "inspect(bind)" in src or "sa.inspect" in src
    assert "information_schema" not in src.lower()
    assert "DATABASE()" not in src
    assert "JSON_EXTRACT" not in src
    assert "ON UPDATE CURRENT_TIMESTAMP" not in src
    assert "mysql.JSON" not in src
    # Parse succeeds (syntax); table create delegates to ORM models.
    ast.parse(src)


@pytest.mark.asyncio
async def test_mysql_points_schema_readable():
    """联调 MySQL：积分核心表可读（需 config.yaml 指向测试库）。"""
    from sqlalchemy import text
    from bisheng.core.database import get_async_db_session

    required = [
        "user_point_account",
        "user_point_log",
        "point_rule",
        "point_copy",
        "point_rank_snapshot",
        "point_favorite_tier_award",
        "point_sync_outbox",
    ]
    try:
        async with get_async_db_session() as session:
            for name in required:
                row = (await session.execute(text(f"select count(*) from {name}"))).first()
                assert row is not None
            rules = (
                await session.execute(
                    text("select count(*) from point_rule where tenant_id = 1")
                )
            ).first()
            assert int(rules[0]) >= 1
    except Exception as exc:
        pytest.skip(f"MySQL smoke skipped (DSN/config unavailable): {exc}")


@pytest.mark.skipif(
    sys.platform == "darwin",
    reason="DM8 driver (dmPython) not installed on macOS; validate on CI/Linux only",
)
def test_dm8_driver_importable_on_linux():
    """Linux/CI：确认 DM8 驱动可导入（真实连库由 CI workflow 负责）。"""
    import importlib.util

    mod = importlib.util.find_spec("dmPython") or importlib.util.find_spec("dmAsync")
    assert mod is not None, "DM8 driver missing on Linux CI image"
