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

from bisheng.database.models.department import DepartmentDao


async def resolve_short_name(department_id: int | None, name_text: str | None) -> str:
    if department_id is not None:
        dept = await DepartmentDao.aget_by_id(department_id)
        if dept is not None:
            return dept.short_name or dept.name
        return name_text or ""

    if not name_text:
        return name_text or ""

    matches = await DepartmentDao.aget_by_name(name_text)
    if len(matches) == 1:
        return matches[0].short_name or name_text

    # No match, or ambiguous (duplicate names): fall back to the original text.
    return name_text
