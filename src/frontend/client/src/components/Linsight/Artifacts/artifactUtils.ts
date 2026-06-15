/**
 * F035 Track H (P4): shared helpers for the artifact delivery UI (spec §5) —
 * file typing for the preview panel and the single-file download flow
 * (MinIO share url → backend resolve → blob save), same behaviour as the
 * legacy task flow but kept here so P5 can delete the Sop components.
 */
import { getLinsightFileDownloadApi } from '~/api/chat/data-service';

/** Output file shape of `output_result.final_files` (= store `file_list`). */
export interface ArtifactFile {
    file_id: string;
    file_name: string;
    file_url: string;
    file_md5?: string;
    file_path?: string;
}

export type PreviewKind = 'markdown' | 'text' | 'image' | 'unsupported';

const IMAGE_EXTS = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'];

export function getFileExtension(fileName: string): string {
    const lastDot = fileName?.lastIndexOf('.') ?? -1;
    return lastDot !== -1 ? fileName.substring(lastDot + 1).toLowerCase() : '';
}

/** What the preview panel can render inline; everything else falls back to download. */
export function getPreviewKind(fileName: string): PreviewKind {
    const ext = getFileExtension(fileName);
    if (ext === 'md') return 'markdown';
    if (ext === 'txt') return 'text';
    if (IMAGE_EXTS.includes(ext)) return 'image';
    return 'unsupported';
}

/** Resolve a MinIO share url into a same-origin fetchable path. */
export async function resolveArtifactUrl(fileUrl: string, versionId: string): Promise<string> {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- backend returns {data:{file_path}}, not typed
    const res: any = await getLinsightFileDownloadApi(fileUrl, versionId);
    return `${__APP_ENV__.BASE_URL}${res.data.file_path}`;
}

/** Download the original artifact file ("save as" action). */
export async function downloadArtifactFile(file: ArtifactFile, versionId: string): Promise<void> {
    const url = await resolveArtifactUrl(file.file_url, versionId);
    const response = await fetch(url);
    if (!response.ok) {
        throw new Error(`Failed to download file: ${response.status}`);
    }
    const data = await response.blob();
    // CSV needs a UTF-8 BOM so Excel opens it with the right encoding
    const blob =
        getFileExtension(file.file_name) === 'csv'
            ? new Blob([new Uint8Array([0xef, 0xbb, 0xbf]), data], { type: 'text/csv;charset=utf-8;' })
            : data;
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = file.file_name;
    link.click();
    URL.revokeObjectURL(link.href);
}

/** Save an exported blob (md → pdf/docx) with the converted extension. */
export function saveConvertedBlob(blob: Blob, mdFileName: string, toType: 'pdf' | 'docx'): void {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${mdFileName.replace(/\.md$/i, '')}.${toType}`;
    link.click();
    URL.revokeObjectURL(url);
}
