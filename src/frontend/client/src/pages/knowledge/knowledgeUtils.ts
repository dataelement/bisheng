import { FileStatus, FileType, type KnowledgeFile } from "~/api/knowledge";
import i18next from "i18next";

/** 列表/卡片：可点击「查看详情」——文件夹，或解析成功（SUCCESS）的文件 */
export function isKnowledgeItemPreviewable(file: KnowledgeFile): boolean {
    if (file.type === FileType.FOLDER) return true;
    return file.status === FileStatus.SUCCESS;
}

export function getKnowledgeApprovalStatusLabel(file: KnowledgeFile): string | null {
    if (!file.approvalStatus) return null;
    switch (file.approvalStatus) {
        case "pending_review":
            return i18next.t("com_knowledge.approval_pending_status");
        case "sensitive_rejected":
            return i18next.t("com_knowledge.sensitive_rejected_status");
        case "rejected":
            return i18next.t("com_knowledge.approval_rejected_status");
        case "finalize_failed":
            return i18next.t("com_knowledge.approval_finalize_failed_status");
        default:
            return null;
    }
}

export function isKnowledgeApprovalRejected(file: KnowledgeFile): boolean {
    return file.approvalStatus === "rejected" || file.approvalStatus === "sensitive_rejected";
}

export function isKnowledgeItemPending(file: KnowledgeFile): boolean {
    if (file.approvalStatus) {
        return file.approvalStatus === "pending_review";
    }
    return Boolean(
        file.status && [
            FileStatus.PROCESSING,
            FileStatus.WAITING,
            FileStatus.REBUILDING,
            FileStatus.UPLOADING,
        ].includes(file.status)
    );
}

// ─── File upload constants ──────────────────────────────────────────
/**
 * Allowed file extensions for upload — fully populated set (assumes ETL4LM is enabled).
 * Prefer `getAllowedExtensions(enableEtl4lm)` for runtime-correct lists.
 */
export const ALLOWED_EXTENSIONS = [
    "pdf", "txt", "docx", "ppt", "pptx", "md", "html",
    "xls", "xlsx", "csv", "doc", "png", "jpg", "jpeg", "bmp",
    "wps", "dps", "et",
] as const;

/** Subset used when ETL4LM is NOT deployed — drops images. */
const ALLOWED_EXTENSIONS_NO_ETL4LM: readonly string[] = [
    "pdf", "txt", "docx", "doc", "ppt", "pptx", "md", "html", "xls", "xlsx", "csv",
];

/**
 * MIME types accepted during drag validation — fully populated set.
 * Prefer `getAllowedMimeTypes(enableEtl4lm)` for runtime-correct lists.
 */
export const ALLOWED_MIME_TYPES = [
    "application/pdf",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document", // docx
    "application/msword", // doc
    "application/vnd.ms-excel", // xls
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", // xlsx
    "application/vnd.ms-powerpoint", // ppt
    "application/vnd.openxmlformats-officedocument.presentationml.presentation", // pptx
    "text/markdown", "text/html", "text/csv",
    "image/png", "image/jpeg", "image/bmp",
    "application/vnd.ms-works", "application/kswps", "application/wps-office.wps", // wps
    "application/vnd.wps-presentation", "application/kswps", // dps
    "application/vnd.ms-excel", "application/kset", // et
] as const;

/** MIME types when ETL4LM is NOT deployed (no images). */
const ALLOWED_MIME_TYPES_NO_ETL4LM: readonly string[] = ALLOWED_MIME_TYPES.filter(
    (m) => !m.startsWith("image/")
);

/** Accept attribute value for <input type="file"> — full set, prefer `getFileInputAccept()`. */
export const FILE_INPUT_ACCEPT = ALLOWED_EXTENSIONS.map(e => `.${e}`).join(",");

/** Returns extension list based on whether ETL4LM is deployed. */
export function getAllowedExtensions(enableEtl4lm: boolean): readonly string[] {
    return enableEtl4lm ? ALLOWED_EXTENSIONS : ALLOWED_EXTENSIONS_NO_ETL4LM;
}

/** Returns MIME-type list based on whether ETL4LM is deployed. */
export function getAllowedMimeTypes(enableEtl4lm: boolean): readonly string[] {
    return enableEtl4lm ? ALLOWED_MIME_TYPES : ALLOWED_MIME_TYPES_NO_ETL4LM;
}

/** Returns the `<input accept="">` value for the current ETL4LM mode. */
export function getFileInputAccept(enableEtl4lm: boolean): string {
    return getAllowedExtensions(enableEtl4lm).map((e) => `.${e}`).join(",");
}

/** Default maximum single file size in MB (used when env config is not available) */
export const DEFAULT_MAX_FILE_SIZE_MB = 200;

/** Maximum number of files per upload batch */
export const MAX_UPLOAD_COUNT = 50;

/** Maximum folder nesting depth */
export const MAX_FOLDER_DEPTH = 10;

// ─── Pure utility functions ─────────────────────────────────────────

/** Derive FileType enum from a file extension */
export function getFileTypeFromName(name: string): FileType {
    const ext = name.split(".").pop()?.toLowerCase();
    switch (ext) {
        case "pdf": return FileType.PDF;
        case "doc": return FileType.DOC;
        case "docx": return FileType.DOCX;
        case "xls": return FileType.XLS;
        case "xlsx": return FileType.XLSX;
        case "ppt": return FileType.PPT;
        case "pptx": return FileType.PPTX;
        case "jpg": return FileType.JPG;
        case "jpeg": return FileType.JPEG;
        case "png": return FileType.PNG;
        case "wps": return FileType.WPS;
        case "dps": return FileType.DPS;
        case "et": return FileType.ET;
        default: return FileType.OTHER;
    }
}

/**
 * Trigger browser download from a URL.
 * Supports both absolute URLs (http/https) and relative paths from the backend.
 * For relative paths: Full URL = window.location.origin + BASE_URL + relativeUrl
 */
export function triggerUrlDownload(url: string, filename?: string) {
    const fullUrl = /^https?:\/\//.test(url)
        ? url
        : `${window.location.origin}${__APP_ENV__.BASE_URL}${url}`;
    const a = document.createElement("a");
    a.href = fullUrl;
    if (filename) a.download = filename;
    a.target = "_blank";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

/** Format ISO date string for display — shows time if today, otherwise date */
export function formatTime(dateString: string): string {
    const date = new Date(dateString);
    const yyyy = date.getFullYear();
    const mm = String(date.getMonth() + 1).padStart(2, "0");
    const dd = String(date.getDate()).padStart(2, "0");
    const HH = String(date.getHours()).padStart(2, "0");
    const min = String(date.getMinutes()).padStart(2, "0");

    const now = new Date();
    const isToday = date.toDateString() === now.toDateString();

    const todayStr = i18next.t("com_ui_date_today");
    return isToday ? `${todayStr} ${HH}:${min}` : `${yyyy}-${mm}-${dd} ${HH}:${min}`;
}

/**
 * Card-mode compact date display.
 * Today  → "HH:mm"
 * Others → "YYYY-MM-DD"
 */
export function formatTimeCard(dateString: string): string {
    const date = new Date(dateString);
    const yyyy = date.getFullYear();
    const mm = String(date.getMonth() + 1).padStart(2, "0");
    const dd = String(date.getDate()).padStart(2, "0");
    const HH = String(date.getHours()).padStart(2, "0");
    const min = String(date.getMinutes()).padStart(2, "0");

    const isToday = date.toDateString() === new Date().toDateString();
    return isToday ? `${HH}:${min}` : `${yyyy}-${mm}-${dd}`;
}

/**
 * Validate a single file for upload eligibility (size + extension).
 * @param file - File to validate
 * @param maxSizeMB - Maximum file size in MB (from env config or default 200)
 * Returns an error message string, or null if valid.
 */
export function validateFileForUpload(file: File, maxSizeMB: number = DEFAULT_MAX_FILE_SIZE_MB): string | null {
    const maxSizeBytes = maxSizeMB * 1024 * 1024;
    if (file.size > maxSizeBytes) {
        return i18next.t("com_knowledge.file_exceeds_limit", { name: file.name, size: maxSizeMB });
    }
    const ext = file.name.split(".").pop()?.toLowerCase();
    if (!ext || !(ALLOWED_EXTENSIONS as readonly string[]).includes(ext)) {
        return i18next.t("com_knowledge.unsupported_file_format", { 0: file.name });
    }
    return null;
}
