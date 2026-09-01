import type {
  GrantablePermissionModel,
  PermissionGrantAssignee,
  ResourcePermissionContext,
} from "~/api/permission";

export function canMutatePermissionAssignee(
  assignee: PermissionGrantAssignee,
  context: ResourcePermissionContext,
  grantableModels: GrantablePermissionModel[],
): boolean {
  return (
    context.mode === "CUSTOM" &&
    context.can_manage_permission &&
    assignee.scope === "LOCAL" &&
    assignee.editable &&
    !assignee.protected &&
    grantableModels.some((model) => model.key === assignee.model.key)
  );
}
