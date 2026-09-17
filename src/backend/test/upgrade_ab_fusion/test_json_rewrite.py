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


def test_missing_knowledge_is_dropped():
    data = {"knowledge": {"type": "knowledge", "value": [{"key": 11, "label": "gone"}]}}
    out, report = rewrite_flow_data(data, {"knowledge": {}})
    assert report.missing == []
    assert report.dropped
    assert out["knowledge"]["value"] == []


def test_knowledge_selector_keeps_node_output_refs():
    data = {
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
                                        "value": [
                                            {"key": 11, "label": "kb"},
                                            {"key": "input_53ff4.file", "label": "file"},
                                        ],
                                    },
                                }
                            ]
                        }
                    ]
                }
            }
        ]
    }
    out, report = rewrite_flow_data(data, {"knowledge": {"11": "201"}})
    keys = [item["key"] for item in out["nodes"][0]["data"]["group_params"][0]["params"][0]["value"]["value"]]
    assert keys == [201, "input_53ff4.file"]
    assert report.missing == []
    assert report.as_dict()["used"]["knowledge"] == ["11"]


def test_rewrites_recommended_llm_and_rerank_model():
    data = {
        "nodes": [
            {
                "data": {
                    "group_params": [
                        {
                            "params": [
                                {"key": "recommended_llm", "value": 3},
                                {
                                    "key": "advanced_retrieval_switch",
                                    "value": {"rerank_flag": True, "rerank_model": 4},
                                },
                            ]
                        }
                    ]
                }
            }
        ]
    }
    out, report = rewrite_flow_data(data, {"model": {"3": "9", "4": "12"}})
    params = out["nodes"][0]["data"]["group_params"][0]["params"]
    assert params[0]["value"] == 9
    assert params[1]["value"]["rerank_model"] == 12
    assert report.missing == []
    used = report.as_dict()["used"]["model"]
    assert "3" in used and "4" in used


def test_report_version_key_and_tool_key_optional_maps():
    data = {
        "report_info": {"version_key": "vk1", "file_name": "a.docx"},
        "tool_key": "web_search",
        "nodes": [{"data": {"tool_key": "tool_type_1_abc"}}],
    }
    out, report = rewrite_flow_data(
        data,
        {
            "report_version_key": {"vk1": "vk-new"},
            "tool_key": {"tool_type_1_abc": "tool_type_9_abc"},
        },
    )
    assert out["report_info"]["version_key"] == "vk-new"
    assert out["tool_key"] == "web_search"
    assert out["nodes"][0]["data"]["tool_key"] == "tool_type_9_abc"
    assert report.missing == []
