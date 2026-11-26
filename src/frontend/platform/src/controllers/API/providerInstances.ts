import request from "../request";

export type ProviderInstance = {
  id: number;
  endpoint: string;
  remote_scope_id: string;
  state: string;
  capability_revision: number;
  has_api_key: boolean;
  has_upload_signed_token_secret: boolean;
};

export type ProviderInstanceWrite = {
  endpoint: string;
  remote_scope_id: string;
  api_key: string;
  upload_signed_token_secret?: string;
};

export type ProviderInstanceUpdate = {
  endpoint: string;
  remote_scope_id: string;
  api_key?: string;
  upload_signed_token_secret?: string;
};

function asInstance(row: Record<string, unknown>): ProviderInstance {
  if (
    typeof row.id !== "number" ||
    typeof row.endpoint !== "string" ||
    typeof row.remote_scope_id !== "string" ||
    typeof row.state !== "string" ||
    typeof row.capability_revision !== "number" ||
    typeof row.has_api_key !== "boolean" ||
    typeof row.has_upload_signed_token_secret !== "boolean"
  ) {
    throw new Error("Invalid provider instance");
  }
  return {
    id: row.id,
    endpoint: row.endpoint,
    remote_scope_id: row.remote_scope_id,
    state: row.state,
    capability_revision: row.capability_revision,
    has_api_key: row.has_api_key,
    has_upload_signed_token_secret: row.has_upload_signed_token_secret,
  };
}

export async function listProviderInstances(): Promise<ProviderInstance[]> {
  const rows = await request.get("/api/v1/knowledge/provider-instances");
  if (!Array.isArray(rows)) throw new Error("Invalid provider instance list");
  return rows.map(asInstance);
}

export async function createProviderInstance(body: ProviderInstanceWrite): Promise<ProviderInstance> {
  return asInstance(await request.post("/api/v1/knowledge/provider-instances", body));
}

export async function updateProviderInstance(id: number, body: ProviderInstanceUpdate): Promise<ProviderInstance> {
  return asInstance(await request.patch(`/api/v1/knowledge/provider-instances/${id}`, body));
}
