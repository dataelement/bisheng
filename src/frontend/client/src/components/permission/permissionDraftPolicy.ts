import type { RelationModelOption } from "./RelationSelect";
import type { PermissionDraftRow } from "./usePermissionDraft";

export function canMutatePermissionDraftRow(
  row: PermissionDraftRow,
  capabilityEnabled: boolean,
  grantableModels: RelationModelOption[],
): boolean {
  return (
    capabilityEnabled &&
    !row.protected &&
    row.editable !== false &&
    row.scope !== "INHERITED" &&
    grantableModels.some((model) => model.id === row.modelKey)
  );
}
