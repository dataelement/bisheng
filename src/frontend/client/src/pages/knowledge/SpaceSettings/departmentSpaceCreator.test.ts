/**
 * Department space roster: the 创建者 tag belongs to the configured responsible
 * user. The super admin recorded as the audit creator never appears here.
 */

import type { PermissionDraftRow } from "~/components/permission/usePermissionDraft";
import {
  CREATOR_DISPLAY_MODEL_KEY,
  decorateDepartmentSpaceRows,
  restoreDepartmentSpaceRows,
} from "./departmentSpaceCreator";

const creator = { id: 7, name: "zhang" };

const owner: PermissionDraftRow = {
  subjectType: "user",
  subjectId: 7,
  subjectName: "zhang",
  modelKey: "manager",
  assigneeId: "a-owner",
  sourceType: "DIRECT",
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

  it("tags the configured responsible user as the creator", () => {
    const [ownerRow, viewerRow] = decorateDepartmentSpaceRows([owner, viewer], creator);
    expect(ownerRow).toMatchObject({ subjectId: 7, modelKey: "manager", sourceType: "creator" });
    expect(viewerRow).toEqual(viewer);
  });

  it("does not show the audit creator when no responsible user is configured", () => {
    const rows = [viewer];
    expect(decorateDepartmentSpaceRows(rows, null)).toBe(rows);
  });

  it("adds a display row only for a configured responsible user whose grant is missing", () => {
    const [first, viewerRow] = decorateDepartmentSpaceRows([viewer], creator);
    expect(first).toMatchObject({
      subjectId: 7,
      subjectName: "zhang",
      modelKey: CREATOR_DISPLAY_MODEL_KEY,
      sourceType: "creator",
      protected: true,
    });
    expect(viewerRow).toEqual(viewer);
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
