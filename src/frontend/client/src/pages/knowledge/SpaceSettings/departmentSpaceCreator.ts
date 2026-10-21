import type { PermissionDraftRow } from "~/components/permission/usePermissionDraft";

/** The configured department responsible user has owner permissions, not creator provenance. */
export interface DepartmentSpaceCreator {
  id: number;
  name: string;
}

export function decorateDepartmentSpaceRows(
  rows: PermissionDraftRow[],
  responsible: DepartmentSpaceCreator | null,
): PermissionDraftRow[] {
  if (!responsible) return rows;
  // Permission models and protection come from the actual Grant. Do not invent
  // an owner row while its projection is unavailable or hide a failed upgrade.
  return rows.map((row) =>
    row.sourceType?.toLowerCase() === "creator" ||
    (row.subjectType === "user" && row.subjectId === responsible.id && row.protected)
      ? { ...row, sourceType: undefined }
      : row,
  );
}

/** Restore provenance before submitting the existing permission draft. */
export function restoreDepartmentSpaceRows(
  rows: PermissionDraftRow[],
  originals: PermissionDraftRow[],
): PermissionDraftRow[] {
  const sourceByKey = new Map(originals.map((row) => [row.assigneeId, row.sourceType]));
  return rows.map((row) =>
    row.assigneeId !== undefined && sourceByKey.has(row.assigneeId)
      ? { ...row, sourceType: sourceByKey.get(row.assigneeId) }
      : row,
  );
}
