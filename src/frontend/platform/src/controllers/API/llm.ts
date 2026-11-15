// Axios wrappers for LLM server CRUD under the Tenant-tree model.
// Global super admins and Child Admins may call POST/PUT/DELETE; the
// backend's get_tenant_admin_user dependency gates access.

import axios from "@/controllers/request";

export interface LLMModelInfo {
  id: number;
  server_id: number;
  name: string;
  description?: string;
  model_name: string;
  model_type: string;
  online: boolean;
  status: number;
  remark?: string;
  tenant_id: number;
  config?: Record<string, unknown>;
}

export interface LLMServerInfo {
  id: number;
  name: string;
  description?: string;
  type: string;
  limit_flag: boolean;
  limit: number;
  tenant_id: number;
  user_id: number;
  config?: Record<string, unknown>;
  models: LLMModelInfo[];
  // True when the caller sees this server via Root → Child share.
  // Drives the readonly Badge + disabled edit buttons on the UI.
  is_root_shared_readonly: boolean;
}

export interface LLMServerUpsertReq {
  id?: number;
  name: string;
  description?: string;
  type: string;
  limit_flag?: boolean;
  limit?: number;
  config?: Record<string, unknown>;
  // Root-only switch; true fans out to all Children via FGA shared_with
  // tuples. Ignored by the backend when the target tenant is not Root.
  share_to_children?: boolean;
  models: Array<{
    id?: number;
    name: string;
    description?: string;
    model_name: string;
    model_type: string;
    online?: boolean;
    config?: Record<string, unknown>;
  }>;
}

export async function listLLMServers(): Promise<LLMServerInfo[]> {
  return await axios.get("/api/v1/llm");
}

/** Root-owned servers currently shared to ≥1 Child (mount-preview dialog).
 *  Super-admin only; non-super callers receive HTTP 403. */
export async function listSharedLLMServersForMountPreview(): Promise<
  LLMServerInfo[]
> {
  return await axios.get("/api/v1/llm", { params: { only_shared: true } });
}

export async function getLLMServerDetail(
  serverId: number,
): Promise<LLMServerInfo> {
  return await axios.get("/api/v1/llm/info", {
    params: { server_id: serverId },
  });
}

export async function createLLMServer(
  req: LLMServerUpsertReq,
): Promise<LLMServerInfo> {
  return await axios.post("/api/v1/llm", req);
}

export async function updateLLMServer(
  req: LLMServerUpsertReq,
  control?: ModelRemovalControl,
): Promise<LLMServerInfo> {
  if (!control) return await axios.put("/api/v1/llm", req);
  return await axios.put("/api/v1/llm", req, {
    params: control,
    showError: false,
  });
}

export async function deleteLLMServer(
  serverId: number,
  control?: ModelRemovalControl,
): Promise<void> {
  if (!control)
    return await axios.delete("/api/v1/llm", { data: { server_id: serverId } });
  return await axios.delete("/api/v1/llm", {
    data: { server_id: serverId },
    params: control,
    showError: false,
  });
}

export async function setModelOnline(
  modelId: number,
  online: boolean,
): Promise<LLMModelInfo> {
  return await axios.post("/api/v1/llm/online", { model_id: modelId, online });
}

export type ModelReferenceSourceType =
  | "workflow_version"
  | "assistant"
  | "hosted_app_version"
  | "channel_sync"
  | "knowledge"
  | "model_default";
export type ModelReferenceCounts = Array<[ModelReferenceSourceType, number]>;
export interface ModelReferenceSource {
  disclosure: {
    source: {
      tenant_id: number;
      source_type: ModelReferenceSourceType;
      source_id: string;
      source_version: string;
    };
    name: string;
    version_label: string | null;
    entry: string | null;
  };
  matched_slot_count: number;
}
export interface ModelReferencePage {
  data: ModelReferenceSource[];
  page_size: number;
  has_more: boolean;
  next_cursor: string | null;
}
export interface ModelRemovalInspection {
  server_id: number;
  targets: Array<{ target_type: "model"; target_id: string }>;
  source_counts: ModelReferenceCounts;
  slot_counts: ModelReferenceCounts;
  restricted_counts: ModelReferenceCounts;
  qualified_counts: ModelReferenceCounts;
  source_page: ModelReferencePage;
  blocked: boolean;
  check_complete: boolean;
}
export interface ModelRemovalPrecheck {
  inspection: ModelRemovalInspection;
  confirmation: {
    confirmation_id: string;
    operation: "model_update_server" | "model_delete_server";
    plan_digest: string;
    expires_at: string;
  };
}
export interface ModelRemovalControl {
  force: boolean;
  confirmation_id: string;
  plan_digest: string;
}
export interface ModelRemovalSourceQuery {
  server_id: number;
  retained_model_ids: number[];
  delete_server: boolean;
  cursor?: string;
  page_size: number;
}
export type LLMServerDraftRequest = Omit<
  LLMServerUpsertReq,
  "id" | "models"
> & {
  id?: number | null;
  models: Array<
    Omit<LLMServerUpsertReq["models"][number], "id"> & {
      id?: number | string | null;
    }
  >;
};

/** Mirror the original editor's temporary-ID handling without mutating its draft. */
export function snapshotModelUpdate(
  draft: LLMServerDraftRequest,
): LLMServerUpsertReq {
  const copy = structuredClone(draft);
  return {
    ...copy,
    id: copy.id ?? undefined,
    models: copy.models.map(({ id, ...model }) =>
      typeof id === "number" ? { ...model, id } : model,
    ),
  };
}

export async function precheckLLMServerUpdate(
  server: LLMServerUpsertReq,
): Promise<ModelRemovalPrecheck> {
  return await axios.post("/api/v1/llm/removal-plan", server, {
    showError: false,
  });
}
export async function precheckLLMServerDelete(
  serverId: number,
): Promise<ModelRemovalPrecheck> {
  return await axios.post(
    "/api/v1/llm/server-removal-plan",
    { server_id: serverId },
    { showError: false },
  );
}
export async function listLLMRemovalSources(
  query: ModelRemovalSourceQuery,
): Promise<ModelReferencePage> {
  return await axios.post("/api/v1/llm/removal-sources", query, {
    showError: false,
  });
}
