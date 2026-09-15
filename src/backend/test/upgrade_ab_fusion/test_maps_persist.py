"""后序域依赖前序映射 csv."""

from pathlib import Path

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.maps import load_map, persist_runtime_maps


def test_persist_knowledge_then_flow_can_read(tmp_path: Path):
    persist_runtime_maps(
        tmp_path,
        {"knowledge_maps": [{"b_id": "5", "a_id": "10"}], "file_maps": [{"b_id": "12", "a_id": "20"}]},
    )
    assert load_map(tmp_path / "knowledge-map.csv", "b_id", "a_id")["5"] == "10"
    persist_runtime_maps(
        tmp_path,
        {
            "flow_maps": [{"b_id": "ffff", "a_id": "aabb"}],
            "flowversion_maps": [{"b_id": "1", "a_id": "8"}],
        },
    )
    assert load_map(tmp_path / "flow-map.csv", "b_id", "a_id")["ffff"] == "aabb"
    assert load_map(tmp_path / "flowversion-map.csv", "b_id", "a_id")["1"] == "8"
    assert load_map(tmp_path / "knowledge-map.csv", "b_id", "a_id")["5"] == "10"


def test_fill_user_create_ids_keeps_bind_rows(tmp_path: Path):
    p = tmp_path / "user-map.csv"
    p.write_text(
        "b_user_id,a_user_id,action\n7,100,bind\n8,,create\n",
        encoding="utf-8",
    )
    persist_runtime_maps(tmp_path, {"user_alloc": {"8": "200", "7": "100"}})
    text = p.read_text(encoding="utf-8")
    assert "8,200,create" in text
    assert "7,100,bind" in text


def test_fill_dept_as_group_id(tmp_path: Path):
    p = tmp_path / "dept-map.csv"
    p.write_text(
        "b_dept_pk,a_dept_pk,a_group_id,action\n3,,,as_group\n",
        encoding="utf-8",
    )
    persist_runtime_maps(tmp_path, {"dept_as_group": {"3": "88"}})
    assert "88" in p.read_text(encoding="utf-8")
