import request from "~/api/request";

export const FILE_CORRECTION_SCENARIO = "knowledge_file_correction";

const CONTENT_LIMIT = 500;

export interface FileCorrectionRecord {
    correction_id: number;
    file_id: number;
    file_name: string;
    space_id: number;
    content: string;
    original_error?: string | null;
    corrected_content?: string | null;
    status: string;
}

export interface SubmitFileCorrectionInput {
    originalError: string;
    correctedContent: string;
}

interface ApiEnvelope<T> {
    status_code?: number;
    status_message?: string;
    data?: T;
}

function raiseBusinessError(payload: ApiEnvelope<unknown>): never {
    const error = new Error(payload.status_message || "请求失败") as Error & { status_code?: number };
    error.status_code = payload.status_code;
    throw error;
}

export interface FileCorrectionListItem {
    correction_id: number;
    status: string;
    award_kind?: string | null;
    applicant_user_name?: string;
    file_name?: string;
    create_time?: string | null;
    content?: string | null;
}

/** 这篇文档的纠错列表. 含反馈人, 说明和状态. */
export async function listFileCorrections(fileId: string | number): Promise<FileCorrectionListItem[]> {
    const payload = await request.get(`/api/v1/knowledge/files/${fileId}/corrections`) as ApiEnvelope<FileCorrectionListItem[]>;
    if (payload?.status_code && payload.status_code !== 200) raiseBusinessError(payload);
    return payload?.data ?? [];
}

export function correctionStatusLabel(status: string, awardKind?: string | null): string {
    if (status === "pending") return "待处理";
    if (status === "rejected") return "已拒绝";
    if (status === "withdrawn") return "已撤回";
    if (status === "cancelled") return "已取消";
    if (status === "approved" && awardKind === "update") return "已采纳并更新";
    if (status === "approved") return "已采纳";
    return status;
}

/** 提交文档纠错. 失败时抛出带 status_code 的错误. */
export async function submitFileCorrection(
    fileId: string | number,
    input: SubmitFileCorrectionInput,
): Promise<FileCorrectionRecord> {
    const payload = await request.post(`/api/v1/knowledge/files/${fileId}/corrections`, {
        original_error: input.originalError,
        corrected_content: input.correctedContent,
    }) as ApiEnvelope<FileCorrectionRecord>;
    if (payload?.status_code && payload.status_code !== 200) raiseBusinessError(payload);
    if (!payload?.data) throw new Error("提交失败");
    return payload.data;
}

/** 采纳并更新登记新文件. 不走普通上传, 因此不记入库分. */
export async function registerCorrectionUpdateFile(
    correctionId: number,
    filePath: string,
): Promise<{ id: number; status: number; file_name?: string }> {
    const payload = await request.post(`/api/v1/knowledge/file-corrections/${correctionId}/update-file`, {
        file_path: filePath,
    }) as ApiEnvelope<{ id: number; status: number; file_name?: string }>;
    if (payload?.status_code && payload.status_code !== 200) raiseBusinessError(payload);
    if (!payload?.data?.id) throw new Error("新文件没有写入知识库");
    return payload.data;
}

/** 读取纠错说明. 非当事人返回 18407. */
export async function getFileCorrection(correctionId: number): Promise<FileCorrectionRecord> {
    const payload = await request.get(`/api/v1/knowledge/file-corrections/${correctionId}`) as ApiEnvelope<FileCorrectionRecord>;
    if (payload?.status_code && payload.status_code !== 200) raiseBusinessError(payload);
    if (!payload?.data) throw new Error("读取失败");
    return payload.data;
}

export function correctionListTitle(fileName: string | null | undefined): string {
    const name = String(fileName || "").trim();
    return name ? `纠错：${name}` : "纠错";
}

export { CONTENT_LIMIT as FILE_CORRECTION_CONTENT_LIMIT };
