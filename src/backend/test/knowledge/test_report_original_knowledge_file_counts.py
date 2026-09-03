"""原始上传知识库文件组织统计脚本回归测试。"""

from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
    KnowledgeFileStatus,
)
from scripts.report_original_knowledge_file_counts import (
    CandidateFile,
    DimensionSnapshot,
    build_report,
    is_legacy_distribution_copy,
    iter_eligible_file_pages,
    write_json_report,
)


def _department(
    department_id: int,
    *,
    name: str,
    level: str,
    path: str,
    short_name: str | None = None,
    status: str = "active",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=department_id,
        name=name,
        short_name=short_name,
        org_level=level,
        path=path,
        status=status,
    )


def _space(space_id: int) -> SimpleNamespace:
    return SimpleNamespace(id=space_id, type=KnowledgeTypeEnum.SPACE.value)


def _dimensions() -> DimensionSnapshot:
    departments = {
        1: _department(1, name="首钢股份有限公司", short_name="首钢股份", level="company", path="/1/"),
        10: _department(10, name="炼钢作业部", level="dept", path="/1/10/"),
        20: _department(20, name="炼钢科室", short_name="炼钢科", level="office", path="/1/10/20/"),
        30: _department(30, name="甲班", level="squad", path="/1/10/20/30/"),
    }
    return DimensionSnapshot(
        spaces={space_id: _space(space_id) for space_id in range(100, 105)},
        scopes={
            100: SimpleNamespace(level="public", created_by=0, owner_id=0),
            101: SimpleNamespace(level="department", created_by=0, owner_id=0),
            102: SimpleNamespace(level="team_ks", created_by=0, owner_id=0),
            103: SimpleNamespace(level="team", created_by=900, owner_id=0),
            104: SimpleNamespace(level="personal", created_by=0, owner_id=901),
        },
        bound_department_ids={101: 10, 102: 20},
        primary_department_ids={900: 30, 901: 20},
        departments=departments,
    )


def test_build_report_maps_five_space_levels_to_one_actual_organization() -> None:
    report = build_report(
        [CandidateFile(file_id=index, original_knowledge_id=99 + index, knowledge_id=101) for index in range(1, 6)],
        _dimensions(),
        generated_at=datetime.fromisoformat("2026-09-03T12:00:00+08:00"),
    )

    organizations = {item["organization_id"]: item for item in report["organizations"]}
    assert organizations[1]["counts"] == {
        "public": 1,
        "department": 0,
        "team_ks": 0,
        "team": 0,
        "personal": 0,
    }
    assert organizations[10]["counts"]["department"] == 1
    assert organizations[20]["counts"]["team_ks"] == 1
    assert organizations[20]["counts"]["personal"] == 1
    assert organizations[30]["counts"]["team"] == 1
    assert organizations[10]["organization_short_name"] == "炼钢作业部"
    assert organizations[20]["organization_short_name"] == "炼钢科"
    assert organizations[30]["organization_path"] == [
        {
            "organization_id": 1,
            "organization_name": "首钢股份有限公司",
            "organization_short_name": "首钢股份",
            "organization_level": "company",
        },
        {
            "organization_id": 10,
            "organization_name": "炼钢作业部",
            "organization_short_name": "炼钢作业部",
            "organization_level": "dept",
        },
        {
            "organization_id": 20,
            "organization_name": "炼钢科室",
            "organization_short_name": "炼钢科",
            "organization_level": "office",
        },
        {
            "organization_id": 30,
            "organization_name": "甲班",
            "organization_short_name": "甲班",
            "organization_level": "squad",
        },
    ]
    assert report["summary"] == {"assigned": 5, "unassigned": 0, "total": 5}


def test_build_report_falls_back_to_current_knowledge_when_original_is_missing() -> None:
    report = build_report(
        [CandidateFile(file_id=1, original_knowledge_id=None, knowledge_id=101)],
        _dimensions(),
    )

    assert report["organizations"][0]["organization_id"] == 10
    assert report["organizations"][0]["counts"]["department"] == 1
    assert report["unassigned"]["missing_original_knowledge"] == 0
    assert report["summary"] == {"assigned": 1, "unassigned": 0, "total": 1}


def test_build_report_keeps_unresolvable_files_in_auditable_buckets() -> None:
    dimensions = _dimensions()
    dimensions.spaces.update({200: _space(200), 201: _space(201), 202: _space(202), 203: _space(203)})
    dimensions.scopes.update(
        {
            201: SimpleNamespace(level="unsupported", created_by=0, owner_id=0),
            202: SimpleNamespace(level="department", created_by=0, owner_id=0),
            203: SimpleNamespace(level="personal", created_by=0, owner_id=999),
        }
    )

    report = build_report(
        [
            CandidateFile(file_id=1, original_knowledge_id=None),
            CandidateFile(file_id=2, original_knowledge_id=999),
            CandidateFile(file_id=3, original_knowledge_id=200),
            CandidateFile(file_id=4, original_knowledge_id=201),
            CandidateFile(file_id=5, original_knowledge_id=202),
            CandidateFile(file_id=6, original_knowledge_id=203),
        ],
        dimensions,
    )

    assert report["organizations"] == []
    assert report["unassigned"] == {
        "missing_original_knowledge": 1,
        "original_knowledge_not_found": 1,
        "missing_space_scope": 1,
        "missing_organization_mapping": 1,
        "missing_owner_organization": 1,
        "invalid_space_level": 1,
        "total": 6,
    }
    assert report["summary"] == {"assigned": 0, "unassigned": 6, "total": 6}


def test_legacy_publish_metadata_is_recognized_as_a_distribution_copy() -> None:
    assert is_legacy_distribution_copy({"shougang_portal_publish": {"source_file_id": 12}})
    assert not is_legacy_distribution_copy({"shougang_portal_publish": {"source_file_id": None}})
    assert not is_legacy_distribution_copy({})
    assert not is_legacy_distribution_copy(None)


def test_write_json_report_is_utf8_and_requires_force_for_overwrite(tmp_path) -> None:
    output = tmp_path / "统计结果.json"
    report = {
        "generated_at": "2026-09-03T12:00:00+08:00",
        "organizations": [
            {
                "organization_name": "炼钢作业部",
                "counts": {
                    "public": 0,
                    "department": 1,
                    "team_ks": 0,
                    "team": 0,
                    "personal": 0,
                },
                "total": 1,
            }
        ],
        "unassigned": {
            "missing_original_knowledge": 0,
            "original_knowledge_not_found": 0,
            "missing_space_scope": 0,
            "missing_organization_mapping": 0,
            "missing_owner_organization": 0,
            "invalid_space_level": 0,
            "total": 0,
        },
        "summary": {"assigned": 1, "unassigned": 0, "total": 1},
    }

    write_json_report(report, output)
    assert "炼钢作业部" in output.read_text(encoding="utf-8")
    assert json.loads(output.read_text(encoding="utf-8")) == report

    with pytest.raises(FileExistsError):
        write_json_report(report, output)

    report["organizations"][0]["counts"]["department"] = 2
    report["organizations"][0]["total"] = 2
    report["summary"]["assigned"] = 2
    report["summary"]["total"] = 2
    write_json_report(report, output, force=True)
    assert json.loads(output.read_text(encoding="utf-8"))["summary"]["total"] == 2


def _db_space(space_id: int, *, favorite: bool = False) -> Knowledge:
    return Knowledge(
        id=space_id,
        tenant_id=1,
        user_id=1,
        name=f"space-{space_id}",
        type=KnowledgeTypeEnum.SPACE.value,
        is_favorite=favorite,
    )


def _db_file(file_id: int, *, knowledge_id: int = 10, **kwargs) -> KnowledgeFile:
    values = {
        "original_knowledge_id": 10,
        "user_id": 1,
        "file_name": f"file-{file_id}.pdf",
        "file_type": FileType.FILE.value,
        "status": KnowledgeFileStatus.SUCCESS.value,
        **kwargs,
    }
    return KnowledgeFile(
        id=file_id,
        tenant_id=1,
        knowledge_id=knowledge_id,
        **values,
    )


async def test_eligible_query_counts_only_current_physical_business_documents(
    async_db_session: AsyncSession,
) -> None:
    current_file = _db_file(
        10,
        entry_type=KnowledgeFileEntryType.MANAGER.value,
        entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
    )
    historical_file = _db_file(11)
    async_db_session.add_all(
        [
            _db_space(10),
            _db_space(20, favorite=True),
            _db_file(1, original_knowledge_id=None),
            _db_file(2, entry_type=KnowledgeFileEntryType.PUBLISH.value),
            _db_file(3, entry_type=KnowledgeFileEntryType.SHARE.value),
            _db_file(4, entry_type=KnowledgeFileEntryType.PROJECTION_TOMBSTONE.value),
            _db_file(5, status=KnowledgeFileStatus.FAILED.value),
            _db_file(6, deleted_at=datetime(2026, 9, 1)),
            _db_file(7, file_type=FileType.DIR.value),
            _db_file(8, knowledge_id=20),
            _db_file(9, user_metadata={"shougang_portal_publish": {"source_file_id": 1}}),
            current_file,
            historical_file,
            KnowledgeDocument(id=100, tenant_id=1, knowledge_id=10, primary_version_id=1000),
            KnowledgeDocumentVersion(
                id=1000,
                document_id=100,
                knowledge_file_id=10,
                version_no=2,
                is_primary=True,
            ),
            KnowledgeDocumentVersion(
                id=1001,
                document_id=100,
                knowledge_file_id=11,
                version_no=1,
                is_primary=False,
            ),
        ]
    )
    await async_db_session.commit()

    candidates = [
        candidate async for page in iter_eligible_file_pages(async_db_session, page_size=2) for candidate in page
    ]

    assert [candidate.file_id for candidate in candidates] == [1, 10]
    assert [candidate.knowledge_id for candidate in candidates] == [10, 10]
    assert [candidate.original_knowledge_id for candidate in candidates] == [None, 10]
