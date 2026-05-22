import request from "./request";
import { FileStatus, FileType, type KnowledgeFile } from "./knowledge";

interface ApiResponse<T> {
  status_code: number;
  status_message: string;
  data: T;
}

export type ApprovalCenterTab = "my_tasks" | "my_requests";

export interface ApprovalTaskItem {
  task_id?: number;
  id?: number;
  instance_id?: number;
  scenario_code?: string;
  scenario_name?: string;
  business_name?: string;
  status?: string;
  instance_status?: string;
  current_node_name?: string | null;
  applicant_user_name?: string;
  applicant_department_id?: number | null;
  applicant_department_name?: string | null;
  // task-level fields (when inside ApprovalInstanceDetail.tasks)
  approver_user_id?: number;
  approver_user_name?: string | null;
  node_name?: string | null;
  node_order?: number;
  node_mode?: string;
  comment?: string | null;
  create_time?: string;
  update_time?: string;
}

export interface ApprovalInstanceItem {
  instance_id?: number;
  id?: number;
  scenario_code?: string;
  scenario_name?: string;
  business_name?: string;
  status?: string;
  applicant_user_name?: string;
  applicant_department_id?: number | null;
  applicant_department_name?: string | null;
  current_node_name?: string | null;
  current_approver_names?: string | null;
  create_time?: string;
  update_time?: string;
}

export interface ApprovalTaskDetail extends ApprovalTaskItem {
  comment?: string | null;
  reason?: string | null;
  detail_snapshot?: Record<string, any>;
  payload_snapshot?: Record<string, any>;
  detail?: Record<string, any>;
  action_logs?: Array<{
    id?: number;
    action?: string;
    operator_user_name?: string;
    create_time?: string;
    detail?: Record<string, any>;
  }>;
}

export interface ApprovalFlowNode {
  node_code?: string;
  node_name?: string;
  node_order?: number;
  node_mode?: string;
}

export interface ApprovalInstanceDetail extends ApprovalInstanceItem {
  reason?: string | null;
  granted_keys?: string[];
  revoked_keys?: string[];
  payload_snapshot?: Record<string, any>;
  detail_snapshot?: Record<string, any>;
  tasks?: ApprovalTaskItem[];
  flow_nodes?: ApprovalFlowNode[];
  action_logs?: Array<{
    id?: number;
    action?: string;
    operator_user_name?: string;
    create_time?: string;
    detail?: Record<string, any>;
  }>;
}

export interface ApprovalSettings {
  approval_enabled: boolean;
  sensitive_check_enabled: boolean;
}

export interface ApprovalRequestItem {
  id: number;
  request_type: string;
  status: string;
  review_mode: string;
  space_id: number;
  department_id: number;
  parent_folder_id?: number | null;
  applicant_user_id: number;
  applicant_user_name: string;
  reviewer_user_ids: number[];
  file_count: number;
  payload_json: Record<string, any>;
  safety_status: string;
  safety_reason?: string | null;
  decision_reason?: string | null;
  decided_by?: number | null;
  message_id?: number | null;
  create_time?: string;
  update_time?: string;
}

export class ApprovalApiError extends Error {
  statusCode: number;
  statusMessage: string;
  constructor(statusCode: number, statusMessage: string) {
    super(statusMessage);
    this.statusCode = statusCode;
    this.statusMessage = statusMessage;
  }
}

function unwrapPayload<T>(response: ApiResponse<T> | T): T {
  const apiResp = response as ApiResponse<T>;
  if (apiResp?.status_code != null && apiResp.status_code !== 200) {
    throw new ApprovalApiError(apiResp.status_code, apiResp.status_message || String(apiResp.status_code));
  }
  return (apiResp?.data ?? response) as T;
}

function unwrapPaged<T>(response: any): { data: T[]; total: number } {
  if (response?.status_code != null && response.status_code !== 200) {
    throw new ApprovalApiError(response.status_code, response.status_message || String(response.status_code));
  }
  const payload = response?.data ?? response ?? {};
  return {
    data: Array.isArray(payload?.data) ? payload.data : [],
    total: Number(payload?.total ?? 0),
  };
}

export async function listMyApprovalTasksApi(): Promise<{ data: ApprovalTaskItem[]; total: number }> {
  const response = await request.get<ApiResponse<{ data: ApprovalTaskItem[]; total: number }>>(
    "/api/v1/approval/my-tasks",
  );
  return unwrapPaged<ApprovalTaskItem>(response);
}

export async function getMyApprovalTaskDetailApi(taskId: number): Promise<ApprovalTaskDetail> {
  const response = await request.get<ApiResponse<ApprovalTaskDetail>>(`/api/v1/approval/my-tasks/${taskId}`);
  return unwrapPayload(response);
}

export async function decideApprovalTaskApi(
  taskId: number,
  data: { action: "approve" | "reject"; comment?: string },
): Promise<ApprovalTaskDetail> {
  const response = await request.post<ApiResponse<ApprovalTaskDetail>>(
    `/api/v1/approval/tasks/${taskId}/decision`,
    data,
  );
  return unwrapPayload(response);
}

export async function listMyApprovalRequestsApi(): Promise<{ data: ApprovalInstanceItem[]; total: number }> {
  const response = await request.get<ApiResponse<{ data: ApprovalInstanceItem[]; total: number }>>(
    "/api/v1/approval/my-requests",
  );
  return unwrapPaged<ApprovalInstanceItem>(response);
}

export async function getApprovalInstanceDetailApi(instanceId: number): Promise<ApprovalInstanceDetail> {
  const response = await request.get<ApiResponse<ApprovalInstanceDetail>>(`/api/v1/approval/instances/${instanceId}`);
  return unwrapPayload(response);
}

export async function withdrawApprovalInstanceApi(
  instanceId: number,
  data: { reason?: string },
): Promise<ApprovalInstanceDetail> {
  const response = await request.post<ApiResponse<ApprovalInstanceDetail>>(
    `/api/v1/approval/instances/${instanceId}/withdraw`,
    data,
  );
  return unwrapPayload(response);
}

export async function resubmitApprovalInstanceApi(
  instanceId: number,
  data: { reason?: string },
): Promise<ApprovalInstanceDetail> {
  const response = await request.post<ApiResponse<ApprovalInstanceDetail>>(
    `/api/v1/approval/instances/${instanceId}/resubmit`,
    data,
  );
  return unwrapPayload(response);
}

export async function applyMenuAccessApi(data: {
  menu_key: string;
  menu_name: string;
  reason?: string;
}): Promise<Record<string, any>> {
  const response = await request.post<ApiResponse<Record<string, any>>>(
    "/api/v1/approval/menu-access/apply",
    data,
  );
  return unwrapPayload(response);
}

export async function revokeMenuAccessGrantApi(
  instanceId: number,
  data: { reason?: string },
): Promise<Record<string, any>> {
  const response = await request.post<ApiResponse<Record<string, any>>>(
    `/api/v1/approval/menu-access/${instanceId}/revoke-grant`,
    data,
  );
  return unwrapPayload(response);
}

export async function getDepartmentKnowledgeSpaceApprovalSettingsApi(): Promise<ApprovalSettings> {
  const res = await request.get<ApiResponse<ApprovalSettings>>(`/api/v1/approval/department-knowledge-space/settings`);
  return unwrapPayload(res);
}

export async function updateDepartmentKnowledgeSpaceApprovalSettingsApi(
  data: ApprovalSettings
): Promise<ApprovalSettings> {
  const res = await request.put<ApiResponse<ApprovalSettings>>(
    `/api/v1/approval/department-knowledge-space/settings`,
    data,
  );
  return unwrapPayload(res);
}

export async function listApprovalRequestsApi(params?: {
  space_id?: number;
  statuses?: string[];
  page?: number;
  page_size?: number;
}): Promise<{ data: ApprovalRequestItem[]; total: number }> {
  const res: any = await request.get(`/api/v1/approval/requests`, {
    params,
    paramsSerializer: request.paramsSerializer,
  });
  return unwrapPaged<ApprovalRequestItem>(res);
}

export async function getApprovalRequestApi(requestId: number): Promise<ApprovalRequestItem> {
  const res: any = await request.get(`/api/v1/approval/requests/${requestId}`);
  return unwrapPayload(res) as ApprovalRequestItem;
}

export async function decideApprovalRequestApi(
  requestId: number,
  data: { action: "approve" | "reject"; reason?: string }
): Promise<ApprovalRequestItem> {
  const res: any = await request.post(
    `/api/v1/approval/requests/${requestId}/decision`,
    data,
  );
  return unwrapPayload(res) as ApprovalRequestItem;
}

function fileTypeFromName(fileName: string): FileType {
  const ext = fileName.split(".").pop()?.toLowerCase();
  switch (ext) {
    case "pdf":
      return FileType.PDF;
    case "doc":
      return FileType.DOC;
    case "docx":
      return FileType.DOCX;
    case "xls":
      return FileType.XLS;
    case "xlsx":
      return FileType.XLSX;
    case "ppt":
      return FileType.PPT;
    case "pptx":
      return FileType.PPTX;
    case "jpg":
      return FileType.JPG;
    case "jpeg":
      return FileType.JPEG;
    case "png":
      return FileType.PNG;
    case "html":
    case "htm":
      return FileType.HTML;
    case "txt":
      return FileType.TXT;
    case "md":
      return FileType.MD;
    case "wps":
      return FileType.WPS;
    case "dps":
      return FileType.DPS;
    case "et":
      return FileType.ET;
    default:
      return FileType.OTHER;
  }
}

function numberOrUndefined(value: unknown): number | undefined {
  if (value === undefined || value === null || value === "") return undefined;
  const num = Number(value);
  return Number.isFinite(num) ? num : undefined;
}

export function approvalRequestToKnowledgeFiles(
  requestItem: ApprovalRequestItem,
  spaceId: string,
): KnowledgeFile[] {
  const files = Array.isArray(requestItem.payload_json?.files)
    ? requestItem.payload_json.files
    : [];
  return files.map((item: any, index: number) => {
    const name = String(item?.file_name || item?.name || `pending-${index + 1}`);
    const parentId = item?.parent_id ?? requestItem.parent_folder_id;
    return {
      id: String(-(requestItem.id * 1000 + index + 1)),
      name,
      type: fileTypeFromName(name),
      size: numberOrUndefined(item?.file_size ?? item?.size),
      status:
        requestItem.status === "pending_review"
          ? FileStatus.WAITING
          : FileStatus.FAILED,
      tags: [],
      path: String(item?.file_path || item?.file_name || ""),
      parentId:
        parentId !== undefined && parentId !== null
          ? String(parentId)
          : undefined,
      spaceId,
      createdAt: requestItem.create_time || "",
      updatedAt: requestItem.update_time || requestItem.create_time || "",
      approvalRequestId: requestItem.id,
      approvalStatus: requestItem.status,
      approvalReason: requestItem.decision_reason || requestItem.safety_reason || undefined,
      isPendingApproval: requestItem.status === "pending_review",
    };
  });
}
