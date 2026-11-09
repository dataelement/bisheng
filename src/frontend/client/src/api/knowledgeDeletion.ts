import request from "./request";
import { KnowledgeProcessingApiError, type OperationPrecheck } from "./knowledgeProcessing";
type Envelope<T> = { status_code: number; status_message: string; data: T };
function unwrap<T>(value: Envelope<T>): T {
  if (value.status_code !== 200) throw new KnowledgeProcessingApiError(value);
  return value.data;
}
type ScopedResponse<T> = { headers: Record<string, unknown>; data: Envelope<T> };
const changed = () => Object.assign(new Error("management_scope_changed"), { status_code: 19704 });
export async function readDeletionTenant(
  command: DeleteCommand,
): Promise<{ tenant: string; inspection: ReferenceInspection }> {
  const response =
    command.kind === "files"
      ? await request.postResponse<ScopedResponse<ReferenceInspection>>(
          `/api/v1/knowledge/space/${command.spaceId}/files/references`,
          { items: command.items },
        )
      : await request.getResponse<ScopedResponse<ReferenceInspection>>(
          `/api/v1/knowledge/space/${command.spaceId}/references`,
        );
  const inspection = unwrap(response.data);
  const tenant = String(response.headers["x-management-tenant"] ?? "");
  if (!/^[1-9][0-9]*$/.test(tenant) || !Number.isSafeInteger(Number(tenant))) throw changed();
  return { tenant, inspection };
}
function scoped<T>(response: ScopedResponse<T>, pin?: string): T {
  if (!pin || String(response.headers["x-management-tenant"] ?? "") !== pin) throw changed();
  return unwrap(response.data);
}
const post = async <T,>(url: string, body?: unknown, pin?: string): Promise<T> => {
  if (!pin) throw changed();
  return scoped(
    await request.postResponse<ScopedResponse<T>>(url, body, {
      headers: { "X-Management-Tenant": pin },
    }),
    pin,
  );
};
const get = async <T,>(url: string, params?: Record<string, string>, pin?: string): Promise<T> => {
  if (!pin) throw changed();
  return scoped(
    await request.getResponse<ScopedResponse<T>>(url, {
      params,
      headers: { "X-Management-Tenant": pin },
    }),
    pin,
  );
};
export type DeleteItem = Readonly<{ id: number; type: "file" | "folder" }>;
export type DeleteCommand = Readonly<{
  spaceId: number;
  kind: "files" | "delete" | "clear";
  items?: readonly DeleteItem[];
}>;
export type ReferenceRow = {
  disclosure: {
    source: {
      tenant_id: number;
      source_type: string;
      source_id: string;
      source_version: string | null;
    };
    name: string;
    version_label: string | null;
    entry: string | null;
  };
  matched_slot_count: number;
};
export type ReferencePage = {
  data: ReferenceRow[];
  page_size: number;
  has_more: boolean;
  next_cursor: string | null;
};
export type ReferenceInspection = {
  check_complete: boolean;
  blocked: boolean;
  source_counts: Record<string, number>;
  slot_counts: Record<string, number>;
  restricted_counts: Record<string, number>;
  source_page: ReferencePage;
};
export type DeleteImpact = {
  source_counts: Record<string, number>;
  restricted_counts: Record<string, number>;
  source_page: ReferencePage;
  file_count: number;
};
export type DeletePrecheck = Omit<OperationPrecheck, "impact"> & { impact: DeleteImpact };
export type DeleteConfirmation = Readonly<{
  idempotency_key: string;
  confirmation_id: string;
  plan_digest: string;
}>;
export type DeletionStatus = {
  job_id: string;
  state: string;
  reused?: boolean;
  accepted?: boolean;
  business_phase?: string;
  completed_steps?: string[];
};
const path = (id: number) => `/api/v1/knowledge/space/${id}`;
export function precheckDeletion(
  command: DeleteCommand,
  force = false,
  pin?: string,
): Promise<DeletePrecheck> {
  if (force && command.kind !== "delete") return Promise.reject(new Error("invalid_force"));
  const suffix = command.kind === "files" ? "files/delete" : command.kind;
  return post(
    `${path(command.spaceId)}/${suffix}/precheck`,
    command.kind === "files"
      ? { items: command.items }
      : command.kind === "delete"
        ? { force }
        : undefined,
    pin,
  );
}
export function confirmDeletion(
  spaceId: number,
  body: DeleteConfirmation,
  pin?: string,
): Promise<DeletionStatus> {
  return post(`${path(spaceId)}/deletion/confirm`, body, pin);
}
export function getDeletionStatus(
  spaceId: number,
  jobId: string,
  pin?: string,
): Promise<DeletionStatus> {
  return get(`${path(spaceId)}/deletion/${encodeURIComponent(jobId)}`, undefined, pin);
}
export function inspectReferences(
  command: DeleteCommand,
  pin?: string,
): Promise<ReferenceInspection> {
  return command.kind === "files"
    ? post(`${path(command.spaceId)}/files/references`, { items: command.items }, pin)
    : get(`${path(command.spaceId)}/references`, undefined, pin);
}
export function pageReferences(
  command: DeleteCommand,
  cursor: string,
  pin?: string,
): Promise<ReferencePage> {
  return command.kind === "files"
    ? post(`${path(command.spaceId)}/files/references`, { items: command.items, cursor }, pin)
    : get(`${path(command.spaceId)}/references`, { cursor }, pin);
}
