#!/usr/bin/env python3
"""Count current business documents by original knowledge-space organization."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from collections.abc import AsyncIterator, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import exists, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.department.domain.services.department_display_service import (
    get_department_display_name,
)
from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileEntryType,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum, KnowledgeSpaceScope

SPACE_LEVELS = (
    KnowledgeSpaceLevelEnum.PUBLIC.value,
    KnowledgeSpaceLevelEnum.DEPARTMENT.value,
    KnowledgeSpaceLevelEnum.TEAM_KS.value,
    KnowledgeSpaceLevelEnum.TEAM.value,
    KnowledgeSpaceLevelEnum.PERSONAL.value,
)
ORGANIZATION_LEVELS = frozenset({"company", "dept", "office", "squad"})
LEGACY_PUBLISH_METADATA_KEY = "shougang_portal_publish"
FAVORITE_REFERENCE_SOURCE = "favorite_reference"
DEFAULT_OUTPUT_FILE = "knowledge_file_counts_by_original_organization.json"
UNASSIGNED_REASONS = (
    "missing_original_knowledge",
    "original_knowledge_not_found",
    "missing_space_scope",
    "missing_organization_mapping",
    "missing_owner_organization",
    "invalid_space_level",
)


@dataclass(frozen=True, slots=True)
class CandidateFile:
    """One unique physical business document eligible for counting."""

    file_id: int
    original_knowledge_id: int | None
    knowledge_id: int | None = None


@dataclass(slots=True)
class DimensionSnapshot:
    """Read-only lookup data used to resolve original-space ownership."""

    spaces: dict[int, Any]
    scopes: dict[int, Any]
    bound_department_ids: dict[int, int | None]
    primary_department_ids: dict[int, int | None]
    departments: dict[int, Any]


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip().lower()


def is_legacy_distribution_copy(metadata: Any) -> bool:
    """Return whether legacy metadata identifies a copied publish entry."""

    if not isinstance(metadata, Mapping):
        return False
    publish = metadata.get(LEGACY_PUBLISH_METADATA_KEY)
    return isinstance(publish, Mapping) and _positive_int(publish.get("source_file_id")) is not None


async def iter_eligible_file_pages(
    session: AsyncSession,
    *,
    page_size: int = 1000,
) -> AsyncIterator[list[CandidateFile]]:
    """Yield current physical business documents without logical distribution copies."""

    if page_size <= 0:
        raise ValueError("page_size must be greater than zero")

    last_file_id = 0
    while True:
        any_version = select(KnowledgeDocumentVersion.id).where(
            KnowledgeDocumentVersion.knowledge_file_id == KnowledgeFile.id
        )
        primary_version = any_version.where(KnowledgeDocumentVersion.is_primary.is_(True))
        statement = (
            select(
                KnowledgeFile.id,
                KnowledgeFile.knowledge_id,
                KnowledgeFile.original_knowledge_id,
                KnowledgeFile.user_metadata,
            )
            .join(Knowledge, Knowledge.id == KnowledgeFile.knowledge_id)
            .where(
                KnowledgeFile.id > last_file_id,
                Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                Knowledge.is_favorite.is_(False),
                KnowledgeFile.file_type == FileType.FILE.value,
                KnowledgeFile.status == KnowledgeFileStatus.SUCCESS.value,
                col(KnowledgeFile.deleted_at).is_(None),
                or_(
                    col(KnowledgeFile.file_source).is_(None),
                    KnowledgeFile.file_source != FAVORITE_REFERENCE_SOURCE,
                ),
                or_(
                    col(KnowledgeFile.entry_type).is_(None),
                    KnowledgeFile.entry_type == KnowledgeFileEntryType.MANAGER.value,
                ),
                or_(~exists(any_version), exists(primary_version)),
            )
            .order_by(KnowledgeFile.id.asc())
            .limit(page_size)
        )
        rows = list((await session.exec(statement)).all())
        if not rows:
            return

        page = [
            CandidateFile(
                file_id=int(file_id),
                original_knowledge_id=_positive_int(original_knowledge_id),
                knowledge_id=_positive_int(knowledge_id),
            )
            for file_id, knowledge_id, original_knowledge_id, user_metadata in rows
            if not is_legacy_distribution_copy(user_metadata)
        ]
        if page:
            yield page

        last_file_id = int(rows[-1][0])
        if len(rows) < page_size:
            return


def _merge_unique_mapping(
    target: dict[int, int | None],
    key: Any,
    value: Any,
) -> None:
    normalized_key = _positive_int(key)
    normalized_value = _positive_int(value)
    if normalized_key is None or normalized_value is None:
        return
    previous = target.get(normalized_key)
    if previous is not None and previous != normalized_value:
        target[normalized_key] = None
        return
    if normalized_key not in target:
        target[normalized_key] = normalized_value


async def load_dimension_snapshot(session: AsyncSession) -> DimensionSnapshot:
    """Load all default-tenant dimensions once to avoid per-file queries."""

    from bisheng.database.models.department import Department, UserDepartment

    spaces = {
        int(item.id): item
        for item in (await session.exec(select(Knowledge).where(Knowledge.type == KnowledgeTypeEnum.SPACE.value))).all()
        if item.id is not None
    }
    scopes = {
        int(item.space_id): item
        for item in (await session.exec(select(KnowledgeSpaceScope))).all()
        if item.space_id is not None
    }

    bound_department_ids: dict[int, int | None] = {}
    binding_rows = (
        await session.exec(select(DepartmentKnowledgeSpace.space_id, DepartmentKnowledgeSpace.department_id))
    ).all()
    for space_id, department_id in binding_rows:
        _merge_unique_mapping(bound_department_ids, space_id, department_id)

    primary_department_ids: dict[int, int | None] = {}
    membership_rows = (
        await session.exec(
            select(UserDepartment.user_id, UserDepartment.department_id).where(UserDepartment.is_primary == 1)
        )
    ).all()
    for user_id, department_id in membership_rows:
        _merge_unique_mapping(primary_department_ids, user_id, department_id)

    departments = {
        int(item.id): item
        for item in (await session.exec(select(Department).where(Department.status == "active"))).all()
        if item.id is not None
    }
    return DimensionSnapshot(
        spaces=spaces,
        scopes=scopes,
        bound_department_ids=bound_department_ids,
        primary_department_ids=primary_department_ids,
        departments=departments,
    )


def _path_ids(department: Any) -> list[int]:
    values: list[int] = []
    seen: set[int] = set()
    for raw_value in str(getattr(department, "path", "") or "").strip("/").split("/"):
        value = _positive_int(raw_value)
        if value is not None and value not in seen:
            values.append(value)
            seen.add(value)
    department_id = _positive_int(getattr(department, "id", None))
    if department_id is not None and department_id not in seen:
        values.append(department_id)
    return values


def _organization_node(department: Any) -> dict[str, Any] | None:
    department_id = _positive_int(getattr(department, "id", None))
    name = str(getattr(department, "name", "") or "").strip()
    level = _enum_value(getattr(department, "org_level", None))
    if department_id is None or not name or level not in ORGANIZATION_LEVELS:
        return None
    return {
        "organization_id": department_id,
        "organization_name": name,
        "organization_short_name": get_department_display_name(
            name,
            getattr(department, "short_name", None),
        ),
        "organization_level": level,
    }


def _organization_path(
    department: Any,
    departments: Mapping[int, Any],
) -> list[dict[str, Any]] | None:
    target_id = _positive_int(getattr(department, "id", None))
    result: list[dict[str, Any]] = []
    for department_id in _path_ids(department):
        node_source = departments.get(department_id)
        if node_source is None or str(getattr(node_source, "status", "active")) != "active":
            continue
        node = _organization_node(node_source)
        if node is not None:
            result.append(node)
    if target_id is None or not result or result[-1]["organization_id"] != target_id:
        return None
    return result


def _resolve_assignment(
    candidate: CandidateFile,
    dimensions: DimensionSnapshot,
) -> tuple[str | None, Any | None, list[dict[str, Any]] | None, str | None]:
    source_knowledge_id = candidate.original_knowledge_id
    if source_knowledge_id is None:
        source_knowledge_id = candidate.knowledge_id
    if source_knowledge_id is None:
        return None, None, None, "missing_original_knowledge"
    if source_knowledge_id not in dimensions.spaces:
        return None, None, None, "original_knowledge_not_found"

    scope = dimensions.scopes.get(source_knowledge_id)
    if scope is None:
        return None, None, None, "missing_space_scope"
    level = _enum_value(getattr(scope, "level", None))
    if level not in SPACE_LEVELS:
        return None, None, None, "invalid_space_level"

    organization_id: int | None
    missing_reason = "missing_organization_mapping"
    if level == KnowledgeSpaceLevelEnum.PUBLIC.value:
        company_ids = sorted(
            int(department_id)
            for department_id, department in dimensions.departments.items()
            if _enum_value(getattr(department, "org_level", None)) == "company"
        )
        organization_id = company_ids[0] if len(company_ids) == 1 else None
    elif level in {
        KnowledgeSpaceLevelEnum.DEPARTMENT.value,
        KnowledgeSpaceLevelEnum.TEAM_KS.value,
    }:
        organization_id = dimensions.bound_department_ids.get(source_knowledge_id)
    else:
        missing_reason = "missing_owner_organization"
        owner_id = (
            _positive_int(getattr(scope, "created_by", None))
            if level == KnowledgeSpaceLevelEnum.TEAM.value
            else _positive_int(getattr(scope, "owner_id", None))
        )
        organization_id = dimensions.primary_department_ids.get(owner_id) if owner_id is not None else None

    organization = dimensions.departments.get(organization_id) if organization_id is not None else None
    if organization is None or str(getattr(organization, "status", "active")) != "active":
        return level, None, None, missing_reason
    path = _organization_path(organization, dimensions.departments)
    if path is None:
        return level, None, None, missing_reason
    return level, organization, path, None


class ReportAccumulator:
    """Incrementally aggregate candidate files into the confirmed JSON contract."""

    def __init__(
        self,
        dimensions: DimensionSnapshot,
        *,
        generated_at: datetime | None = None,
    ) -> None:
        self.dimensions = dimensions
        self.generated_at = generated_at or datetime.now().astimezone()
        self.organization_counts: dict[int, dict[str, int]] = {}
        self.organization_paths: dict[int, list[dict[str, Any]]] = {}
        self.unassigned = dict.fromkeys(UNASSIGNED_REASONS, 0)
        self.total = 0

    def add(self, candidate: CandidateFile) -> None:
        self.total += 1
        level, organization, path, reason = _resolve_assignment(candidate, self.dimensions)
        if reason is not None:
            self.unassigned[reason] += 1
            return
        if level is None or organization is None or path is None:
            raise RuntimeError(f"Incomplete organization assignment for file_id={candidate.file_id}")

        organization_id = int(organization.id)
        counts = self.organization_counts.setdefault(
            organization_id,
            dict.fromkeys(SPACE_LEVELS, 0),
        )
        counts[level] += 1
        self.organization_paths[organization_id] = path

    def add_many(self, candidates: Iterable[CandidateFile]) -> None:
        for candidate in candidates:
            self.add(candidate)

    def build(self) -> dict[str, Any]:
        organizations: list[dict[str, Any]] = []
        for organization_id, counts in self.organization_counts.items():
            organization = self.dimensions.departments[organization_id]
            node = _organization_node(organization)
            if node is None:
                raise RuntimeError(f"Invalid organization projection for organization_id={organization_id}")
            organizations.append(
                {
                    **node,
                    "organization_path": self.organization_paths[organization_id],
                    "counts": dict(counts),
                    "total": sum(counts.values()),
                }
            )
        organizations.sort(
            key=lambda item: (
                tuple(node["organization_id"] for node in item["organization_path"]),
                item["organization_id"],
            )
        )

        unassigned_total = sum(self.unassigned.values())
        assigned_total = sum(item["total"] for item in organizations)
        report = {
            "generated_at": self.generated_at.astimezone().isoformat(timespec="seconds"),
            "organizations": organizations,
            "unassigned": {**self.unassigned, "total": unassigned_total},
            "summary": {
                "assigned": assigned_total,
                "unassigned": unassigned_total,
                "total": self.total,
            },
        }
        validate_report(report)
        return report


def build_report(
    candidates: Iterable[CandidateFile],
    dimensions: DimensionSnapshot,
    *,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    accumulator = ReportAccumulator(dimensions, generated_at=generated_at)
    accumulator.add_many(candidates)
    return accumulator.build()


def validate_report(report: Mapping[str, Any]) -> None:
    organizations = report.get("organizations")
    unassigned = report.get("unassigned")
    summary = report.get("summary")
    if not isinstance(organizations, list) or not isinstance(unassigned, Mapping) or not isinstance(summary, Mapping):
        raise ValueError("report is missing organizations, unassigned, or summary")

    assigned_total = 0
    for organization in organizations:
        counts = organization.get("counts")
        if not isinstance(counts, Mapping) or tuple(counts) != SPACE_LEVELS:
            raise ValueError("organization counts must contain the five ordered space levels")
        organization_total = sum(int(counts[level]) for level in SPACE_LEVELS)
        if organization_total != int(organization.get("total", -1)):
            raise ValueError("organization total does not match its category counts")
        assigned_total += organization_total

    unassigned_total = sum(int(unassigned.get(reason, 0)) for reason in UNASSIGNED_REASONS)
    if unassigned_total != int(unassigned.get("total", -1)):
        raise ValueError("unassigned total does not match its reason counts")
    if assigned_total != int(summary.get("assigned", -1)):
        raise ValueError("summary assigned count does not match organizations")
    if unassigned_total != int(summary.get("unassigned", -1)):
        raise ValueError("summary unassigned count does not match unassigned reasons")
    if assigned_total + unassigned_total != int(summary.get("total", -1)):
        raise ValueError("summary total is not conserved")


def write_json_report(
    report: Mapping[str, Any],
    output_path: str | Path,
    *,
    force: bool = False,
) -> Path:
    """Validate and atomically write one UTF-8 JSON report."""

    validate_report(report)
    target = Path(output_path).expanduser().resolve()
    if not target.parent.is_dir():
        raise FileNotFoundError(f"Output directory does not exist: {target.parent}")
    if target.exists() and not force:
        raise FileExistsError(f"Output file already exists: {target}")

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if target.exists() and not force:
            raise FileExistsError(f"Output file already exists: {target}")
        os.replace(temp_path, target)
        return target
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


async def generate_report(page_size: int = 1000) -> dict[str, Any]:
    """Read default-tenant data and build the report without writing it."""

    from bisheng.core.database import get_async_db_session

    async with get_async_db_session() as session:
        dimensions = await load_dimension_snapshot(session)
        accumulator = ReportAccumulator(dimensions)
        async for page in iter_eligible_file_pages(session, page_size=page_size):
            accumulator.add_many(page)
        return accumulator.build()


async def run(args: argparse.Namespace) -> int:
    from bisheng.common.services.config_service import settings
    from bisheng.core.context.manager import close_app_context, initialize_app_context
    from bisheng.core.context.tenant import (
        DEFAULT_TENANT_ID,
        current_tenant_id,
        set_current_tenant_id,
    )

    if args.page_size <= 0:
        raise ValueError("--page-size must be greater than zero")
    if bool(settings.multi_tenant.enabled):
        raise RuntimeError("This report only supports deployments with multi-tenancy disabled")

    target = Path(args.output).expanduser().resolve()
    if target.exists() and not args.force:
        raise FileExistsError(f"Output file already exists: {target}")

    await initialize_app_context(config=settings)
    tenant_token = set_current_tenant_id(DEFAULT_TENANT_ID)
    try:
        report = await generate_report(page_size=args.page_size)
        written_path = write_json_report(report, target, force=args.force)
        summary = report["summary"]
        print(
            "Report generated: "
            f"assigned={summary['assigned']} "
            f"unassigned={summary['unassigned']} "
            f"total={summary['total']} "
            f"output={written_path}"
        )
        return 0
    finally:
        current_tenant_id.reset(tenant_token)
        await close_app_context()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT_FILE,
        help=f"JSON 输出路径, 默认: {DEFAULT_OUTPUT_FILE}",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=1000,
        help="文件分页大小, 默认: 1000",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="允许覆盖已经存在的输出文件",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        return asyncio.run(run(parse_args(argv)))
    except (FileExistsError, FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
