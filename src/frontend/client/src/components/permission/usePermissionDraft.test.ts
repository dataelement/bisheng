/** @jest-environment node */

import {
  createPermissionDraft,
  getPermissionDraftDiff,
  getPermissionDraftRowKey,
  permissionDraftReducer,
  type PermissionDraftRow,
} from "./usePermissionDraft";

const localViewer: PermissionDraftRow = {
  subjectType: "user", subjectId: 7, subjectName: "Ada", modelKey: "viewer",
  assigneeId: "assignee-1", assigneeVersion: 3, sourceType: "DIRECT",
  scope: "LOCAL", editable: true,
};

describe("F048 permission draft", () => {
  it("builds ADD with canonical subject fields", () => {
    const row: PermissionDraftRow = {
      subjectType: "department", subjectId: 8, subjectName: "Platform",
      modelKey: "editor", includeChildren: true,
    };
    const draft = permissionDraftReducer(createPermissionDraft(), { type: "add", row });
    expect(getPermissionDraftDiff(draft).changes).toEqual([{
      op: "ADD", model_key: "editor",
      subject: {
        type: "department", id: "8", userset_relation: "subtree_member",
        include_children: true,
      },
    }]);
  });

  it("builds versioned MOVE and REMOVE changes", () => {
    let draft = createPermissionDraft([localViewer], { resourceVersion: 9, catalogReleaseId: 42 });
    draft = permissionDraftReducer(draft, {
      type: "change", key: getPermissionDraftRowKey(localViewer), changes: { modelKey: "editor" },
    });
    expect(getPermissionDraftDiff(draft).changes).toEqual([{
      op: "MOVE", assignee_id: "assignee-1", expected_assignee_version: 3,
      target_model_key: "editor",
    }]);
    draft = permissionDraftReducer(draft, {
      type: "remove", key: getPermissionDraftRowKey(draft.rows[0]),
    });
    expect(getPermissionDraftDiff(draft).changes).toEqual([{
      op: "REMOVE", assignee_id: "assignee-1", expected_assignee_version: 3,
    }]);
  });

  it("keeps the server baseline when the editor replaces visible rows", () => {
    const baseline = createPermissionDraft([localViewer]);
    const moved = permissionDraftReducer(baseline, {
      type: "replace_rows",
      rows: [{ ...localViewer, modelKey: "editor" }],
    });
    expect(getPermissionDraftDiff(moved).changes).toEqual([{
      op: "MOVE",
      assignee_id: "assignee-1",
      expected_assignee_version: 3,
      target_model_key: "editor",
    }]);

    const removed = permissionDraftReducer(baseline, {
      type: "replace_rows",
      rows: [],
    });
    expect(getPermissionDraftDiff(removed).changes).toEqual([{
      op: "REMOVE",
      assignee_id: "assignee-1",
      expected_assignee_version: 3,
    }]);
  });

  it("keeps protected rows when the editor replaces a subject tab", () => {
    const protectedOwner: PermissionDraftRow = {
      ...localViewer,
      assigneeId: "owner-1",
      modelKey: "owner",
      protected: true,
      editable: false,
    };
    const baseline = createPermissionDraft([protectedOwner, localViewer]);
    const next = permissionDraftReducer(baseline, {
      type: "replace_rows",
      rows: [{ ...localViewer, modelKey: "editor" }],
    });
    expect(next.rows).toContainEqual(protectedOwner);
    expect(getPermissionDraftDiff(next).changes).toHaveLength(1);
  });

  it.each([
    { ...localViewer, protected: true },
    { ...localViewer, scope: "INHERITED" as const },
    { ...localViewer, editable: false },
  ])("does not mutate protected or read-only rows", (row) => {
    const draft = createPermissionDraft([row]);
    expect(permissionDraftReducer(draft, {
      type: "remove", key: getPermissionDraftRowKey(row),
    })).toBe(draft);
  });

  it("keeps the same subject as separate source assignees", () => {
    const rows = [localViewer, { ...localViewer, assigneeId: "assignee-2", sourceType: "DEPARTMENT" }];
    expect(createPermissionDraft(rows).rows).toHaveLength(2);
  });

  it("cancel restores rows and clears changes", () => {
    const baseline = createPermissionDraft([localViewer]);
    const changed = permissionDraftReducer(baseline, {
      type: "remove", key: getPermissionDraftRowKey(localViewer),
    });
    const reset = permissionDraftReducer(changed, { type: "reset" });
    expect(reset.rows).toEqual([localViewer]);
    expect(getPermissionDraftDiff(reset).changes).toEqual([]);
  });
});
