/**
 * Shared helpers to turn a raw `KnowledgeFilePreview` payload (from
 * `getFilePreviewApi`) into the concrete props a `FilePreview` /
 * `RichKnowledgePreview` needs: a resolved URL, a file extension, and the
 * rich-media / conversion-failed flags.
 *
 * The route page (`FilePreviewPage`) and the portal workbench each grew their
 * own copy of this logic; new consumers should reuse this module instead.
 */
import type { KnowledgeFilePreview } from "~/api/knowledge";

const AUDIO_EXTENSIONS = new Set(["mp3", "wav", "m4a", "aac", "flac", "ogg"]);
const VIDEO_EXTENSIONS = new Set(["mp4", "mov", "avi", "mkv", "webm"]);

/**
 * Extract a file extension from a URL path, ignoring query string / hash.
 * e.g. "/bisheng/preview/84296.html?X-Amz-Algorithm=..." → "html"
 */
export function extractExtFromUrl(url: string, fallback: string): string {
    try {
        const pathOnly = url.split("?")[0].split("#")[0];
        const lastSegment = pathOnly.split("/").pop() || "";
        const dotIndex = lastSegment.lastIndexOf(".");
        if (dotIndex >= 0 && dotIndex < lastSegment.length - 1) {
            return lastSegment.substring(dotIndex + 1).toLowerCase();
        }
    } catch {
        // Parsing failed — fall through to the fallback.
    }
    return fallback;
}

/** Turn a possibly-relative preview URL into an absolute one. */
export function resolvePreviewUrl(url: string): string {
    if (!url) return "";
    return /^https?:\/\//.test(url)
        ? url
        : `${window.location.origin}${__APP_ENV__.BASE_URL}${url}`;
}

/** Whether the payload should be rendered by `RichKnowledgePreview` (web link / audio / video). */
export function isRichPreviewData(data: KnowledgeFilePreview | null): boolean {
    if (!data) return false;
    const ext = extractExtFromUrl(data.original_url || data.preview_url || "", "");
    return (
        data.file_source === "web_link"
        || data.file_source === "audio_transcript"
        || data.file_source === "video_transcript"
        || data.media_kind === "audio"
        || data.media_kind === "video"
        || AUDIO_EXTENSIONS.has(ext)
        || VIDEO_EXTENSIONS.has(ext)
    );
}

export interface ResolvedPreview {
    /** True when the caller should render `RichKnowledgePreview` instead of `FilePreview`. */
    isRich: boolean;
    /** Absolute URL to feed the viewer (empty when not renderable). */
    fileUrl: string;
    /** File extension driving the viewer choice. */
    fileType: string;
    /** True when a pptx→pdf conversion was expected but the backend produced no preview. */
    conversionFailed: boolean;
    /** Payload with all URLs resolved to absolute form (for `RichKnowledgePreview`). */
    previewData: KnowledgeFilePreview;
}

/**
 * Resolve a raw preview payload into concrete viewer props. Mirrors the logic in
 * `FilePreviewPage` so both paths behave identically.
 */
export function resolveFilePreview(data: KnowledgeFilePreview): ResolvedPreview {
    const previewData: KnowledgeFilePreview = {
        ...data,
        original_url: resolvePreviewUrl(data.original_url),
        preview_url: resolvePreviewUrl(data.preview_url),
        html_preview_url: resolvePreviewUrl(data.html_preview_url),
    };

    if (isRichPreviewData(data)) {
        const richUrl = previewData.preview_url || previewData.html_preview_url || previewData.original_url;
        return {
            isRich: true,
            fileUrl: richUrl,
            fileType: data.file_source === "web_link" ? "html" : extractExtFromUrl(data.original_url, "md"),
            conversionFailed: false,
            previewData,
        };
    }

    const chosenUrl = data.preview_url || data.original_url;
    if (!chosenUrl) {
        return { isRich: false, fileUrl: "", fileType: "pdf", conversionFailed: false, previewData };
    }

    const ext = extractExtFromUrl(chosenUrl, "pdf");
    // A ppt/pptx that never got a preview_url can't be rendered raw → conversion failed.
    if (!data.preview_url && /^pptx?$/.test(ext)) {
        return { isRich: false, fileUrl: "", fileType: ext, conversionFailed: true, previewData };
    }

    return { isRich: false, fileUrl: resolvePreviewUrl(chosenUrl), fileType: ext, conversionFailed: false, previewData };
}
