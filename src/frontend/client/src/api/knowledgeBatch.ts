import request from "./request";
import { KnowledgeProcessingApiError, type OperationPrecheck } from "./knowledgeProcessing";
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

type Envelope<T> = { status_code: number; status_message: string; data: T };
type Response<T> = { data: Envelope<T>; headers: Record<string, unknown> };
function unwrap<T>(response: Response<T>, pin?: string): T {
  if (response.data.status_code !== 200) throw new KnowledgeProcessingApiError(response.data);
  const actual = String(response.headers["x-management-tenant"] ?? "");
  if (
    !/^[1-9][0-9]*$/.test(actual) ||
    !Number.isSafeInteger(Number(actual)) ||
    (pin !== undefined && actual !== pin)
  )
    throw Object.assign(new Error("management_scope_changed"), { status_code: 19704 });
  return response.data.data;
}
export async function inspectBatch(
  command: BatchCommand,
): Promise<{ inspection: BatchInspection; tenant: string }> {
  const response = await request.postResponse<Response<BatchInspection>>(
    `${path(command)}/inspect`,
    body(command),
  );
  return { inspection: unwrap(response), tenant: String(response.headers["x-management-tenant"]) };
}
export async function precheckBatch(
  command: BatchCommand,
  tenant: string,
): Promise<OperationPrecheck> {
  return unwrap(
    await request.postResponse<Response<OperationPrecheck>>(
      `${path(command)}/precheck`,
      body(command),
      { headers: { "X-Management-Tenant": tenant } },
    ),
    tenant,
  );
}
export async function confirmBatch(
  command: BatchCommand,
  confirmation: BatchConfirmation,
  tenant: string,
): Promise<BatchResult> {
  return unwrap(
    await request.postResponse<Response<BatchResult>>(`${path(command)}/confirm`, confirmation, {
      headers: { "X-Management-Tenant": tenant },
    }),
    tenant,
  );
}
