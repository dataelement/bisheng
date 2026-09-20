"""工作流/助手上线门禁."""

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.flow_publish import gate_assistant, gate_flow, generate_publish_sql

MAPS = {
    "knowledge": {"11": "201"},
    "model": {"3": "9"},
    "tool": {"5": "88"},
    "flow": {"ffff": "aabb"},
}


def _online_flow_data():
    return {
        "nodes": [
            {
                "data": {
                    "group_params": [
                        {
                            "params": [
                                {
                                    "key": "knowledge",
                                    "value": {
                                        "type": "knowledge",
                                        "value": [{"key": 11}],
                                    },
                                },
                                {"key": "model_id", "value": 3},
                            ]
                        }
                    ]
                }
            }
        ]
    }


def test_gate_flow_ok_when_refs_mapped():
    row = gate_flow(
        src_id="ffff",
        dst_id="aabb",
        desired_status=2,
        data=_online_flow_data(),
        maps=MAPS,
        gap_model_ids=set(),
        gap_tool_ids=set(),
        vector_exception_kids=set(),
    )
    assert row["ok"] is True


def test_gate_flow_blocks_vector_exception():
    row = gate_flow(
        src_id="ffff",
        dst_id="aabb",
        desired_status=2,
        data=_online_flow_data(),
        maps=MAPS,
        gap_model_ids=set(),
        gap_tool_ids=set(),
        vector_exception_kids={"11"},
    )
    assert row["ok"] is False
    assert "向量不兼容" in row["reason"]


def test_gate_flow_skips_offline():
    row = gate_flow(
        src_id="ffff",
        dst_id="aabb",
        desired_status=1,
        data=_online_flow_data(),
        maps=MAPS,
        gap_model_ids=set(),
        gap_tool_ids=set(),
        vector_exception_kids=set(),
    )
    assert row["ok"] is False
    assert "下线" in row["reason"]


def test_gate_flow_blocks_dangling_model():
    data = {"nodes": [{"data": {"group_params": [{"params": [{"key": "model_id", "value": 3}]}]}}]}
    row = gate_flow(
        src_id="ffff",
        dst_id="aabb",
        desired_status=2,
        data=data,
        maps={"model": {}, "knowledge": {}, "tool": {}, "flow": {}},
        gap_model_ids=set(),
        gap_tool_ids=set(),
        vector_exception_kids=set(),
    )
    assert row["ok"] is False
    assert "模型引用已删除" in row["reason"]


def test_gate_assistant_blocks_gap_model():
    row = gate_assistant(
        src_id="a1",
        dst_id="b1",
        desired_status=2,
        model_name="3",
        maps=MAPS,
        gap_model_ids={"3"},
    )
    assert row["ok"] is False


def test_publish_sql_only_ok_rows():
    sql = generate_publish_sql(
        batch="b1",
        flow_rows=[{"ok": True, "dst_id": "aabb"}, {"ok": False, "dst_id": "nope"}],
        assistant_rows=[{"ok": True, "dst_id": "asst1"}],
    )
    assert "UPDATE flow SET status=2 WHERE id='aabb'" in sql
    assert "nope" not in sql
    assert "UPDATE assistant SET status=2 WHERE id='asst1'" in sql
