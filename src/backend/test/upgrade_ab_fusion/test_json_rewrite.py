"""JSON 白名单重写, 不做全文替换."""

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.json_rewrite import rewrite_flow_data


def test_rewrites_knowledge_selector_and_model_id():
    data = {
        "nodes": [
            {
                "data": {
                    "group_params": [
                        {
                            "params": [
                                {
                                    "key": "knowledge",
                                    "value": {"type": "knowledge", "value": [{"key": 11, "label": "kb"}]},
                                },
                                {"key": "model_id", "value": 3},
                            ]
                        }
                    ]
                }
            }
        ],
        "edges": [],
    }
    maps = {"knowledge": {"11": "201"}, "model": {"3": "9"}}
    out, report = rewrite_flow_data(data, maps)
    params = out["nodes"][0]["data"]["group_params"][0]["params"]
    assert params[0]["value"]["value"][0]["key"] == 201
    assert params[1]["value"] == 9
    assert report.missing == []
    used = report.as_dict()["used"]
    assert used["knowledge"] == ["11"]
    assert used["model"] == ["3"]


def test_does_not_replace_id_inside_unrelated_text():
    data = {"nodes": [{"data": {"note": "see knowledge 11"}}], "edges": []}
    out, report = rewrite_flow_data(data, {"knowledge": {"11": "201"}})
    assert out["nodes"][0]["data"]["note"] == "see knowledge 11"
    assert report.rewritten == []


def test_tool_list_keys():
    data = {"tool_list": [{"key": 5, "label": "t"}]}
    out, report = rewrite_flow_data(data, {"tool": {"5": "88"}})
    assert out["tool_list"][0]["key"] == 88
    assert report.missing == []
    assert report.as_dict()["used"]["tool"] == ["5"]


def test_missing_knowledge_is_reported():
    data = {"knowledge": {"type": "knowledge", "value": [{"key": 11}]}}
    _, report = rewrite_flow_data(data, {"knowledge": {}})
    assert report.missing
