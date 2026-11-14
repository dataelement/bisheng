import axios from "@/controllers/request";
import type {
  KnowledgeSpaceInfo,
  OperationPrecheck,
  ProcessingKind,
  JobState,
  ProcessingJobRead,
  ProcessingItemsQuery,
  ProcessingItemRead,
  PageData,
} from "./knowledgeSpace";

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

export type ProcessingCommandResult =
  | JobAccepted
  | {
      completed: true;
      operation: "embedding_rebuild";
      space_id: number;
      model_config_revision: number;
    };
export interface SpaceCopyResult {
  knowledge: KnowledgeSpaceInfo;
  processing_job: JobAccepted | null;
  completed: boolean;
}
const path = (spaceId: number) => `/api/v1/knowledge/space/${spaceId}`;
export function precheckSpaceCopy(
  spaceId: number,
  name: string,
): Promise<OperationPrecheck> {
  return axios.post(`${path(spaceId)}/copy/precheck`, { name });
}
export function confirmSpaceCopy(
  spaceId: number,
  request: ProcessingCreateRequest,
): Promise<SpaceCopyResult> {
  return axios.post(`${path(spaceId)}/copy/confirm`, request);
}
export function readProcessingJob(
  spaceId: number,
  jobId: string,
  kind?: ProcessingKind,
): Promise<ProcessingJobRead> {
  return axios.get(
    `${path(spaceId)}/processing-jobs/${encodeURIComponent(jobId)}`,
    { params: kind ? { kind } : undefined },
  );
}
export function readProcessingItems(
  spaceId: number,
  jobId: string,
  query: ProcessingItemsQuery,
  kind?: ProcessingKind,
): Promise<PageData<ProcessingItemRead>> {
  return axios.get(
    `${path(spaceId)}/processing-jobs/${encodeURIComponent(jobId)}/items`,
    { params: { ...query, ...(kind ? { kind } : {}) } },
  );
}
export function retryProcessing(
  spaceId: number,
  jobId: string,
  request: ProcessingRetryRequest,
  kind?: ProcessingKind,
): Promise<JobAccepted> {
  return axios.post(
    `${path(spaceId)}/processing-jobs/${encodeURIComponent(jobId)}/retry`,
    request,
    { params: kind ? { kind } : undefined },
  );
}

export function readProcessingTarget(
  spaceId: number,
  fileId: number,
): Promise<import("./knowledgeSpace").ProcessingTargetInput> {
  return axios.get(`${path(spaceId)}/files/${fileId}/processing-target`);
}

export function readMetadataSchema(
  spaceId: number,
): Promise<{
  revision: number;
  fields: { field_name: string; field_type: string }[];
}> {
  return axios.get(`${path(spaceId)}/metadata-schema`);
}
