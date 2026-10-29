"""Department short-name display resolution (F058, AC-04 / AC-11).

Two lookup paths:
- ``department_id`` present (e.g. a filter dropdown value sourced from the
  department tree): exact lookup, ``short_name`` or fall back to ``name``.
- Only a free-text ``name_text`` available (e.g. a historical org-name
  snapshot stored on telemetry mid-table rows, with no FK to the current
  ``department`` table): best-effort lookup by exact name match. If the
  department was renamed/deleted, or the name matches more than one
  department (duplicate names across the org tree), the match is treated as
  ambiguous and the original text is returned unchanged rather than guessing.
"""

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.core.database import get_async_db_session
from bisheng.database.models.department import Department, DepartmentDao
from bisheng.department.domain.services.department_display_service import get_department_display_name
from bisheng.telemetry.domain.mid_table.knowledge_space_content_dimensions import ORGANIZATION_NAME_FIELDS

ORGANIZATION_DIMENSIONS = {
    *ORGANIZATION_NAME_FIELDS,
    "primary_department_name",
    "user_department_infos.department_name",
    *(
        f"{prefix}_{field}"
        for prefix in ("uploader", "belonging", "original_upload", "asker")
        for field in ORGANIZATION_NAME_FIELDS
    ),
}


async def resolve_dimension_labels(fields: list[str], rows: list[list]) -> dict[str, dict[str, str]]:
    """Batch display labels without replacing raw aggregation or filter values."""
    names_by_field = {
        field: {str(row[index]) for row in rows if index < len(row) and row[index]}
        for index, field in enumerate(fields)
        if field in ORGANIZATION_DIMENSIONS
    }
    if not any(names_by_field.values()):
        return {}

    async with get_async_db_session() as session:
        departments = await BaseRepositoryImpl(session, Department).find_all()
    matches: dict[str, list[Department]] = {}
    for department in departments:
        matches.setdefault(department.name, []).append(department)

    labels = {}
    for field, names in names_by_field.items():
        labels[field] = {}
        for name in names:
            candidates = matches.get(name, [])
            labels[field][name] = (
                get_department_display_name(name, candidates[0].short_name) if len(candidates) == 1 else name
            )
    return labels


async def resolve_short_name(department_id: int | None, name_text: str | None) -> str:
    if department_id is not None:
        dept = await DepartmentDao.aget_by_id(department_id)
        if dept is not None:
            return get_department_display_name(dept.name, dept.short_name)
        return name_text or ""

    if not name_text:
        return name_text or ""

    matches = await DepartmentDao.aget_by_name(name_text)
    if len(matches) == 1:
        return get_department_display_name(name_text, matches[0].short_name)

    # No match, or ambiguous (duplicate names): fall back to the original text.
    return name_text
