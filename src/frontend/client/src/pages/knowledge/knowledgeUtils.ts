import { FileStatus, FileType, type KnowledgeFile } from "~/api/knowledge";
import i18next from "i18next";

/** List/card: only folders and successfully parsed files are clickable; violation files stay grayed out. */
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

export {
    isWebLinkKnowledgeFile,
    resolveWebLinkDisplayName,
    toWebLinkFileName,
} from "~/api/knowledge";

/**
 * True while a file body is still being uploaded (frontend placeholder row)
 * or a folder row is a not-yet-committed inline-create placeholder. These
 * rows have no stable backend identity yet, so move (drag / menu / batch)
 * must be disabled for them.
 */
export function isKnowledgeItemUploading(file: KnowledgeFile): boolean {
    return file.status === FileStatus.UPLOADING || !!file.isCreating;
}

export function isKnowledgeItemPending(file: KnowledgeFile): boolean {
    if (file.approvalStatus) {
        return file.approvalStatus === "pending_review";
    }
    // Folder rows have no `status`; treat as pending only when children are
    // still in an in-progress state (PROCESSING / WAITING / REBUILDING).
    // Terminal failures (FAILED / TIMEOUT / VIOLATION) must NOT keep the
    // auto-refresh polling alive — e.g. 8 success + 1 failed is a stable state.
    if (file.type === FileType.FOLDER) {
        return file.processingFileNum != null && file.processingFileNum > 0;
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
    "pdf", "ofd", "txt", "docx", "ppt", "pptx", "md", "html",
    "xls", "xlsx", "csv", "doc", "png", "jpg", "jpeg", "bmp",
    "wps", "dps", "et", "mp3", "wav", "m4a", "aac", "flac", "ogg",
    "mp4", "mov", "avi", "mkv", "webm",
] as const;

/** Subset used when ETL4LM is NOT deployed — drops images. */
const ALLOWED_EXTENSIONS_NO_ETL4LM: readonly string[] = [
    "pdf", "ofd", "txt", "docx", "doc", "ppt", "pptx", "md", "html", "xls", "xlsx", "csv",
    "wps", "dps", "et", "mp3", "wav", "m4a", "aac", "flac", "ogg", "mp4", "mov", "avi", "mkv", "webm",
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
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/mp4", "audio/m4a", "audio/x-m4a",
    "audio/aac", "audio/flac", "audio/ogg",
    "video/mp4", "video/quicktime", "video/x-msvideo", "video/avi", "video/x-matroska", "video/webm",
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

/** Default maximum media file size in MB when env config is not available */
export const DEFAULT_MEDIA_MAX_FILE_SIZE_MB = 1;

export const MEDIA_FILE_EXTENSIONS = [
    "mp3", "wav", "m4a", "aac", "flac", "ogg",
    "mp4", "mov", "avi", "mkv", "webm",
] as const;

export interface UploadSizeLimits {
    defaultMaxMB: number;
    mediaMaxMB: number;
}

export interface UploadSizeEnvConfig {
    uploaded_files_maximum_size?: number;
    uploaded_media_maximum_size?: number;
}

export function resolveUploadSizeLimits(config?: UploadSizeEnvConfig | null): UploadSizeLimits {
    return {
        defaultMaxMB: config?.uploaded_files_maximum_size ?? DEFAULT_MAX_FILE_SIZE_MB,
        mediaMaxMB: config?.uploaded_media_maximum_size ?? DEFAULT_MEDIA_MAX_FILE_SIZE_MB,
    };
}

export function isMediaFileName(name: string): boolean {
    const ext = name.split(".").pop()?.toLowerCase();
    return Boolean(ext && (MEDIA_FILE_EXTENSIONS as readonly string[]).includes(ext));
}

export function getMaxFileSizeMBForFile(name: string, limits: UploadSizeLimits): number {
    return isMediaFileName(name) ? limits.mediaMaxMB : limits.defaultMaxMB;
}

export function getMaxFileSizeBytesForFile(name: string, limits: UploadSizeLimits): number {
    return getMaxFileSizeMBForFile(name, limits) * 1024 * 1024;
}

/** Maximum number of files per upload batch */
export const MAX_UPLOAD_COUNT = 50;

/** Maximum number of files per folder upload batch */
export const MAX_FOLDER_UPLOAD_COUNT = 1000;

/** Maximum folder nesting depth */
export const MAX_FOLDER_DEPTH = 10;

// ─── Pure utility functions ─────────────────────────────────────────

/** Derive FileType enum from a file extension */
export function getFileTypeFromName(name: string): FileType {
    const ext = name.split(".").pop()?.toLowerCase();
    switch (ext) {
        case "pdf": return FileType.PDF;
        // OFD is converted to PDF; its preview is a PDF, so treat it as PDF for
        // icon + viewer routing.
        case "ofd": return FileType.PDF;
        case "doc": return FileType.DOC;
        case "docx": return FileType.DOCX;
        case "xls": return FileType.XLS;
        case "xlsx": return FileType.XLSX;
        case "ppt": return FileType.PPT;
        case "pptx": return FileType.PPTX;
        case "jpg": return FileType.JPG;
        case "jpeg": return FileType.JPEG;
        case "png": return FileType.PNG;
        case "mp3":
        case "wav":
        case "m4a":
        case "aac":
        case "flac":
        case "ogg":
            return FileType.AUDIO;
        case "mp4":
        case "mov":
        case "avi":
        case "mkv":
        case "webm":
            return FileType.VIDEO;
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

/** True if the leading segment of a name is hidden (dot-prefixed, e.g. `.git`). */
export function isHiddenName(name: string): boolean {
    return name.startsWith(".");
}

/**
 * Extract the top-level folder segment from a `webkitRelativePath`.
 * For `Docs/a.pdf` returns `Docs`; for `Docs/Sub/b.pdf` also returns `Docs`.
 */
export function getRootFolderName(relativePath: string): string {
    if (!relativePath) return "";
    return relativePath.split("/")[0] || "";
}

/**
 * A relative path is hidden when ANY of its segments is hidden — a visible
 * file inside a hidden directory (e.g. `.git/config`) must also be dropped.
 */
export function isHiddenPath(relativePath: string): boolean {
    return relativePath.split("/").some((segment) => isHiddenName(segment));
}

/**
 * Folder upload keeps files at *every* nesting level (F034 §5.5: the backend
 * rebuilds the directory tree from `webkitRelativePath`) and silently drops:
 *   - hidden files, and files inside hidden directories (checked per path segment)
 *   - unsupported extensions
 *   - files exceeding the size limit
 *
 * Caller is expected to have already handled the integral-batch rejections
 * (hidden root folder / duplicate folder name / > MAX_FOLDER_UPLOAD_COUNT).
 *
 * Returns the kept files plus counts of what was dropped, so the caller can
 * tell the user why some files didn't upload (oversize / unsupported). Hidden
 * files stay a silent drop (expected behaviour, not worth a toast).
 */
export interface FolderUploadFilterResult {
    valid: File[];
    oversizeCount: number;
    unsupportedCount: number;
}

export function filterFolderUploadFiles(
    files: File[],
    options: { allowedExtensions: readonly string[]; maxSizeMB: number; limits?: UploadSizeLimits },
): FolderUploadFilterResult {
    const limits = options.limits ?? { defaultMaxMB: options.maxSizeMB, mediaMaxMB: options.maxSizeMB };
    const valid: File[] = [];
    let oversizeCount = 0;
    let unsupportedCount = 0;
    for (const file of files) {
        const rel = file.webkitRelativePath || file.name;
        if (isHiddenPath(rel)) continue; // hidden: silent drop
        if (file.size > getMaxFileSizeBytesForFile(file.name, limits)) {
            oversizeCount++;
            continue;
        }
        const ext = file.name.split(".").pop()?.toLowerCase();
        if (!ext || !options.allowedExtensions.includes(ext)) {
            unsupportedCount++;
            continue;
        }
        valid.push(file);
    }
    return { valid, oversizeCount, unsupportedCount };
}

/**
 * Validate a single file for upload eligibility (size + extension).
 * @param file - File to validate
 * @param maxSizeMB - Maximum file size in MB (from env config or default 200)
 * Returns an error message string, or null if valid.
 */
export function validateFileForUpload(
    file: File,
    maxSizeMB: number = DEFAULT_MAX_FILE_SIZE_MB,
    limits?: UploadSizeLimits,
): string | null {
    const resolvedLimits = limits ?? { defaultMaxMB: maxSizeMB, mediaMaxMB: maxSizeMB };
    if (file.size > getMaxFileSizeBytesForFile(file.name, resolvedLimits)) {
        return i18next.t("com_knowledge.file_exceeds_limit", {
            name: file.name,
            size: getMaxFileSizeMBForFile(file.name, resolvedLimits),
        });
    }
    const ext = file.name.split(".").pop()?.toLowerCase();
    if (!ext || !(ALLOWED_EXTENSIONS as readonly string[]).includes(ext)) {
        return i18next.t("com_knowledge.unsupported_file_format", { 0: file.name });
    }
    return null;
}
