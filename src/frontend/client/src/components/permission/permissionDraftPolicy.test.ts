/** @jest-environment node */

import type { RelationModelOption } from "./RelationSelect";
import type { PermissionDraftRow } from "./usePermissionDraft";
import { canMutatePermissionDraftRow } from "./permissionDraftPolicy";

const ownerRow: PermissionDraftRow = {
  subjectType: "user",
  subjectId: 1,
  subjectName: "Alice",
  modelKey: "owner",
  modelName: "Owner",
  modelLevel: 4,
  assigneeId: "1",
  assigneeVersion: 1,
  sourceType: "DIRECT",
  scope: "LOCAL",
  protected: false,
  editable: true,
};

const grantableModels: RelationModelOption[] = [
  { id: "viewer", name: "Viewer", level: 1 },
];

describe("canMutatePermissionDraftRow", () => {
  it("rejects an owner row when owner is not grantable", () => {
    expect(
      canMutatePermissionDraftRow(ownerRow, true, grantableModels),
    ).toBe(false);
  });

  it("accepts a local row whose current model is grantable", () => {
    expect(
      canMutatePermissionDraftRow(
        {
          ...ownerRow,
          modelKey: "viewer",
          modelName: "Viewer",
          modelLevel: 1,
        },
        true,
        grantableModels,
      ),
    ).toBe(true);
  });

  it("rejects inherited and protected rows even when their model is grantable", () => {
    const viewerRow = {
      ...ownerRow,
      modelKey: "viewer",
      modelName: "Viewer",
      modelLevel: 1,
    };

    expect(
      canMutatePermissionDraftRow(
        { ...viewerRow, scope: "INHERITED" },
        true,
        grantableModels,
      ),
    ).toBe(false);
    expect(
      canMutatePermissionDraftRow(
        { ...viewerRow, protected: true },
        true,
        grantableModels,
      ),
    ).toBe(false);
  });
});
