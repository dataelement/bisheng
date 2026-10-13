import request from "~/api/request";

export const FILE_CORRECTION_SCENARIO = "knowledge_file_correction";

const CONTENT_LIMIT = 500;

export interface FileCorrectionRecord {
    correction_id: number;
    file_id: number;
    file_name: string;
    space_id: number;
    content: string;
    status: string;
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

/** 提交文档纠错. 失败时抛出带 status_code 的错误. */
export async function submitFileCorrection(fileId: string | number, content: string): Promise<FileCorrectionRecord> {
    const payload = await request.post(`/api/v1/knowledge/files/${fileId}/corrections`, {
        content,
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
