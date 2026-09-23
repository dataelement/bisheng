import type { PermissionDraftRow } from "~/components/permission/usePermissionDraft";

/**
 * Department knowledge spaces: the configured responsible user is the creator.
 *
 * Knowledge.user_id only records the super admin who operated the creation and
 * must not surface in this roster. The caller passes the configured
 * admin_user_id instead; when it is absent, no creator row is synthesized.
 */

export interface DepartmentSpaceCreator {
  id: number;
  name: string;
}

/** Marks a configured responsible user whose grant projection is temporarily absent. */
export const CREATOR_DISPLAY_MODEL_KEY = "__department_space_creator__";

const CREATOR_SOURCE = "creator";

function isCreatorSource(row: PermissionDraftRow): boolean {
  return row.sourceType?.toLowerCase() === CREATOR_SOURCE;
}

function isCreatorUser(row: PermissionDraftRow, creator: DepartmentSpaceCreator): boolean {
  return row.subjectType === "user" && row.subjectId === creator.id;
}

export function isCreatorDisplayRow(row: PermissionDraftRow): boolean {
  return row.modelKey === CREATOR_DISPLAY_MODEL_KEY;
}

export function decorateDepartmentSpaceRows(
  rows: PermissionDraftRow[],
  creator: DepartmentSpaceCreator | null,
): PermissionDraftRow[] {
  if (!creator) return rows;
  const decorated = rows.map((row) => {
    if (isCreatorUser(row, creator)) return { ...row, sourceType: CREATOR_SOURCE };
    return isCreatorSource(row) ? { ...row, sourceType: undefined } : row;
  });
  if (decorated.some((row) => isCreatorUser(row, creator))) return decorated;
  const displayRow: PermissionDraftRow = {
    subjectType: "user",
    subjectId: creator.id,
    subjectName: creator.name,
    modelKey: CREATOR_DISPLAY_MODEL_KEY,
    modelName: "",
    sourceType: CREATOR_SOURCE,
    protected: true,
    editable: false,
  };
  return [displayRow, ...decorated];
}

/** Undo the display pass before rows go back into the permission draft. */
export function restoreDepartmentSpaceRows(
  rows: PermissionDraftRow[],
  originals: PermissionDraftRow[],
): PermissionDraftRow[] {
  const sourceByKey = new Map(originals.map((row) => [row.assigneeId, row.sourceType]));
  return rows
    .filter((row) => !isCreatorDisplayRow(row))
    .map((row) =>
      row.assigneeId !== undefined && sourceByKey.has(row.assigneeId)
        ? { ...row, sourceType: sourceByKey.get(row.assigneeId) }
        : row,
    );
}
