from types import SimpleNamespace

from bisheng.telemetry.domain.mid_table.belonging_organization import (
    apply_belonging_names,
    belonging_names,
    belonging_terms_missing,
    merge_belonging_backfill,
    qa_belonging_names,
)
from bisheng.telemetry.domain.mid_table.daily_participation import merge_participation_document
from bisheng.telemetry_search.domain.init_dataset import DASHBOARD_DATASET
from bisheng.telemetry_search.domain.models.dashboard_dataset import DimensionConfig
from bisheng.telemetry_search.domain.schemas.component import (
    ComponentDataConfig,
    DimensionField,
    DimensionQueryFilter,
)
from bisheng.telemetry_search.domain.services.component import DataQueryService


def _node(department_id, name, level, path, tenant_id=1, status="active", is_deleted=0):
    return SimpleNamespace(
        id=department_id,
        name=name,
        org_level=level,
        path=path,
        tenant_id=tenant_id,
        status=status,
        is_deleted=is_deleted,
    )


def _org():
    company = _node(1, "首钢股份", "company", "/1")
    manufacturing = _node(10, "制造部", "dept", "/1/10")
    office = _node(30, "轧钢科", "office", "/1/10/30")
    equipment = _node(40, "设备部", "dept", "/1/40")
    disabled = _node(50, "停用部", "dept", "/1/50", status="inactive")
    other_tenant = _node(60, "外租户部", "dept", "/60", tenant_id=2)
    nodes = {
        1: company,
        10: manufacturing,
        30: office,
        40: equipment,
        50: disabled,
        60: other_tenant,
    }
    return nodes


def test_office_primary_expands_to_company_parent_department_and_office():
    nodes = _org()
    assert belonging_names(nodes[30], nodes, 1) == {
        "belonging_company_name": "首钢股份",
        "belonging_department_name": "制造部",
        "belonging_office_name": "轧钢科",
    }


def test_invalid_primary_leaves_names_empty():
    nodes = _org()
    assert belonging_names(None, nodes, 1) == {}
    assert belonging_names(nodes[50], nodes, 1) == {}
    assert belonging_names(nodes[60], nodes, 1) == {}
    deleted = _node(10, "制造部", "dept", "/1/10", is_deleted=1)
    assert belonging_names(deleted, nodes, 1) == {}


def test_company_without_department_leaves_lower_levels_empty():
    nodes = _org()
    assert belonging_names(nodes[1], nodes, 1) == {"belonging_company_name": "首钢股份"}


def test_qa_backfill_copies_asker_names_and_ignores_today_department():
    nodes = _org()
    names = qa_belonging_names(
        {
            "tenant_id": 1,
            "primary_department_id": 40,
            "asker_company_name": "首钢股份",
            "asker_department_name": "制造部",
            "asker_office_name": "",
        },
        nodes[40],
        nodes,
    )
    assert names["belonging_department_name"] == "制造部"
    assert "belonging_office_name" not in names


def test_qa_backfill_uses_stored_department_when_asker_names_are_absent():
    nodes = _org()
    names = qa_belonging_names(
        {"tenant_id": 1, "primary_department_id": 10},
        nodes[10],
        nodes,
    )
    assert names == {
        "belonging_company_name": "首钢股份",
        "belonging_department_name": "制造部",
    }


def test_participation_merge_keeps_recorded_names_with_recorded_department():
    current = {
        "user_id": 7,
        "logged_in": True,
        "department_source": "event_time",
        "primary_department_id": 10,
        "belonging_department_name": "制造部",
    }
    roster = {
        "user_id": 7,
        "logged_in": False,
        "department_source": "current_roster",
        "primary_department_id": 40,
        "belonging_department_name": "设备部",
    }
    merged = merge_participation_document(current, roster)
    assert merged["primary_department_id"] == 10
    assert merged["belonging_department_name"] == "制造部"
    assert "未分类" not in merged.values()


def test_backfill_patch_replaces_names_without_dropping_other_fields():
    current = {"user_id": 1001, "metric_source": "increment", "belonging_department_name": "旧部门"}
    merged = merge_belonging_backfill(current, {"names": {"belonging_department_name": "设备部"}})
    assert merged["user_id"] == 1001
    assert merged["metric_source"] == "increment"
    assert merged["belonging_department_name"] == "设备部"

    cleared = apply_belonging_names(merged, {})
    assert "belonging_department_name" not in cleared
    assert cleared["user_id"] == 1001


def test_user_and_qa_datasets_expose_belonging_fields_and_other_datasets_do_not():
    fields = {
        dataset.dataset_code: {item["field"] for item in dataset.schema_config["dimensions"]}
        for dataset in DASHBOARD_DATASET
    }
    expected = {"belonging_company_name", "belonging_department_name", "belonging_office_name"}
    assert expected <= fields["mid_user_increment"]
    assert expected <= fields["mid_realtime_qa_question_fact"]
    assert expected <= fields["mid_active_user"]
    assert expected <= fields["mid_user_daily_participation"]
    assert expected.isdisjoint(fields["mid_app_increment"])


async def test_missing_bucket_is_only_added_for_user_and_qa_belonging_fields():
    dimension_map = {
        "belonging_department_name": DimensionConfig(name="所属部门", field="belonging_department_name"),
    }
    dimensions = [DimensionField(fieldId="belonging_department_name", fieldName="所属部门")]
    user_agg = (await DataQueryService.convert_dimensions(dimensions, dimension_map, "mid_user_increment"))[0]
    content_agg = (
        await DataQueryService.convert_dimensions(dimensions, dimension_map, "mid_knowledge_space_content_stat")
    )[0]
    assert user_agg.custom_params["missing"] == ""
    assert content_agg.custom_params is None
    assert belonging_terms_missing("mid_app_increment", "belonging_department_name") is None


async def test_selected_belonging_department_filters_user_dataset_and_skips_app_dataset():
    dimension_map = {
        "belonging_department_name": DimensionConfig(name="所属部门", field="belonging_department_name"),
    }
    selected = DataQueryService(
        dataset_code="mid_user_increment",
        data_config=ComponentDataConfig(),
        dimension_filters=[DimensionQueryFilter(fieldId="belonging_department_name", values=["制造部"])],
    )
    filters, _time_range = await selected.convert_filters(dimension_map, {})
    dumped = filters[0].model_dump()
    assert dumped["filters"][0]["field"] == "belonging_department_name"
    assert dumped["filters"][0]["value"] == ["制造部"]

    skipped = DataQueryService(
        dataset_code="mid_app_increment",
        data_config=ComponentDataConfig(),
        dimension_filters=[DimensionQueryFilter(fieldId="belonging_department_name", values=["制造部"])],
    )
    skipped_filters, _skipped_time = await skipped.convert_filters({}, {})
    assert skipped_filters == []
