import request from "./request";
import { FileStatus, FileType, type KnowledgeFile } from "./knowledge";

interface ApiResponse<T> {
  status_code: number;
  status_message: string;
  data: T;
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

export async function getDepartmentKnowledgeSpaceApprovalSettingsApi(): Promise<ApprovalSettings> {
  const res = await request.get<ApiResponse<ApprovalSettings>>(`/api/v1/approval/department-knowledge-space/settings`);
  return (res as any)?.data ?? res;
}

export async function updateDepartmentKnowledgeSpaceApprovalSettingsApi(
  data: ApprovalSettings
): Promise<ApprovalSettings> {
  const res = await request.put<ApiResponse<ApprovalSettings>>(
    `/api/v1/approval/department-knowledge-space/settings`,
    data,
  );
  return (res as any)?.data ?? res;
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
  const payload = res?.data ?? res ?? {};
  return {
    data: Array.isArray(payload?.data) ? payload.data : [],
    total: Number(payload?.total ?? 0),
  };
}

export async function getApprovalRequestApi(requestId: number): Promise<ApprovalRequestItem> {
  const res: any = await request.get(`/api/v1/approval/requests/${requestId}`);
  return (res?.data ?? res) as ApprovalRequestItem;
}

export async function decideApprovalRequestApi(
  requestId: number,
  data: { action: "approve" | "reject"; reason?: string }
): Promise<ApprovalRequestItem> {
  const res: any = await request.post(
    `/api/v1/approval/requests/${requestId}/decision`,
    data,
  );
  return (res?.data ?? res) as ApprovalRequestItem;
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
  request: ApprovalRequestItem,
  spaceId: string,
): KnowledgeFile[] {
  const files = Array.isArray(request.payload_json?.files)
    ? request.payload_json.files
    : [];
  return files.map((item: any, index: number) => {
    const name = String(item?.file_name || item?.name || `pending-${index + 1}`);
    const parentId = item?.parent_id ?? request.parent_folder_id;
    return {
      id: String(-(request.id * 1000 + index + 1)),
      name,
      type: fileTypeFromName(name),
      size: numberOrUndefined(item?.file_size ?? item?.size),
      status:
        request.status === "pending_review"
          ? FileStatus.WAITING
          : FileStatus.FAILED,
      tags: [],
      path: String(item?.file_path || item?.file_name || ""),
      parentId:
        parentId !== undefined && parentId !== null
          ? String(parentId)
          : undefined,
      spaceId,
      createdAt: request.create_time || "",
      updatedAt: request.update_time || request.create_time || "",
      approvalRequestId: request.id,
      approvalStatus: request.status,
      approvalReason: request.decision_reason || request.safety_reason || undefined,
      isPendingApproval: request.status === "pending_review",
    };
  });
}
