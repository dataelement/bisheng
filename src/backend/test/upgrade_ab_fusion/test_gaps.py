"""从已签字 map 和 propose conflict 收集缺口. bind/create 不算缺口."""

from pathlib import Path

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.gaps import collect_gaps


def test_collects_manual_and_skips_bind(tmp_path: Path):
    (tmp_path / "model-map.csv").write_text(
        "b_model_id,a_model_id,action\n1,9,bind\n2,,manual\n9,,create\n",
        encoding="utf-8",
    )
    (tmp_path / "tool-map.csv").write_text(
        "b_tool_id,a_tool_id,action\n3,8,bind\n",
        encoding="utf-8",
    )
    (tmp_path / "model-map.manual.csv").write_text(
        "b_model_id,reason\n4,A 无同名\n",
        encoding="utf-8",
    )
    rows = collect_gaps(tmp_path, tmp_path)
    ids = {(r["kind"], r["b_id"]) for r in rows}
    assert ("model", "2") in ids
    assert ("model", "4") in ids
    assert ("model", "1") not in ids
    assert ("model", "9") not in ids
    assert ("tool", "3") not in ids
