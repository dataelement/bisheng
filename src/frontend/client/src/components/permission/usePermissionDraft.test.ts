import { act, renderHook } from "@testing-library/react";
import {
  createPermissionDraft,
  getPermissionDraftDiff,
  getPermissionDraftRowKey,
  permissionDraftReducer,
  usePermissionDraft,
} from "./usePermissionDraft";
import type { PermissionDraftRow } from "./usePermissionDraft";

const creator: PermissionDraftRow = {
  subjectType: "user",
  subjectId: 1,
  subjectName: "Creator",
  relation: "owner",
  modelId: "owner",
  immutableCreator: true,
};

const viewer: PermissionDraftRow = {
  subjectType: "user",
  subjectId: 2,
  subjectName: "Viewer",
  relation: "viewer",
  modelId: "viewer",
};

describe("permissionDraftReducer", () => {
  it("adds, changes and removes rows while tracking both sides of a change", () => {
    const editor: PermissionDraftRow = {
      subjectType: "user_group",
      subjectId: 3,
      subjectName: "Editors",
      relation: "editor",
      modelId: "custom-editor",
    };
    let state = createPermissionDraft([viewer]);

    state = permissionDraftReducer(state, { type: "add", row: editor });
    expect(state.rows).toEqual([viewer, editor]);
    expect(state.touchedKeys).toEqual([getPermissionDraftRowKey(editor)]);

    const viewerKey = getPermissionDraftRowKey(viewer);
    state = permissionDraftReducer(state, {
      type: "change",
      key: viewerKey,
      changes: { relation: "manager", modelId: "manager" },
    });
    const manager = state.rows[0];
    expect(manager).toMatchObject({ relation: "manager", modelId: "manager" });
    expect(state.touchedKeys).toEqual(expect.arrayContaining([
      viewerKey,
      getPermissionDraftRowKey(manager),
      getPermissionDraftRowKey(editor),
    ]));

    state = permissionDraftReducer(state, {
      type: "remove",
      key: getPermissionDraftRowKey(editor),
    });
    expect(state.rows).toEqual([manager]);
  });

  it("keeps creator rows immutable", () => {
    const state = createPermissionDraft([creator, viewer]);
    const creatorKey = getPermissionDraftRowKey(creator);

    const changed = permissionDraftReducer(state, {
      type: "change",
      key: creatorKey,
      changes: { relation: "viewer", modelId: "viewer" },
    });
    const removed = permissionDraftReducer(state, { type: "remove", key: creatorKey });

    expect(changed).toBe(state);
    expect(removed).toBe(state);
  });

  it("uses relation, model and department scope in the stable key", () => {
    const department: PermissionDraftRow = {
      subjectType: "department",
      subjectId: 8,
      subjectName: "Platform",
      relation: "viewer",
      modelId: "viewer-a",
      includeChildren: false,
    };

    expect(getPermissionDraftRowKey({ ...department, relation: "editor" }))
      .not.toBe(getPermissionDraftRowKey(department));
    expect(getPermissionDraftRowKey({ ...department, modelId: "viewer-b" }))
      .not.toBe(getPermissionDraftRowKey(department));
    expect(getPermissionDraftRowKey({ ...department, includeChildren: true }))
      .not.toBe(getPermissionDraftRowKey(department));
  });

  it("emits only touched grants and revokes", () => {
    const untouchedConcurrentRow: PermissionDraftRow = {
      subjectType: "user",
      subjectId: 99,
      subjectName: "Concurrent member",
      relation: "viewer",
    };
    let state = createPermissionDraft([viewer, untouchedConcurrentRow]);
    state = permissionDraftReducer(state, {
      type: "change",
      key: getPermissionDraftRowKey(viewer),
      changes: { relation: "editor", modelId: "editor" },
    });

    expect(getPermissionDraftDiff(state)).toEqual({
      grants: [{
        subject_type: "user",
        subject_id: 2,
        relation: "editor",
        model_id: "editor",
      }],
      revokes: [{
        subject_type: "user",
        subject_id: 2,
        relation: "viewer",
      }],
    });
  });
});

describe("usePermissionDraft", () => {
  it("resets/cancels local edits without producing a write diff", () => {
    const { result } = renderHook(() => usePermissionDraft([viewer]));

    act(() => {
      result.current.removeRow(getPermissionDraftRowKey(viewer));
    });
    expect(result.current.diff.revokes).toHaveLength(1);

    act(() => {
      result.current.cancel();
    });
    expect(result.current.rows).toEqual([viewer]);
    expect(result.current.diff).toEqual({ grants: [], revokes: [] });
    expect(result.current.hasChanges).toBe(false);
  });

  it("can replace the baseline after a server refresh", () => {
    const { result } = renderHook(() => usePermissionDraft([viewer]));

    act(() => {
      result.current.reset([creator]);
    });

    expect(result.current.draft).toEqual(createPermissionDraft([creator]));
  });
});
