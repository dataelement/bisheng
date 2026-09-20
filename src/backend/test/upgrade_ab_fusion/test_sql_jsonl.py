"""jsonl 加载跳过 mysql 客户端 warning 行."""

from pathlib import Path

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.sql import load_jsonl


def test_load_jsonl_skips_mysql_warning(tmp_path: Path):
    p = tmp_path / "rows.jsonl"
    p.write_text(
        'mysql: [Warning] Using a password on the command line interface can be insecure.\n{"id": 1, "name": "ok"}\n\n',
        encoding="utf-8",
    )
    rows = load_jsonl(p)
    assert rows == [{"id": 1, "name": "ok"}]
