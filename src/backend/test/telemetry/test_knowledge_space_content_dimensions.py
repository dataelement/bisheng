from types import SimpleNamespace

import pytest

from bisheng.telemetry.domain.mid_table.knowledge_space_content import (
    KnowledgeSpaceContentStat,
    KnowledgeSpaceDownloadDailyRecord,
    KnowledgeSpaceFavoriteDailyRecord,
    KnowledgeSpacePreviewDailyRecord,
)
from bisheng.telemetry.domain.mid_table.knowledge_space_content_dimensions import (
    build_daily_document_id,
    resolve_organization_names,
)


def _department(department_id, name, level, path, status="active"):
    return SimpleNamespace(
        id=department_id,
        name=name,
        org_level=level,
        path=path,
        status=status,
    )


@pytest.mark.parametrize(
    ("start_id", "expected"),
    [
        (4, {"company_name": "首钢", "department_name": "技术部", "office_name": "研发科", "squad_name": "一班"}),
        (3, {"company_name": "首钢", "department_name": "技术部", "office_name": "研发科", "squad_name": None}),
        (5, {"company_name": "首钢", "department_name": "技术部", "office_name": "研发科", "squad_name": "一班"}),
    ],
)
def test_resolve_organization_names_uses_labeled_path_and_first_squad(start_id, expected):
    departments = {
        1: _department(1, "首钢", "company", "/1/"),
        2: _department(2, "技术部", "dept", "/1/2/"),
        3: _department(3, "研发科", "office", "/1/2/3/"),
        4: _department(4, "一班", "squad", "/1/2/3/4/"),
        5: _department(5, "一班子组", "squad", "/1/2/3/4/5/"),
    }

    result = resolve_organization_names(departments[start_id], departments)

    assert result.model_dump() == expected


def test_resolve_organization_names_preserves_missing_level():
    departments = {
        1: _department(1, "首钢", "company", "/1/"),
        3: _department(3, "研发科", "office", "/1/3/"),
    }

    result = resolve_organization_names(departments[3], departments)

    assert result.company_name == "首钢"
    assert result.department_name is None
    assert result.office_name == "研发科"


def test_daily_document_id_is_stable_and_splits_missing_from_value():
    dimensions = {"file_id": 11, "file_name": "制度.pdf", "uploader_company_name": "首钢"}

    first = build_daily_document_id(
        record_type="preview_daily",
        file_id=11,
        local_date="2026-08-20",
        dimensions=dimensions,
    )
    second = build_daily_document_id(
        record_type="preview_daily",
        file_id=11,
        local_date="2026-08-20",
        dimensions=dict(reversed(list(dimensions.items()))),
    )
    with_department = build_daily_document_id(
        record_type="preview_daily",
        file_id=11,
        local_date="2026-08-20",
        dimensions={**dimensions, "uploader_department_name": "技术部"},
    )

    assert first == second
    assert first.startswith("preview_daily:11:2026-08-20:")
    assert first != with_department


def test_mapping_contains_only_new_organization_fields():
    mapping = KnowledgeSpaceContentStat(ensure_sync_index=False)._mappings
    expected = {
        "uploader_company_name",
        "uploader_department_name",
        "uploader_office_name",
        "uploader_squad_name",
        "belonging_company_name",
        "belonging_department_name",
        "belonging_office_name",
        "belonging_squad_name",
    }

    assert expected.issubset(mapping)
    assert mapping["favorite_count"] == {"type": "long"}
    assert not {
        "tenant_id",
        "space_department_id",
        "space_department_name",
        "primary_department_id",
        "primary_department_name",
        "uploader_department_infos",
    }.intersection(mapping)


@pytest.mark.parametrize(
    ("record_cls", "metric_field", "record_type"),
    [
        (KnowledgeSpacePreviewDailyRecord, "preview_count", "preview_daily"),
        (KnowledgeSpaceDownloadDailyRecord, "download_count", "download_daily"),
        (KnowledgeSpaceFavoriteDailyRecord, "favorite_count", "favorite_daily"),
    ],
)
def test_daily_record_contract_has_fixed_type_and_omits_missing_dimensions(
    record_cls,
    metric_field,
    record_type,
):
    record = record_cls(
        timestamp=1,
        local_date="2026-08-20",
        space_id=3,
        space_name="公共库",
        file_id=11,
        file_name="制度.pdf",
        file_type=1,
        uploader_user_id=7,
        uploader_user_name="上传人",
        **{metric_field: 1},
    )

    source = record.model_dump()
    assert source["record_type"] == record_type
    assert "uploader_company_name" not in source
    assert "belonging_company_name" not in source
