/** Maps file extension → viewer type for the FilePreview dispatcher. */

export type ViewerType = "pdf" | "docx" | "xlsx" | "markdown" | "html" | "image" | "text" | "audio" | "video" | "unsupported";

const EXT_MAP: Record<string, ViewerType> = {
    // PDF
    pdf: "pdf",
    // Word
    docx: "docx",
    doc: "docx",
    // Excel
    xls: "xlsx",
    xlsx: "xlsx",
    csv: "xlsx",
    // ppt
    ppt: "pdf",
    pptx: "pdf",
    // Markdown
    md: "markdown",
    // HTML
    html: "html",
    htm: "html",
    // Images
    png: "image",
    jpg: "image",
    jpeg: "image",
    bmp: "image",
    gif: "image",
    svg: "image",
    webp: "image",
    // Text
    txt: "text",
    // Audio
    mp3: "audio",
    wav: "audio",
    m4a: "audio",
    aac: "audio",
    flac: "audio",
    ogg: "audio",
    // Video
    mp4: "video",
    mov: "video",
    avi: "video",
    mkv: "video",
    webm: "video",
};

export function getViewerType(fileType: string): ViewerType {
    return EXT_MAP[fileType.toLowerCase()] ?? "unsupported";
}

/** Formats that support thumbnail sidebar */
export function supportsSidebar(type: ViewerType): boolean {
    return type === "pdf";
}

/** Formats that support page-based navigation */
export function supportsPagination(type: ViewerType): boolean {
    return type === "pdf";
}

/** Formats that support zoom */
export function supportsZoom(type: ViewerType): boolean {
    // A player sizes itself to its own control bar — zooming it means nothing.
    return type !== "unsupported" && type !== "audio" && type !== "video";
}

/** Audio/video, rendered by the media player rather than a document viewer. */
export function isMediaViewer(type: ViewerType): boolean {
    return type === "audio" || type === "video";
}
