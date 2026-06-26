import { FileType } from "~/api/knowledge";

// Format a byte count into a human-readable size string.
export function formatFileSize(bytes: number): string {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + sizes[i];
}

// File-type icon color. Folder/doc are brand blue; the rest are fixed
// semantic colors (red/green/orange/purple) that do not follow the theme.
export function getFileTypeColor(type: FileType): string {
    switch (type) {
        case FileType.FOLDER:
            return "#165dff";
        case FileType.PDF:
            return "#f53f3f";
        case FileType.DOC:
        case FileType.DOCX:
            return "#165dff";
        case FileType.XLS:
        case FileType.XLSX:
            return "#00b42a";
        case FileType.PPT:
        case FileType.PPTX:
            return "#ff7d00";
        case FileType.JPG:
        case FileType.JPEG:
        case FileType.PNG:
            return "#722ed1";
        default:
            return "#86909c";
    }
}
