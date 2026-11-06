import request from "./request";
import type { RawSpaceChild } from "./knowledge";

// Wire types mirror knowledge/domain/schemas/processing_{settings,job}.py.
export type BinaryFlag = 0 | 1;
export type SplitMode = "auto" | "custom" | "hierarchical";
export type SeparatorRule = "before" | "after";

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

export type PartialDocumentRule = { [K in keyof DocumentProcessingRule]?: DocumentProcessingRule[K] | null };
export type PartialTableRule = { [K in keyof TableProcessingRule]?: TableProcessingRule[K] | null };

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
  effective_rule: DocumentProcessingRule | TableProcessingRule;
  space_config_version: number;
  supplied_fields_by_layer: Partial<Record<"system" | "space" | "batch" | "file" | "specialized", string[]>>;
}

export type ProcessingKind = "embedding_rebuild" | "file_reprocess" | "file_resplit" | "metadata_schema_change" | "move_index" | "space_copy";
export type JobState = "accepted" | "running" | "succeeded" | "partial_failed" | "failed" | "obsolete";
export type ItemState = "pending" | "running" | "succeeded" | "failed" | "obsolete";

export interface ResourceVersionTarget {
  file_id: number;
  document_id: number;
  version_id: number;
}

export interface ProcessingTargetInput {
  file_id: number;
  version_id: number;
  document_id?: number | null;
}

export interface EmbeddingRebuildParameters {
  embedding_model_id?: number | null;
}

export interface FileProcessingParameters {
  overrides?: ProcessingOverrides;
}

export type MetadataSchemaChange =
  | { operation: "add"; field_name: string; field_type: "string" | "number" | "time"; new_field_name?: null }
  | { operation: "rename"; field_name: string; new_field_name: string; field_type?: null }
  | { operation: "delete"; field_name: string; field_type?: null; new_field_name?: null };

export interface MetadataSchemaParameters {
  expected_schema_revision: number;
  changes: MetadataSchemaChange[];
}

export type ProcessingPrecheckRequest =
  | { kind: "embedding_rebuild"; targets?: null; parameters: EmbeddingRebuildParameters }
  | { kind: "file_reprocess" | "file_resplit"; targets: ProcessingTargetInput[]; parameters: FileProcessingParameters }
  | { kind: "metadata_schema_change"; targets?: null; parameters: MetadataSchemaParameters };

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

export type OperationItemType = "file" | "folder" | "space" | "model" | "version";
export interface OperationItem {
  id: number;
  type: OperationItemType;
  name: string | null;
}

export interface OperationInvalidItem {
  id?: number | null;
  type?: OperationItemType | null;
  name?: string | null;
  reason: string;
  error_code: number | null;
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

// Existing space endpoints remain raw wire reads; their UI mapping stays in knowledge.ts.
export interface KnowledgeSpaceRead {
  id: number;
  name: string;
  type: number;
  user_id?: number | null;
  tenant_id?: number | null;
  description?: string | null;
  model?: string | null;
  collection_name?: string | null;
  index_name?: string | null;
  state?: number | null;
  is_released?: boolean;
  auth_type?: "public" | "private";
  is_shared?: boolean;
  auto_tag_enabled?: boolean;
  auto_tag_library_id?: number | null;
  metadata_fields?: Record<string, unknown>[] | null;
  create_time?: string | null;
  update_time?: string | null;
  user_name?: string;
  actions?: string[] | null;
  is_pinned?: boolean;
  is_followed?: boolean;
  subscription_status?: "subscribed" | "pending" | "rejected" | "not_subscribed";
  user_role?: string | null;
  avatar?: string | null;
  follower_num?: number;
  file_num?: number;
  is_pending?: boolean;
  space_kind?: "normal" | "department";
  department_id?: number | null;
  department_name?: string | null;
  approval_enabled?: boolean | null;
  sensitive_check_enabled?: boolean | null;
  is_hidden?: boolean | null;
  auto_tag_mode?: "library" | "custom";
  auto_tag_custom_tags?: string[] | null;
}

export interface ChildrenQuery {
  parent_id?: number;
  file_ids?: number[];
  order_field?: string;
  order_sort?: "asc" | "desc";
  file_status?: number[];
  page_size?: number;
  cursor?: string | null;
  file_type?: 0 | 1;
}

export interface PageQuery {
  page?: number;
  page_size?: number;
}
export interface AdminSpacesQuery extends PageQuery { keyword?: string }
export interface ProcessingJobsQuery extends PageQuery { kind?: ProcessingKind; state?: JobState }
export interface ProcessingItemsQuery extends PageQuery { state?: ItemState }

type ApiEnvelope<T> = { status_code: number; status_message: string; data: T };

export class KnowledgeProcessingApiError extends Error {
  readonly status_code: number;
  readonly status_message: string;
  readonly data: unknown;

  constructor(envelope: ApiEnvelope<unknown>) {
    super(envelope.status_message);
    this.name = "KnowledgeProcessingApiError";
    this.status_code = envelope.status_code;
    this.status_message = envelope.status_message;
    this.data = envelope.data;
  }
}

function unwrap<T>(envelope: ApiEnvelope<T>): T {
  if (envelope.status_code !== 200) throw new KnowledgeProcessingApiError(envelope);
  return envelope.data;
}

const spacePath = (spaceId: number) => `/api/v1/knowledge/space/${spaceId}`;
const jobsPath = (spaceId: number) => `${spacePath(spaceId)}/processing-jobs`;
const jobPath = (spaceId: number, jobId: string) => `${jobsPath(spaceId)}/${encodeURIComponent(jobId)}`;

export async function getSpaceInfo(spaceId: number): Promise<KnowledgeSpaceRead> {
  return unwrap(await request.get<ApiEnvelope<KnowledgeSpaceRead>>(`${spacePath(spaceId)}/info`));
}

export async function listChildren(spaceId: number, query: ChildrenQuery = {}): Promise<CursorPage<RawSpaceChild>> {
  return unwrap(await request.get<ApiEnvelope<CursorPage<RawSpaceChild>>>(`${spacePath(spaceId)}/children`, {
    params: query, paramsSerializer: request.paramsSerializer,
  }));
}

export async function listAdminSpaces(query: AdminSpacesQuery = {}): Promise<PageData<KnowledgeSpaceRead>> {
  return unwrap(await request.get<ApiEnvelope<PageData<KnowledgeSpaceRead>>>("/api/v1/knowledge/space/admin/list", { params: query }));
}

export async function getProcessingSettings(spaceId: number): Promise<ProcessingSettingsRead> {
  return unwrap(await request.get<ApiEnvelope<ProcessingSettingsRead>>(`${spacePath(spaceId)}/processing-settings`));
}

export async function updateProcessingSettings(spaceId: number, command: ProcessingSettingsWrite): Promise<ProcessingSettingsRead> {
  return unwrap<ProcessingSettingsRead>(await request.put(`${spacePath(spaceId)}/processing-settings`, command));
}

export async function precheckProcessing(spaceId: number, command: ProcessingPrecheckRequest): Promise<OperationPrecheck> {
  return unwrap<OperationPrecheck>(await request.post(`${jobsPath(spaceId)}/precheck`, command));
}

export async function createProcessingJob(spaceId: number, command: ProcessingCreateRequest): Promise<JobAccepted> {
  return unwrap<JobAccepted>(await request.post(jobsPath(spaceId), command));
}

export async function listProcessingJobs(spaceId: number, query: ProcessingJobsQuery = {}): Promise<PageData<ProcessingJobRead>> {
  return unwrap(await request.get<ApiEnvelope<PageData<ProcessingJobRead>>>(jobsPath(spaceId), { params: query }));
}

export async function getProcessingJob(spaceId: number, jobId: string): Promise<ProcessingJobRead> {
  return unwrap(await request.get<ApiEnvelope<ProcessingJobRead>>(jobPath(spaceId, jobId)));
}

export async function listProcessingItems(spaceId: number, jobId: string, query: ProcessingItemsQuery = {}): Promise<PageData<ProcessingItemRead>> {
  return unwrap(await request.get<ApiEnvelope<PageData<ProcessingItemRead>>>(`${jobPath(spaceId, jobId)}/items`, { params: query }));
}

export async function retryProcessingJob(spaceId: number, jobId: string, command: ProcessingRetryRequest): Promise<JobAccepted> {
  return unwrap<JobAccepted>(await request.post(`${jobPath(spaceId, jobId)}/retry`, command));
}

// Scope comes from the authenticated caller; it is never sent as an authorization override.
export interface ProcessingIdentityScope {
  userId: string | number;
  tenantId: string | number;
  view: "ordinary" | "admin";
}

export function captureProcessingScope(scope: ProcessingIdentityScope): Readonly<ProcessingIdentityScope> {
  return Object.freeze({ userId: String(scope.userId), tenantId: String(scope.tenantId), view: scope.view });
}

export function isProcessingScopeCurrent(issued: Readonly<ProcessingIdentityScope>, current: ProcessingIdentityScope): boolean {
  return String(issued.userId) === String(current.userId) && String(issued.tenantId) === String(current.tenantId) && issued.view === current.view;
}

const scopeKey = (scope: ProcessingIdentityScope) => ["knowledge-processing", captureProcessingScope(scope)] as const;

export const knowledgeProcessingKeys = {
  all: scopeKey,
  info: (scope: ProcessingIdentityScope, spaceId: number) => [...scopeKey(scope), "space", spaceId, "info"] as const,
  children: (scope: ProcessingIdentityScope, spaceId: number, query: ChildrenQuery = {}) => [
    ...scopeKey(scope), "space", spaceId, "children", {
      ...query, file_ids: query.file_ids?.slice(), file_status: query.file_status?.slice(),
    },
  ] as const,
  adminSpaces: (scope: ProcessingIdentityScope, query: AdminSpacesQuery = {}) => [...scopeKey(scope), "admin-spaces", { ...query }] as const,
  settings: (scope: ProcessingIdentityScope, spaceId: number) => [...scopeKey(scope), "space", spaceId, "settings"] as const,
  jobs: (scope: ProcessingIdentityScope, spaceId: number, query: ProcessingJobsQuery = {}) => [...scopeKey(scope), "space", spaceId, "jobs", { ...query }] as const,
  job: (scope: ProcessingIdentityScope, spaceId: number, jobId: string) => [...scopeKey(scope), "space", spaceId, "job", jobId] as const,
  items: (scope: ProcessingIdentityScope, spaceId: number, jobId: string, query: ProcessingItemsQuery = {}) => [...scopeKey(scope), "space", spaceId, "job", jobId, "items", { ...query }] as const,
};
