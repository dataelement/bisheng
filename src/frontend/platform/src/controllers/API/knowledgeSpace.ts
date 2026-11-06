import axios from "@/controllers/request";
import type { PermissionGrantSubjectInput } from "./permission";

export interface KnowledgeSpaceSummary {
  id: number;
  name: string;
  description?: string | null;
  space_kind?: "normal" | "department";
  department_id?: number | null;
  department_name?: string | null;
}

export async function getManagedKnowledgeSpacesApi(params?: {
  order_by?: string;
}): Promise<KnowledgeSpaceSummary[]> {
  return await axios.get<unknown, KnowledgeSpaceSummary[]>(
    `/api/v1/knowledge/space/managed`,
    {
      params: {
        order_by: params?.order_by,
      },
    },
  );
}

export async function batchCreateDepartmentKnowledgeSpacesApi(
  departmentIds: number[],
): Promise<KnowledgeSpaceSummary[]> {
  return await axios.post<unknown, KnowledgeSpaceSummary[]>(
    `/api/v1/knowledge/space/department/batch-create`,
    {
      items: departmentIds.map((departmentId) => ({
        department_id: departmentId,
      })),
    },
  );
}

/**
 * F041: list the knowledge spaces selectable by the config author.
 * Matches the client daily-mode 口径 = "我创建的 + 我加入的 + 部门知识空间" (dedup union
 * of /mine + /joined + /department), NOT including the knowledge square. Loaded in one
 * shot with client-side name filtering (these endpoints are INV-6 exceptions, full-return).
 */
export async function getSelectableKnowledgeSpacesApi(): Promise<
  KnowledgeSpaceSummary[]
> {
  const results = await Promise.all([
    axios.get<unknown, KnowledgeSpaceSummary[]>(`/api/v1/knowledge/space/mine`),
    axios.get<unknown, KnowledgeSpaceSummary[]>(
      `/api/v1/knowledge/space/joined`,
    ),
    axios.get<unknown, KnowledgeSpaceSummary[]>(
      `/api/v1/knowledge/space/department`,
    ),
  ]);
  const byId = new Map<number, KnowledgeSpaceSummary>();
  results.flat().forEach((space: KnowledgeSpaceSummary) => {
    if (space && space.id != null && !byId.has(space.id)) {
      byId.set(space.id, space);
    }
  });
  return Array.from(byId.values());
}

export interface PageData<T> {
  data: T[];
  total: number;
}
export interface CursorPage<T> {
  data: T[];
  page_size: number;
  has_more: boolean;
  next_cursor: string | null;
}

export interface KnowledgeSpaceInfo extends KnowledgeSpaceSummary {
  user_id?: number | null;
  tenant_id?: number | null;
  type?: number;
  model?: string | null;
  collection_name?: string | null;
  index_name?: string | null;
  state?: number | null;
  is_released?: boolean;
  auth_type?: "public" | "private" | "approval";
  is_shared?: boolean;
  auto_tag_enabled?: boolean;
  auto_tag_library_id?: number | null;
  metadata_fields?: Readonly<Record<string, unknown>>[] | null;
  create_time?: string | null;
  update_time?: string | null;
  user_name?: string;
  actions?: string[] | null;
  is_pinned?: boolean;
  is_followed?: boolean;
  subscription_status?:
    "subscribed" | "pending" | "rejected" | "not_subscribed";
  user_role?: "creator" | "admin" | "member" | null;
  avatar?: string | null;
  follower_num?: number;
  file_num?: number;
  is_pending?: boolean;
  approval_enabled?: boolean | null;
  sensitive_check_enabled?: boolean | null;
  is_hidden?: boolean | null;
  auto_tag_mode?: "library" | "custom";
  auto_tag_custom_tags?: string[] | null;
}

export interface KnowledgeSpaceChild {
  id: number;
  knowledge_id: number;
  file_name: string;
  user_id?: number | null;
  user_name?: string | null;
  thumbnails?: string | null;
  file_type?: number;
  file_source?: string | null;
  level?: number | null;
  file_level_path?: string | null;
  abstract?: string | null;
  file_size?: number | null;
  md5?: string | null;
  parse_type?: string | null;
  split_rule?: string | null;
  preview_file_object_name?: string | null;
  bbox_object_name?: string | null;
  status?: number | null;
  object_name?: string | null;
  user_metadata?: Readonly<Record<string, unknown>> | null;
  remark?: string | null;
  file_encoding?: string | null;
  simhash?: string | null;
  similar_status?: number;
  updater_id?: number | null;
  updater_name?: string | null;
  tenant_id?: number | null;
  create_time?: string | null;
  update_time?: string | null;
  old_file_level_path?: string | null;
  approval_request_id?: number | null;
  approval_status?: string | null;
  approval_reason?: string | null;
  is_pending_approval?: boolean;
  version_no?: number | null;
  is_multi_version?: boolean;
  has_similar?: boolean;
}

export interface KnowledgeChildrenQuery {
  parent_id?: number | null;
  file_ids?: number[];
  order_field?:
    "file_type" | "file_name" | "file_size" | "update_time" | "create_time";
  order_sort?: "asc" | "desc" | "ASC" | "DESC";
  file_status?: number[];
  page_size?: number;
  cursor?: string | null;
  file_type?: 0 | 1 | null;
}

export interface KnowledgePageQuery {
  page: number;
  page_size: number;
}
export interface KnowledgeAdminQuery extends KnowledgePageQuery {
  keyword?: string;
}
export interface KnowledgeVisibleQuery {
  keyword?: string;
  page_size?: number;
  cursor?: string | null;
}
export interface KnowledgeSpaceCreateRequest {
  name: string;
  description?: string | null;
  icon?: string | null;
  auth_type?: "public" | "private" | "approval";
  is_released?: boolean;
  auto_tag_enabled?: boolean;
  auto_tag_library_id?: number | null;
  auto_tag_custom_tags?: string[] | null;
  creation_request_id?: string | null;
  initial_permissions?: {
    expected_catalog_release_id: number;
    grants?: { model_key: string; subject: PermissionGrantSubjectInput }[];
  } | null;
  embedding_model_id?: number | null;
  processing_defaults?: ProcessingDefaults | null;
}
export type KnowledgeSpaceCreateResponse = KnowledgeSpaceInfo & {
  initial_permission_result?: {
    status: "succeeded" | "failed";
    resource_version?: number | null;
    assignee_ids?: string[];
    error_code?: number | null;
    message?: string | null;
  } | null;
};
export interface SpaceCreationSettings {
  embedding_model: { id: string; name: string } | null;
  system_defaults: ProcessingDefaults;
}
export type BinaryFlag = 0 | 1;
export type SplitMode = "auto" | "custom" | "hierarchical";
export type SeparatorRule = "before" | "after";

/** Mirrors processing_settings.py; normalized defaults come only from the server. */
export interface DocumentProcessingRule {
  split_mode: SplitMode;
  separator: string[];
  separator_rule: SeparatorRule[];
  chunk_size: number;
  chunk_overlap: number;
  hierarchy_level: number;
  append_title: boolean;
  max_chunk_size: number;
  retain_images: BinaryFlag;
  force_ocr: BinaryFlag;
  enable_formula: BinaryFlag;
  filter_page_header_footer: BinaryFlag;
}
export interface TableProcessingRule {
  slice_length: number;
  header_start_row: number;
  header_end_row: number;
  append_header: BinaryFlag;
}

/** Actual legacy file snapshot only; new defaults and commands keep positive row counts. */
export interface LegacyTableProcessingRule extends Omit<
  TableProcessingRule,
  "slice_length"
> {
  slice_length: 0;
  legacy_unbounded: true;
}
export type PartialDocumentRule = {
  [K in keyof DocumentProcessingRule]?: DocumentProcessingRule[K] | null;
};
export type PartialTableRule = {
  [K in keyof TableProcessingRule]?: TableProcessingRule[K] | null;
};
export interface ProcessingDefaults {
  schema_version: 1;
  document: DocumentProcessingRule;
  table: TableProcessingRule;
}
export interface ProcessingOverrides {
  document?: PartialDocumentRule | null;
  table?: PartialTableRule | null;
}
export interface ProcessingSettingsRead {
  space_id: number;
  config_version: number;
  saved_defaults: ProcessingDefaults | null;
  effective_defaults: ProcessingDefaults;
}
export interface ProcessingSettingsWrite {
  expected_config_version: number;
  defaults: ProcessingDefaults;
}
export interface EffectiveProcessingSnapshot {
  schema_version: 1;
  file_kind: string;
  effective_rule:
    DocumentProcessingRule | TableProcessingRule | LegacyTableProcessingRule;
  space_config_version: number;
  supplied_fields_by_layer: Partial<
    Record<"system" | "space" | "batch" | "file" | "specialized", string[]>
  >;
}

/** Mirrors processing_job.py; file, document and version IDs remain distinct. */
export type ProcessingKind =
  | "embedding_rebuild"
  | "file_reprocess"
  | "file_resplit"
  | "metadata_schema_change"
  | "move_index"
  | "space_copy";
export type JobState =
  | "accepted"
  | "running"
  | "succeeded"
  | "partial_failed"
  | "failed"
  | "obsolete";
export type ItemState =
  "pending" | "running" | "succeeded" | "failed" | "obsolete";
export interface ResourceVersionTarget {
  file_id: number;
  document_id: number;
  version_id: number;
}
export interface ProcessingTargetInput {
  file_id: number;
  document_id?: number | null;
  version_id: number;
}
export interface EmbeddingRebuildParameters {
  embedding_model_id?: number | null;
}
export interface FileProcessingParameters {
  overrides?: ProcessingOverrides;
}
export type MetadataSchemaChange =
  | {
      operation: "add";
      field_name: string;
      field_type: "string" | "number" | "time";
      new_field_name?: null;
    }
  | {
      operation: "rename";
      field_name: string;
      new_field_name: string;
      field_type?: null;
    }
  | {
      operation: "delete";
      field_name: string;
      field_type?: null;
      new_field_name?: null;
    };
export interface MetadataSchemaParameters {
  expected_schema_revision: number;
  changes: MetadataSchemaChange[];
}
export type ProcessingPrecheckRequest =
  | {
      kind: "embedding_rebuild";
      targets?: null;
      parameters: EmbeddingRebuildParameters;
    }
  | {
      kind: "file_reprocess" | "file_resplit";
      targets: ProcessingTargetInput[];
      parameters: FileProcessingParameters;
    }
  | {
      kind: "metadata_schema_change";
      targets?: null;
      parameters: MetadataSchemaParameters;
    };
export interface ProcessingCreateRequest {
  idempotency_key: string;
  confirmation_id: string;
  plan_digest: string;
}
export interface ProcessingRetryRequest {
  idempotency_key: string;
  expected_job_revision: number;
}
export interface JobAccepted {
  job_id: string;
  accepted: true;
  state: JobState;
  reused: boolean;
}
export interface ProcessingJobRead {
  id: string;
  space_id: number;
  kind: ProcessingKind;
  state: JobState;
  revision: number;
  accepted_at: string;
  started_at: string | null;
  finished_at: string | null;
  total_count: number;
  succeeded_count: number;
  failed_count: number;
  pending_count: number;
  hidden_item_count: number;
  retryable: boolean;
  obsolete_reason: string | null;
  error_code: number | null;
}
export interface ProcessingItemRead {
  id: string;
  file_id: number | null;
  document_id: number | null;
  version_id: number | null;
  step: string;
  state: ItemState;
  attempt: number;
  error_code: number | null;
  message: string | null;
  retryable: boolean;
}
export interface OperationItem {
  id: number;
  type: "file" | "folder" | "space" | "model" | "version";
  name?: string | null;
}
export interface OperationInvalidItem {
  id?: number | null;
  type?: OperationItem["type"] | null;
  name?: string | null;
  reason: string;
  error_code?: number | null;
}
export interface OperationPrecheck {
  confirmation_id: string;
  plan_digest: string;
  expires_at: string;
  check_complete: boolean;
  can_execute: boolean;
  valid_items: OperationItem[];
  invalid_items: OperationInvalidItem[];
  impact: Readonly<Record<string, unknown>>;
  requires_skip_confirmation: boolean;
}
export interface ProcessingJobsQuery extends KnowledgePageQuery {
  kind?: ProcessingKind;
  state?: JobState;
}
export interface ProcessingItemsQuery extends KnowledgePageQuery {
  state?: ItemState;
}

const spacePath = (spaceId: number) => `/api/v1/knowledge/space/${spaceId}`;
const jobsPath = (spaceId: number) => `${spacePath(spaceId)}/processing-jobs`;

export function listVisibleSpaces(
  query: KnowledgeVisibleQuery = {},
): Promise<CursorPage<KnowledgeSpaceInfo>> {
  return axios.get<unknown, CursorPage<KnowledgeSpaceInfo>>(
    "/api/v1/knowledge/space/list",
    { params: query },
  );
}
export function getCreationSettings(): Promise<SpaceCreationSettings> {
  return axios.get<unknown, SpaceCreationSettings>(
    "/api/v1/knowledge/space/creation-settings",
  );
}
export async function createSpace(
  body: KnowledgeSpaceCreateRequest,
  expectedManagementTenantId: number | null,
): Promise<KnowledgeSpaceCreateResponse> {
  if (
    body.embedding_model_id != null &&
    (!Number.isSafeInteger(body.embedding_model_id) ||
      body.embedding_model_id <= 0)
  ) {
    throw Object.assign(new Error("knowledge_embedding_model_invalid"), {
      code: "knowledge_embedding_model_invalid",
    });
  }
  if (body.embedding_model_id != null || body.processing_defaults != null) {
    if (
      !Number.isSafeInteger(expectedManagementTenantId) ||
      expectedManagementTenantId === null ||
      expectedManagementTenantId <= 0
    ) {
      throw Object.assign(new Error("knowledge_management_tenant_required"), {
        code: "knowledge_management_tenant_required",
      });
    }
    return axios.post<unknown, KnowledgeSpaceCreateResponse>(
      "/api/v1/knowledge/space",
      body,
      {
        headers: { "X-Management-Tenant": String(expectedManagementTenantId) },
      },
    );
  }
  return axios.post<unknown, KnowledgeSpaceCreateResponse>(
    "/api/v1/knowledge/space",
    body,
  );
}
export function getSpaceInfo(spaceId: number): Promise<KnowledgeSpaceInfo> {
  return axios.get<unknown, KnowledgeSpaceInfo>(`${spacePath(spaceId)}/info`);
}
export function listChildren(
  spaceId: number,
  query: KnowledgeChildrenQuery = {},
): Promise<CursorPage<KnowledgeSpaceChild>> {
  return axios.get<unknown, CursorPage<KnowledgeSpaceChild>>(
    `${spacePath(spaceId)}/children`,
    { params: query },
  );
}
export function listAdminSpaces(
  query: KnowledgeAdminQuery,
): Promise<PageData<KnowledgeSpaceInfo>> {
  return axios.get<unknown, PageData<KnowledgeSpaceInfo>>(
    "/api/v1/knowledge/space/admin/list",
    { params: query },
  );
}
export function getProcessingSettings(
  spaceId: number,
): Promise<ProcessingSettingsRead> {
  return axios.get<unknown, ProcessingSettingsRead>(
    `${spacePath(spaceId)}/processing-settings`,
  );
}
export function updateProcessingSettings(
  spaceId: number,
  request: ProcessingSettingsWrite,
): Promise<ProcessingSettingsRead> {
  return axios.put<unknown, ProcessingSettingsRead>(
    `${spacePath(spaceId)}/processing-settings`,
    request,
  );
}
export function precheckProcessing(
  spaceId: number,
  request: ProcessingPrecheckRequest,
): Promise<OperationPrecheck> {
  return axios.post<unknown, OperationPrecheck>(
    `${jobsPath(spaceId)}/precheck`,
    request,
  );
}
export function createProcessingJob(
  spaceId: number,
  request: ProcessingCreateRequest,
): Promise<JobAccepted> {
  return axios.post<unknown, JobAccepted>(jobsPath(spaceId), request);
}
export function listProcessingJobs(
  spaceId: number,
  query: ProcessingJobsQuery,
): Promise<PageData<ProcessingJobRead>> {
  return axios.get<unknown, PageData<ProcessingJobRead>>(jobsPath(spaceId), {
    params: query,
  });
}
export function getProcessingJob(
  spaceId: number,
  jobId: string,
): Promise<ProcessingJobRead> {
  return axios.get<unknown, ProcessingJobRead>(
    `${jobsPath(spaceId)}/${encodeURIComponent(jobId)}`,
  );
}
export function listProcessingItems(
  spaceId: number,
  jobId: string,
  query: ProcessingItemsQuery,
): Promise<PageData<ProcessingItemRead>> {
  return axios.get<unknown, PageData<ProcessingItemRead>>(
    `${jobsPath(spaceId)}/${encodeURIComponent(jobId)}/items`,
    { params: query },
  );
}
export function retryProcessingJob(
  spaceId: number,
  jobId: string,
  request: ProcessingRetryRequest,
): Promise<JobAccepted> {
  return axios.post<unknown, JobAccepted>(
    `${jobsPath(spaceId)}/${encodeURIComponent(jobId)}/retry`,
    request,
  );
}

/** Test ports have this exact shape; production always uses the wrapped request module. */
export const knowledgeSpaceApi = {
  listVisibleSpaces,
  getCreationSettings,
  createSpace,
  getSpaceInfo,
  listChildren,
  listAdminSpaces,
  getProcessingSettings,
  updateProcessingSettings,
  precheckProcessing,
  createProcessingJob,
  listProcessingJobs,
  getProcessingJob,
  listProcessingItems,
  retryProcessingJob,
};
export type KnowledgeSpaceApi = typeof knowledgeSpaceApi;
