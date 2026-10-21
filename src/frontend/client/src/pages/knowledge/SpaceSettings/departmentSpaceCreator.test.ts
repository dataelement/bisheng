/**
 * Department owner rows preserve their real permission model and do not
 * mislabel the configured responsible user as the creation operator.
 */

import type { PermissionDraftRow } from "~/components/permission/usePermissionDraft";
import {
  decorateDepartmentSpaceRows,
  restoreDepartmentSpaceRows,
} from "./departmentSpaceCreator";

const creator = { id: 7, name: "zhang" };

const owner: PermissionDraftRow = {
  subjectType: "user",
  subjectId: 7,
  subjectName: "zhang",
  modelKey: "owner",
  protected: true,
  assigneeId: "a-owner",
  sourceType: "SPACE_MEMBERSHIP",
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

  it("preserves the real owner model without a creator tag", () => {
    const [ownerRow, viewerRow] = decorateDepartmentSpaceRows([owner, viewer], creator);
    expect(ownerRow).toMatchObject({ subjectId: 7, modelKey: "owner", protected: true, sourceType: undefined });
    expect(viewerRow).toEqual(viewer);
  });

  it("does not show the audit creator when no responsible user is configured", () => {
    const rows = [viewer];
    expect(decorateDepartmentSpaceRows(rows, null)).toBe(rows);
  });

  it("does not manufacture an owner when the real grant is missing", () => {
    expect(decorateDepartmentSpaceRows([viewer], creator)).toEqual([viewer]);
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
