import type { PermissionDraftRow } from "~/components/permission/usePermissionDraft";

/**
 * Department knowledge spaces: show the creator next to the owner.
 *
 * A department space is created by a super admin but owned by its designated
 * space admin, and the creator deliberately holds no grant on it (so the super
 * admin is not pulled into every department's approvals). The owner grant is
 * still recorded with a "creator" source, which put the 创建者 tag on the space
 * admin. For display only: the tag moves to the real creator, who is listed as
 * a read-only row when no grant of theirs is already on the roster.
 */

export interface DepartmentSpaceCreator {
  id: number;
  name: string;
}

/** Marks the display-only creator row; never a real permission model. */
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
