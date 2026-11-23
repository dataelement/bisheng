import request from "@/controllers/request";
import type {
  JobAccepted,
  OperationPrecheck,
  ProcessingCreateRequest,
} from "./knowledgeSpace";

export interface MoveSelection {
  id: number;
  type: "file" | "folder";
}
export interface MoveDestination {
  spaceId: number;
  folderId: number | null;
}
export interface SynchronousMoveResult {
  moved: { id: number; type: string }[];
  invalid: { id: number; type: string; reason: string; name?: string }[];
}
function requireId(value: number) {
  if (!Number.isSafeInteger(value) || value <= 0)
    throw new RangeError("Invalid move resource");
}
function path(spaceId: number) {
  requireId(spaceId);
  return `/api/v1/knowledge/space/${spaceId}/files/move`;
}
export function precheckMove(
  spaceId: number,
  items: readonly MoveSelection[],
  destination: MoveDestination,
  tenantId: number,
): Promise<OperationPrecheck> {
  requireId(tenantId);
  requireId(destination.spaceId);
  if (destination.folderId !== null) requireId(destination.folderId);
  if (!items.length) throw new RangeError("Move requires a selection");
  items.forEach((item) => requireId(item.id));
  return request.post(
    `${path(spaceId)}/precheck`,
    {
      items: items.map(({ id, type }) => ({ id, type })),
      target_space_id: destination.spaceId,
      target_folder_id: destination.folderId,
      skip_invalid: false,
    },
    { headers: { "X-Management-Tenant": String(tenantId) } },
  );
}
export function confirmMove(
  spaceId: number,
  command: ProcessingCreateRequest,
  tenantId: number,
): Promise<JobAccepted | SynchronousMoveResult> {
  requireId(tenantId);
  return request.post(`${path(spaceId)}/confirm`, command, {
    headers: { "X-Management-Tenant": String(tenantId) },
  });
}
