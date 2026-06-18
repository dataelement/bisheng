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
    /**
     * F035: 'upload' = a user-uploaded source file, 'output' (default) = an agent
     * deliverable. Uploaded sources are persisted as their parsed-markdown
     * workspace copy, so the preview renders markdown regardless of the original
     * extension (see getArtifactPreviewKind).
     */
    source?: 'upload' | 'output';
    /**
     * F035: an uploaded IMAGE whose original picture is persisted in the workspace
     * (`original_file_path`). Preview it as the image itself, not its OCR/caption
     * markdown. Absent on legacy entries → falls back to markdown.
     */
    previewAsImage?: boolean;
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

/**
 * Preview kind for a workspace artifact. Uploaded sources are stored as parsed
 * markdown (their `uploads/<name>/index.md`), so they always preview as markdown
 * even though the display name keeps the original extension (e.g. `report.pdf`).
 */
export function getArtifactPreviewKind(file: ArtifactFile): PreviewKind {
    // Image uploads with a persisted original preview as the picture itself.
    if (file.previewAsImage) return 'image';
    if (file.source === 'upload') return 'markdown';
    return getPreviewKind(file.file_name);
}

/**
 * Map a session's uploaded-file entries (store `LinsightInfo.files`, enriched by
 * useLinsightManager with `file_name` + the backend entry fields) into drawer
 * artifacts. The previewable url is the parsed-markdown object (`markdown_file_path`);
 * invalid/expired entries (failed parse, no formal product) are dropped.
 */
export function toUploadedArtifacts(files: any[] | undefined): ArtifactFile[] {
    return (files || [])
        .filter((f) => f && f.valid !== false && f.markdown_file_path)
        .map((f) => {
            const name = f.file_name || f.original_filename || '';
            // Image uploads preview as the original picture when the backend
            // persisted it (`original_file_path`); otherwise fall back to the
            // parsed-markdown wrapper (legacy entries / non-image files).
            const previewAsImage = IMAGE_EXTS.includes(getFileExtension(name)) && !!f.original_file_path;
            return {
                file_id: f.file_id,
                file_name: name,
                file_url: previewAsImage ? f.original_file_path : f.markdown_file_path,
                file_md5: f.file_md5,
                source: 'upload' as const,
                previewAsImage,
            };
        });
}

/** Resolve a MinIO share url into a same-origin fetchable path. */
export async function resolveArtifactUrl(fileUrl: string, versionId: string): Promise<string> {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- backend returns {data:{file_path}}, not typed
    const res: any = await getLinsightFileDownloadApi(fileUrl, versionId);
    return `${__APP_ENV__.BASE_URL}${res.data.file_path}`;
}

/**
 * Open an HTML artifact in the standalone sandboxed viewer tab (`/html`).
 *
 * `file.file_url` is a MinIO OBJECT KEY (e.g. `linsight/final_result/<svid>/x.html`),
 * not a directly servable URL — it must be resolved into a presigned share link
 * via the file_download API (see resolveArtifactUrl). The viewer therefore needs
 * the session_version_id to resolve it, so we pass it as `vid`. Building the query
 * with URLSearchParams also fixes the old bug where the raw key was concatenated
 * straight onto BASE_URL (`/workspace` + `linsight/...` → `/workspacelinsight/...`,
 * a missing-slash 404).
 */
export function openHtmlArtifactViewer(file: ArtifactFile, versionId: string): void {
    const params = new URLSearchParams({ url: file.file_url, vid: versionId || '' });
    window.open(`${__APP_ENV__.BASE_URL}/html?${params.toString()}`, '_blank');
}

/** Download the original artifact file ("save as" action). */
export async function downloadArtifactFile(file: ArtifactFile, versionId: string): Promise<void> {
    const url = await resolveArtifactUrl(file.file_url, versionId);
    const response = await fetch(url);
    if (!response.ok) {
        throw new Error(`Failed to download file: ${response.status}`);
    }
    const data = await response.blob();
    // A user-uploaded non-image source is stored as its PARSED MARKDOWN, so the
    // bytes fetched here are markdown regardless of the original extension —
    // download it as `<name>.md`. Image uploads and model-generated outputs keep
    // their real name/content.
    const isUploadMarkdown = file.source === 'upload' && !file.previewAsImage;
    const downloadName = isUploadMarkdown
        ? `${file.file_name.replace(/\.[^./\\]+$/, '')}.md`
        : file.file_name;
    // CSV needs a UTF-8 BOM so Excel opens it with the right encoding
    const blob =
        !isUploadMarkdown && getFileExtension(file.file_name) === 'csv'
            ? new Blob([new Uint8Array([0xef, 0xbb, 0xbf]), data], { type: 'text/csv;charset=utf-8;' })
            : data;
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = downloadName;
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
