/** @jest-environment node */

import type {
  GrantablePermissionModel,
  PermissionGrantAssignee,
  ResourcePermissionContext,
} from "~/api/permission";
import { canMutatePermissionAssignee } from "./assigneePolicy";

const context: ResourcePermissionContext = {
  mode: "CUSTOM",
  parent_type: null,
  parent_id: null,
  resource_version: 1,
  catalog_release_id: 1,
  projection_state: "FINALIZED",
  can_manage_permission: true,
};

const assignee: PermissionGrantAssignee = {
  assignee_id: "1",
  assignee_version: 1,
  subject: { type: "user", id: "1", name: "Alice" },
  model: { key: "owner", name: "Owner", level: 4, active: true },
  source: { type: "DIRECT", include_children: false },
  scope: "LOCAL",
  inherited_from: null,
  protected: false,
  editable: true,
};

const grantableModels: GrantablePermissionModel[] = [
  { key: "viewer", name: "Viewer", level: 1, active: true },
];

describe("canMutatePermissionAssignee", () => {
  it("rejects an otherwise editable assignee whose model is not grantable", () => {
    expect(
      canMutatePermissionAssignee(assignee, context, grantableModels),
    ).toBe(false);
  });

  it("accepts an editable local assignee whose model is grantable", () => {
    expect(
      canMutatePermissionAssignee(
        { ...assignee, model: grantableModels[0] },
        context,
        grantableModels,
      ),
    ).toBe(true);
  });
});
