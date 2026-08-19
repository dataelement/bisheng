import axios from "@/controllers/request";

export type FileChangePolicyScope = "all_spaces" | "per_space";

export interface KnowledgeSpaceFileChangePolicy {
  enabled: boolean;
  scope: FileChangePolicyScope;
}

export interface KnowledgeSpaceFileChangePolicyPayload {
  enabled: boolean;
  scope: FileChangePolicyScope;
}

export interface KnowledgeSpaceFileChangeSetting {
  space_id: number;
  name: string;
  auth_type: string;
  space_kind: "normal" | "department";
  approval_required: boolean;
  effective_required: boolean;
}

export interface KnowledgeSpaceFileChangeSettingsPage {
  data: KnowledgeSpaceFileChangeSetting[];
  total: number;
}

export interface FileChangeSettingsQuery {
  keyword?: string;
  page: number;
  page_size: number;
}

export interface KnowledgeSpaceFileChangeSettingPayload {
  approval_required: boolean;
}

export interface KnowledgeSpaceFileChangeSettingBulkItem
  extends KnowledgeSpaceFileChangeSettingPayload {
  space_id: number;
}

export interface KnowledgeSpaceFileChangeConfigurationPayload {
  policy?: KnowledgeSpaceFileChangePolicyPayload;
  settings: KnowledgeSpaceFileChangeSettingBulkItem[];
}

export interface KnowledgeSpaceFileChangeConfigurationResult {
  policy: KnowledgeSpaceFileChangePolicy;
  settings: KnowledgeSpaceFileChangeSetting[];
}

export async function getFileChangePolicyApi(): Promise<KnowledgeSpaceFileChangePolicy> {
  return await axios.get("/api/v1/knowledge/space/admin/file-change-policy");
}

export async function updateFileChangePolicyApi(
  payload: KnowledgeSpaceFileChangePolicyPayload,
): Promise<KnowledgeSpaceFileChangePolicy> {
  return await axios.put(
    "/api/v1/knowledge/space/admin/file-change-policy",
    payload,
  );
}

export async function getFileChangeSettingsApi(
  query: FileChangeSettingsQuery,
): Promise<KnowledgeSpaceFileChangeSettingsPage> {
  return await axios.get("/api/v1/knowledge/space/admin/file-change-settings", {
    params: query,
  });
}

export async function updateFileChangeSettingApi(
  spaceId: number,
  payload: KnowledgeSpaceFileChangeSettingPayload,
): Promise<KnowledgeSpaceFileChangeSetting> {
  return await axios.put(
    `/api/v1/knowledge/space/admin/file-change-settings/${spaceId}`,
    payload,
  );
}

export async function updateFileChangeConfigurationApi(
  payload: KnowledgeSpaceFileChangeConfigurationPayload,
): Promise<KnowledgeSpaceFileChangeConfigurationResult> {
  return await axios.put(
    "/api/v1/knowledge/space/admin/file-change-configuration",
    payload,
  );
}
