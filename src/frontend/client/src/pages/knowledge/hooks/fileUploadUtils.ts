import i18next from "i18next";
import {
    FileStatus,
    addFilesApi,
    retryFileChangeIngestApi,
    uploadFileToServerApi,
    uploadFolderApi,
    type FileMutationItemResult,
    type FolderUploadItemPayload,
    type KnowledgeFile,
    type UploadFileResponse,
} from "~/api/knowledge";

interface UploadErrorShape {
    statusCode?: number;
    errorData?: Record<string, unknown>;
    message?: string;
    response?: { data?: { status_code?: number } };
}

interface UploadFailure {
    name: string;
    reason: string;
    statusCode?: number;
}

interface EarlyStop {
    reason: string;
    statusCode: number;
    skippedCount: number;
}

type Localize = (key: string, options?: Record<string, unknown>) => string;
type UploadStageRegister = (
    spaceId: string,
    data: { upload_ids: string[]; parent_id?: number | null },
) => Promise<FileMutationItemResult[]>;
type FolderStageRegister = (
    spaceId: string,
    data: { parent_id?: number | null; items: FolderUploadItemPayload[] },
) => Promise<FileMutationItemResult[]>;

const COLLAPSIBLE_CODES = new Set([18024, 19402, 19403]);

/**
 * Returns true when the action must not proceed, having already told the user
 * why. The byte total is optional: without it only the exhausted state is
 * checked. Server-side quota enforcement stays authoritative.
 */
export type StorageQuotaGuard = (uploadBytes?: number) => boolean;
/** Invalidates the shared effective-quota cache after usage may have moved. */
export type RefreshQuota = () => void;

/** Total byte size of an upload batch, for the personal-storage pre-check. */
export const sumFileSizes = (files: File[]): number =>
    files.reduce((total, file) => total + file.size, 0);

function resolveUploadErrorReason(error: unknown): string {
    const err = error as UploadErrorShape;
    const statusCode = err.statusCode ?? err.response?.data?.status_code;
    if (statusCode != null) {
        const codeKey = `api_errors.${statusCode}`;
        if (i18next.exists(codeKey)) {
            return String(i18next.t(codeKey as never, err.errorData ?? {}));
        }
    }
    if (typeof err.message === "string" && err.message && err.message !== "upload file failed") {
        return err.message;
    }
    return "";
}

export async function uploadFilesSequential(
    spaceId: string,
    files: File[],
    onSuccess: (response: UploadFileResponse, file: File) => void,
    filenameOf?: (file: File) => string | undefined,
): Promise<{ failures: UploadFailure[]; earlyStop: EarlyStop | null }> {
    const failures: UploadFailure[] = [];
    let earlyStop: EarlyStop | null = null;
    for (let index = 0; index < files.length; index += 1) {
        const file = files[index];
        try {
            const response = await uploadFileToServerApi(spaceId, file, filenameOf?.(file));
            onSuccess(response, file);
        } catch (error) {
            const err = error as UploadErrorShape;
            const statusCode = err.statusCode ?? err.response?.data?.status_code;
            const reason = resolveUploadErrorReason(error);
            failures.push({ name: file.name, reason, statusCode });
            if (statusCode && COLLAPSIBLE_CODES.has(statusCode)) {
                earlyStop = { reason, statusCode, skippedCount: files.length - index - 1 };
                break;
            }
        }
    }
    return { failures, earlyStop };
}

export function buildUploadFailureMessage(
    failures: UploadFailure[],
    earlyStop: EarlyStop | null,
    localize: Localize,
): string {
    if (failures.length === 0 && !earlyStop) return "";
    const collapsed: Array<{ reason: string; count: number }> = [];
    const individual: Array<{ name: string; reason: string }> = [];
    const seenCode = new Map<number, { reason: string; count: number }>();
    failures.forEach((failure) => {
        if (failure.statusCode && COLLAPSIBLE_CODES.has(failure.statusCode)) {
            const existing = seenCode.get(failure.statusCode);
            if (existing) existing.count += 1;
            else {
                const entry = { reason: failure.reason, count: 1 };
                seenCode.set(failure.statusCode, entry);
                collapsed.push(entry);
            }
        } else individual.push(failure);
    });
    if (earlyStop?.skippedCount) {
        const existing = seenCode.get(earlyStop.statusCode);
        if (existing) existing.count += earlyStop.skippedCount;
    }
    const lines = [
        ...collapsed.map(({ reason, count }) => count > 1
            ? localize("com_knowledge.file_upload_quota_batch", { 0: count, 1: reason })
            : reason),
        ...individual.map(({ name, reason }) => reason
            ? localize("com_knowledge.file_upload_failed_with_reason", { 0: name, 1: reason })
            : localize("com_knowledge.file_upload_failed", { 0: name })),
    ];
    return failures.every((failure) => !failure.reason)
        ? [...lines, localize("com_knowledge.upload_browser_hint")].join("\n")
        : lines.join("\n");
}

export interface DuplicateFileEntry {
    fileId: string;
    fileName: string;
    oldFileLevelPath: string;
    rawObj: unknown;
}

export interface PartitionedUploadMutationResults {
    directFiles: KnowledgeFile[];
    pending: FileMutationItemResult[];
    invalid: FileMutationItemResult[];
}

export function partitionUploadMutationResults(
    results: FileMutationItemResult[],
): PartitionedUploadMutationResults {
    return results.reduce<PartitionedUploadMutationResults>((partitioned, item) => {
        if (item.decision === "direct" && item.resource) partitioned.directFiles.push(item.resource);
        else if (item.decision === "pending") partitioned.pending.push(item);
        else if (item.decision === "invalid") partitioned.invalid.push(item);
        return partitioned;
    }, { directFiles: [], pending: [], invalid: [] });
}

export async function registerUploadedStagesWithRetry({
    spaceId,
    uploadIds,
    parentId,
    register = addFilesApi,
}: {
    spaceId: string;
    uploadIds: string[];
    parentId?: number | null;
    register?: UploadStageRegister;
}): Promise<FileMutationItemResult[]> {
    const payload = { upload_ids: [...uploadIds], parent_id: parentId };
    try {
        return await register(spaceId, payload);
    } catch (firstError) {
        console.warn("[useFileUpload] file registration failed, retrying once:", firstError);
        return register(spaceId, payload);
    }
}

export async function registerFolderStagesWithRetry({
    spaceId,
    items,
    parentId,
    register = uploadFolderApi,
}: {
    spaceId: string;
    items: FolderUploadItemPayload[];
    parentId?: number | null;
    register?: FolderStageRegister;
}): Promise<FileMutationItemResult[]> {
    const payload = { parent_id: parentId, items: [...items] };
    try {
        return await register(spaceId, payload);
    } catch (firstError) {
        console.warn("[useFileUpload] folder registration failed, retrying once:", firstError);
        return register(spaceId, payload);
    }
}

export async function retryApprovedUploadIngest(
    spaceId: string,
    requestId: number,
    retry: typeof retryFileChangeIngestApi = retryFileChangeIngestApi,
) {
    return retry(spaceId, requestId);
}

export function extractDuplicateFileEntries(registeredFiles: KnowledgeFile[]): DuplicateFileEntry[] {
    return registeredFiles
        .filter((file) => file.status === FileStatus.FAILED
            && typeof file.oldFileLevelPath === "string"
            && Boolean((file as KnowledgeFile & { _raw?: unknown })._raw))
        .map((file) => ({
            fileId: file.id,
            fileName: file.name,
            oldFileLevelPath: file.oldFileLevelPath || "",
            rawObj: (file as KnowledgeFile & { _raw?: unknown })._raw,
        }));
}

export function mergeVisibleRegisteredFiles(
    existingFiles: KnowledgeFile[],
    registeredFiles: KnowledgeFile[],
): { files: KnowledgeFile[]; addedCount: number } {
    if (registeredFiles.length === 0) return { files: existingFiles, addedCount: 0 };
    const existingIds = new Set(existingFiles.map((file) => file.id));
    const uniqueRegisteredFiles = registeredFiles.filter((file) => !existingIds.has(file.id));
    return { files: [...uniqueRegisteredFiles, ...existingFiles], addedCount: uniqueRegisteredFiles.length };
}
