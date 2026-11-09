import request from "@/controllers/request";
import { managementRequestScope } from "@/controllers/managementScope";
import type { OperationPrecheck } from "./knowledgeSpace";
export type BatchKind = "download" | "tag" | "retry";
export type BatchItem = { id: number; type: "file" | "folder"; name?: string };
export type BatchCommand = {
  spaceId: number;
  operation: BatchKind;
  items: readonly BatchItem[];
  tag_ids?: number[];
  new_tag_names?: string[];
};
export type BatchInspection = Pick<
  OperationPrecheck,
  | "can_execute"
  | "check_complete"
  | "valid_items"
  | "invalid_items"
  | "requires_skip_confirmation"
  | "impact"
>;
export type BatchResult = {
  confirmation_id: string;
  operation: BatchKind;
  reused: boolean;
  url?: string;
  items: {
    id: number;
    type: "file" | "folder";
    state: "succeeded" | "accepted" | "pending_dispatch" | "running" | "skipped" | "failed";
  }[];
};
export type BatchConfirmation = {
  confirmation_id: string;
  plan_digest: string;
  idempotency_key: string;
};
const path = (command: BatchCommand) =>
  `/api/v1/knowledge/space/${command.spaceId}/files/batch/${command.operation}`;
function body(command: BatchCommand) {
  return {
    items: command.items.map(({ id, type }) => ({ id, type })),
    ...(command.operation === "tag"
      ? { tag_ids: command.tag_ids ?? [], new_tag_names: command.new_tag_names ?? [] }
      : {}),
  };
}

export async function inspectBatch(
  command: BatchCommand,
): Promise<{ inspection: BatchInspection; tenant: string }> {
  const inspection = await request.post<unknown, BatchInspection>(
    `${path(command)}/inspect`,
    body(command),
  );
  const tenant = managementRequestScope();
  if (tenant === null) throw new Error("management_scope_unavailable");
  return { inspection, tenant: String(tenant) };
}
export function precheckBatch(command: BatchCommand, tenant: string): Promise<OperationPrecheck> {
  return request.post<unknown, OperationPrecheck>(`${path(command)}/precheck`, body(command), {
    headers: { "X-Management-Tenant": tenant },
  });
}
export function confirmBatch(
  command: BatchCommand,
  confirmation: BatchConfirmation,
  tenant: string,
): Promise<BatchResult> {
  return request.post<unknown, BatchResult>(`${path(command)}/confirm`, confirmation, {
    headers: { "X-Management-Tenant": tenant },
  });
}
