export const KUNLIAN_ALL_TENANTS_WILDCARD = "*";

export const KUNLIAN_API_KEY_CAPABILITIES = [
  "read",
  "write",
  "publish",
  "invoke",
  "grant",
] as const;

export type KunlianApiKeyCapability =
  (typeof KUNLIAN_API_KEY_CAPABILITIES)[number];

export interface KunlianApiKeyItem {
  id: number;
  integration_id: string;
  connection_id: string;
  policy_revision: number;
  expires_at: string | null;
  revoked_at: string | null;
  created_by: number;
  create_time: string;
  rotated_from_id: number | null;
  tenant_ids: string[];
  capabilities: KunlianApiKeyCapability[];
  key_mask: string;
}

export interface KunlianApiKeyIssued extends KunlianApiKeyItem {
  api_key: string;
}

export interface KunlianApiKeyIssuePayload {
  connection_id: string;
  integration_id: string;
  tenant_ids: string[];
  capabilities: KunlianApiKeyCapability[];
  expires_at?: string | null;
}

export interface KunlianApiKeyUpdatePayload {
  tenant_ids?: string[];
  capabilities?: KunlianApiKeyCapability[];
  expires_at?: string | null;
}

export interface KunlianIntegrationStatus {
  connection_id?: string | null;
  directory_status?: string;
  projection_status?: string;
  member_count?: number | null;
  unmapped_count?: number | null;
  enabled?: boolean;
  ready?: boolean;
}

export interface KunlianDirectoryTenantItem {
  external_tenant_id: string;
  name: string;
  code: string | null;
  status: string;
  local_tenant_id: number | null;
  binding_enabled: boolean;
  materialized: boolean;
}

export interface KunlianTenantsResponse {
  connection_id: string;
  items: KunlianDirectoryTenantItem[];
}
