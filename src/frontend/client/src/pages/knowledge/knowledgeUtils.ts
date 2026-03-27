import { FileType } from "~/api/knowledge";
import i18next from "i18next";

// ─── File upload constants ──────────────────────────────────────────
/** Allowed file extensions for upload (shared across drag-drop, file input, and validation) */
export const ALLOWED_EXTENSIONS = [
    "pdf", "txt", "docx", "ppt", "pptx", "md", "html",
    "xls", "xlsx", "csv", "doc", "png", "jpg", "jpeg", "bmp",
] as const;

/** MIME types accepted during drag validation */
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
] as const;

/** Accept attribute value for <input type="file"> */
export const FILE_INPUT_ACCEPT = ALLOWED_EXTENSIONS.map(e => `.${e}`).join(",");

/** Maximum single file size in bytes (200 MB) */
export const MAX_FILE_SIZE = 200 * 1024 * 1024;

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
        default: return FileType.OTHER;
    }
}

/**
 * Trigger browser download from a relative URL returned by the backend.
 * Full URL = window.location.origin + BASE_URL + relativeUrl
 */
export function triggerUrlDownload(relativeUrl: string, filename?: string) {
    const fullUrl = `${window.location.origin}${__APP_ENV__.BASE_URL}${relativeUrl}`;
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
 * Validate a single file for upload eligibility (size + extension).
 * Returns an error message string, or null if valid.
 */
export function validateFileForUpload(file: File): string | null {
    if (file.size > MAX_FILE_SIZE) {
        return i18next.t("com_knowledge.file_exceeds_200m", { 0: file.name });
    }
    const ext = file.name.split(".").pop()?.toLowerCase();
    if (!ext || !(ALLOWED_EXTENSIONS as readonly string[]).includes(ext)) {
        return i18next.t("com_knowledge.unsupported_file_format", { 0: file.name });
    }
    return null;
}
