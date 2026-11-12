import request from "@/controllers/request";
import type { OperationPrecheck } from "./knowledgeSpace";
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
export type DeletePrecheck = Omit<OperationPrecheck, "impact"> & {
  impact: DeleteImpact;
};
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
): Promise<DeletePrecheck> {
  if (force && command.kind !== "delete")
    return Promise.reject(new Error("invalid_force"));
  const suffix = command.kind === "files" ? "files/delete" : command.kind;
  return request.post<unknown, DeletePrecheck>(
    `${path(command.spaceId)}/${suffix}/precheck`,
    command.kind === "files"
      ? { items: command.items }
      : command.kind === "delete"
        ? { force }
        : undefined,
  );
}
export function confirmDeletion(
  spaceId: number,
  body: DeleteConfirmation,
): Promise<DeletionStatus> {
  return request.post<unknown, DeletionStatus>(
    `${path(spaceId)}/deletion/confirm`,
    body,
  );
}
export function getDeletionStatus(
  spaceId: number,
  jobId: string,
): Promise<DeletionStatus> {
  return request.get<unknown, DeletionStatus>(
    `${path(spaceId)}/deletion/${encodeURIComponent(jobId)}`,
    { params: undefined },
  );
}
export function inspectReferences(
  command: DeleteCommand,
): Promise<ReferenceInspection> {
  return command.kind === "files"
    ? request.post<unknown, ReferenceInspection>(
        `${path(command.spaceId)}/files/references`,
        { items: command.items },
      )
    : request.get<unknown, ReferenceInspection>(
        `${path(command.spaceId)}/references`,
        { params: undefined },
      );
}
export function pageReferences(
  command: DeleteCommand,
  cursor: string,
): Promise<ReferencePage> {
  return command.kind === "files"
    ? request.post<unknown, ReferencePage>(
        `${path(command.spaceId)}/files/references`,
        { items: command.items, cursor },
      )
    : request.get<unknown, ReferencePage>(
        `${path(command.spaceId)}/references`,
        { params: { cursor } },
      );
}
