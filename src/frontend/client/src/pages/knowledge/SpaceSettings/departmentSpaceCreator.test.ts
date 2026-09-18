/**
 * Department space roster: the 创建者 tag belongs to the super admin who created
 * the space, not to the space admin who owns it (the owner grant is recorded
 * with a "creator" source), and the creator stays visible without a grant.
 */

import type { PermissionDraftRow } from "~/components/permission/usePermissionDraft";
import {
  CREATOR_DISPLAY_MODEL_KEY,
  decorateDepartmentSpaceRows,
  restoreDepartmentSpaceRows,
} from "./departmentSpaceCreator";

const creator = { id: 1, name: "admin" };

const owner: PermissionDraftRow = {
  subjectType: "user",
  subjectId: 7,
  subjectName: "zhang",
  modelKey: "owner",
  assigneeId: "a-owner",
  sourceType: "CREATOR",
  protected: true,
};

const viewer: PermissionDraftRow = {
  subjectType: "department",
  subjectId: 30,
  subjectName: "finance",
  modelKey: "viewer",
  assigneeId: "a-viewer",
  sourceType: "DEPARTMENT",
};

describe("decorateDepartmentSpaceRows", () => {
  it("leaves non-department spaces untouched", () => {
    const rows = [owner, viewer];
    expect(decorateDepartmentSpaceRows(rows, null)).toBe(rows);
  });

  it("moves the creator tag off the owner and lists the creator first", () => {
    const [first, ownerRow, viewerRow] = decorateDepartmentSpaceRows([owner, viewer], creator);
    expect(first).toMatchObject({
      subjectId: 1,
      subjectName: "admin",
      modelKey: CREATOR_DISPLAY_MODEL_KEY,
      sourceType: "creator",
      protected: true,
    });
    expect(ownerRow).toMatchObject({ subjectId: 7, modelKey: "owner", sourceType: undefined });
    expect(viewerRow).toEqual(viewer);
  });

  it("tags the creator's own row instead of adding a second one", () => {
    const creatorGrant: PermissionDraftRow = { ...viewer, subjectType: "user", subjectId: 1, assigneeId: "a-admin" };
    const rows = decorateDepartmentSpaceRows([owner, creatorGrant], creator);
    expect(rows).toHaveLength(2);
    expect(rows[1]).toMatchObject({ subjectId: 1, sourceType: "creator" });
  });

  it("keeps the tag when the space admin is the creator", () => {
    const rows = decorateDepartmentSpaceRows([{ ...owner, subjectId: 1 }], creator);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ modelKey: "owner", sourceType: "creator" });
  });
});

describe("restoreDepartmentSpaceRows", () => {
  it("drops the display row and restores the real sources", () => {
    const originals = [owner, viewer];
    const edited = decorateDepartmentSpaceRows(originals, creator).map((row) =>
      row.assigneeId === "a-viewer" ? { ...row, modelKey: "editor" } : row,
    );
    expect(restoreDepartmentSpaceRows(edited, originals)).toEqual([
      owner,
      { ...viewer, modelKey: "editor" },
    ]);
  });

  it("keeps rows added in this session as they are", () => {
    const added: PermissionDraftRow = { subjectType: "user", subjectId: 9, subjectName: "li", modelKey: "viewer" };
    const rows = [...decorateDepartmentSpaceRows([owner], creator), added];
    expect(restoreDepartmentSpaceRows(rows, [owner])).toEqual([owner, added]);
  });
});
