from bisheng.common.constants.telemetry import KNOWLEDGE_SPACE_CONTENT_STAT_INDEX
from bisheng.telemetry.domain.mid_table.knowledge_space_content import KnowledgeSpaceContentRecord
from bisheng.telemetry_search.domain.init_dataset import DASHBOARD_DATASET


def _dataset_schema() -> dict:
    dataset = next(item for item in DASHBOARD_DATASET if item.dataset_code == KNOWLEDGE_SPACE_CONTENT_STAT_INDEX)
    return dataset.schema_config


def test_knowledge_space_content_dataset_exposes_new_organization_dimensions_only():
    dimensions = {item["field"]: item["name"] for item in _dataset_schema()["dimensions"]}

    assert {
        "uploader_company_name": "上传人公司",
        "uploader_department_name": "上传人部门",
        "uploader_office_name": "上传人科室",
        "uploader_squad_name": "上传人班组",
        "belonging_company_name": "所属公司",
        "belonging_department_name": "所属部门",
        "belonging_office_name": "所属科室",
        "belonging_squad_name": "所属班组",
    }.items() <= dimensions.items()
    assert not {
        "primary_department_id",
        "primary_department_name",
        "space_department_id",
        "space_department_name",
        "uploader_department_infos.department_id",
        "uploader_department_infos.department_name",
    }.intersection(dimensions)


def test_knowledge_space_content_dataset_favorite_metric_uses_daily_projection():
    metrics = {item["field"]: item for item in _dataset_schema()["metrics"]}
    favorite = metrics["favorite_count"]

    assert favorite["name"] == "收藏次数"
    assert favorite["filter"]["filters"][0] == {
        "operator": "term",
        "field": "record_type",
        "value": "favorite_daily",
    }
    assert favorite["aggregations"] == [
        {
            "name": "favorite_count",
            "type": "sum",
            "field": "favorite_count",
            "custom_params": None,
            "time_interval": None,
            "aggs": None,
        }
    ]


def test_knowledge_space_content_dataset_exposes_single_query_time_contribution_ratio():
    metrics = {item["field"]: item for item in _dataset_schema()["metrics"]}
    field = "knowledge_contribution_ratio"
    metric = metrics[field]

    assert metric["name"] == "知识贡献占比"
    assert metric["is_virtual"] is True
    assert metric["calculation"] == "share_of_total"
    assert "share_dimension_hierarchy" not in metric
    assert metric["default_number_format"] == {
        "type": "percent",
        "decimalPlaces": 1,
        "thousandSeparator": False,
    }
    assert metric["filter"]["filters"] == [
        {"operator": "term", "field": "record_type", "value": "file"},
        {"operator": "term", "field": "file_type", "value": 1},
        {
            "operator": "terms",
            "field": "space_level",
            "value": ["public", "department", "team", "team_ks", "personal"],
        },
    ]
    assert metric["aggregations"] == [
        {
            "name": field,
            "type": "value_count",
            "field": "file_id",
            "custom_params": None,
            "time_interval": None,
            "aggs": None,
        }
    ]
    assert not {
        "uploader_knowledge_contribution_ratio",
        "belonging_knowledge_contribution_ratio",
    }.intersection(metrics)
    assert field not in KnowledgeSpaceContentRecord.model_fields
