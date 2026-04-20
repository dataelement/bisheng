/** Maps file extension → viewer type for the FilePreview dispatcher. */

export type ViewerType = "pdf" | "docx" | "xlsx" | "markdown" | "html" | "image" | "text" | "unsupported";

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
    return type !== "unsupported";
}
