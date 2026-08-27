/**
 * F035 Track H (P4): shared helpers for the artifact delivery UI (spec §5) —
 * file typing for the preview panel and the single-file download flow
 * (MinIO share url → backend resolve → blob save), same behaviour as the
 * legacy task flow but kept here so P5 can delete the Sop components.
 */
import { getLinsightFileDownloadApi } from '~/api/chat/data-service';
import { getShareTokenFromPath } from '~/utils/shareToken';

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

export type PreviewKind = 'markdown' | 'text' | 'image' | 'document' | 'unsupported';

const IMAGE_EXTS = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'];
// Rich file types rendered inline by the shared FilePreview viewer (pdfjs /
// mammoth / xlsx). Explicitly excludes `doc` (legacy binary mammoth can't parse)
// and `ppt`/`pptx` (need a backend pptx→pdf conversion) — those stay 'unsupported'
// so they keep the "download to view" fallback.
const DOCUMENT_EXTS = ['pdf', 'docx', 'xls', 'xlsx', 'csv'];

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
    if (DOCUMENT_EXTS.includes(ext)) return 'document';
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
 * Strip the workspace-zone folder prefix (`output/` / `scratch/`, with an optional
 * leading slash) from file references in the run summary, keeping the bare
 * filename.
 *
 * The model is told (system prompt step 4) not to echo workspace paths, but it
 * still often mirrors a tool result like `Updated file /output/report.md` into its
 * final answer. End users neither know nor care about the internal `output/` zone —
 * the deliverable is already surfaced by the report-link row and the file card — so
 * the path just reads as noise. The prompt is only a probabilistic guardrail; this
 * is the deterministic net that guarantees the path never reaches the user.
 *
 * Targeted, not blanket: only a `output/` / `scratch/` segment that (a) sits at a
 * non-alphanumeric boundary (so `myoutput/…` and mid-URL segments are left alone)
 * and (b) directly precedes a `name.ext` token is removed, so prose like
 * "输入/输出" or a bare "output 文件夹" mention is never mangled.
 */
export function stripWorkspacePaths(text: string): string {
    if (!text) return text;
    return text.replace(
        /(?<![A-Za-z0-9])\/?(?:output|scratch)\/(?=[^\s`"')）」】]*\.[A-Za-z0-9]{1,8})/gi,
        '',
    );
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

export interface WorkspaceArtifactSnapshot {
    files?: Parameters<typeof toUploadedArtifacts>[0];
    file_list?: ArtifactFile[];
    history?: Array<{ file_list?: ArtifactFile[] }>;
}

function getWorkspaceArtifactKey(file: ArtifactFile): string {
    const source = file.source || 'output';
    const normalizedPath = decodeSafe(file.file_path || '').replace(/\\/g, '/');
    const workspacePath = normalizedPath.match(/(?:^|\/)(output|uploads)\/(.+)$/i);
    const identity = workspacePath
        ? `${workspacePath[1].toLowerCase()}/${workspacePath[2]}`
        : decodeSafe(file.file_name || '').toLowerCase();
    return `${source}:${identity}`;
}

/**
 * Build the conversation-scoped workspace list from per-round result snapshots.
 *
 * `final_files` describes what one task round delivered; it is not the workspace
 * itself. A later greeting can legitimately have an empty `final_files` array
 * while still inheriting every prior deliverable. Accumulate snapshots in
 * chronological order so the drawer keeps those files, with a newer artifact
 * replacing an older entry at the same workspace path.
 */
export function collectConversationWorkspaceFiles(
    snapshots: Array<WorkspaceArtifactSnapshot | null | undefined>,
): ArtifactFile[] {
    const collected = new Map<string, ArtifactFile>();

    const addFiles = (files: ArtifactFile[] | undefined) => {
        for (const file of files || []) {
            if (!file?.file_name || !file?.file_url) continue;
            collected.set(getWorkspaceArtifactKey(file), file);
        }
    };

    for (const snapshot of snapshots) {
        if (!snapshot) continue;
        addFiles(toUploadedArtifacts(snapshot.files));
        for (const round of snapshot.history || []) {
            addFiles(round.file_list);
        }
        addFiles(snapshot.file_list);
    }

    return Array.from(collected.values());
}

/**
 * Resolve a MinIO share url into a same-origin fetchable path.
 *
 * `shareToken` defaults to the one in the current route: on a share page the
 * viewer is neither the owner nor an admin, and the backend grants them only
 * through the `share-token` header. Pass it explicitly from surfaces that run
 * outside the share route (the standalone `/html` viewer tab).
 */
export async function resolveArtifactUrl(
    fileUrl: string,
    versionId: string,
    shareToken: string = getShareTokenFromPath(),
): Promise<string> {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- backend returns {data:{file_path}}, not typed
    const res: any = await getLinsightFileDownloadApi(fileUrl, versionId, shareToken);
    return `${__APP_ENV__.BASE_URL}${res.data.file_path}`;
}

function decodeSafe(s: string): string {
    try {
        return decodeURIComponent(s);
    } catch {
        return s;
    }
}

/**
 * An image `src` that is already directly loadable and needs no workspace
 * resolution: absolute http(s), protocol-relative, data:/blob:, or root-relative.
 * Only bare relative refs (`charts/x.png`) go through matchArtifactByRelPath.
 */
export function isAbsoluteImageSrc(src: string): boolean {
    return /^(https?:)?\/\//i.test(src) || /^(data|blob):/i.test(src) || src.startsWith('/');
}

/**
 * Match a relative image reference — as authored inside a markdown deliverable,
 * e.g. `charts/ch1_brazil.png` — against the session's artifact file list.
 *
 * Deliverable images are written under `output/<...>` in the workspace and
 * surfaced in file_list with a bare `file_name` plus a `file_path` that preserves
 * the relative dir (worker-local `.../output/charts/ch1_brazil.png`). We match on
 * the path suffix first (disambiguates same-name files in different dirs) and fall
 * back to basename. Returns the matching entry (whose `file_url` resolves to a
 * presigned URL) or undefined when nothing matches.
 */
export function matchArtifactByRelPath(
    fileList: ArtifactFile[] | undefined,
    relPath: string,
): ArtifactFile | undefined {
    if (!relPath || !fileList?.length) return undefined;
    const norm = (s: string) => decodeSafe(s).replace(/\\/g, '/').replace(/^\.?\//, '');
    const target = norm(relPath);
    const targetNoOutput = target.replace(/^output\//, '');
    const base = target.split('/').pop() as string;
    // 1) path-suffix match on file_path (most precise — survives same basename).
    const bySuffix = fileList.find((f) => {
        if (!f.file_path) return false;
        const p = norm(f.file_path);
        return (
            p === target ||
            p.endsWith('/' + target) ||
            p.endsWith('/' + targetNoOutput) ||
            p.endsWith('/output/' + targetNoOutput)
        );
    });
    if (bySuffix) return bySuffix;
    // 2) basename match on file_name (bare filename, no dir).
    return fileList.find((f) => norm(f.file_name) === base);
}

const DELIVERABLE_LINK_EXT = /\.(md|markdown|html|htm|docx|pdf)$/i;

/** True when href looks like an internal workspace deliverable reference. */
export function isDeliverableLinkHref(href: string): boolean {
    if (!href || isAbsoluteImageSrc(href)) return false;
    const norm = decodeSafe(href).replace(/\\/g, '/').replace(/^\.?\//, '').replace(/^output\//, '');
    return DELIVERABLE_LINK_EXT.test(norm);
}

/**
 * Resolve a markdown link in the task result answer to a previewable artifact.
 * Returns undefined when the link names no file this run produced — the caller
 * renders that as 未生成 rather than guessing which artifact was meant.
 */
export function resolveDeliverableLink(
    fileList: ArtifactFile[] | undefined,
    href: string,
): ArtifactFile | undefined {
    const matched = matchArtifactByRelPath(fileList, href);
    if (matched) return matched;
    if (!fileList?.length || !isDeliverableLinkHref(href)) return undefined;
    const norm = decodeSafe(href).replace(/\\/g, '/').replace(/^\.?\//, '').replace(/^output\//, '');
    if (fileList.length === 1) {
        // Case-insensitive retry only: matchArtifactByRelPath compares exactly, so a
        // model that got just the casing wrong should still resolve. A link naming a
        // DIFFERENT file must not resolve — this used to map any unmatched name onto a
        // sole 报告.md, which opened a file with other contents under another name and
        // hid the fact that the claimed file was never written.
        const sole = fileList[0];
        const hrefBase = (norm.split('/').pop() ?? norm).toLowerCase();
        if (hrefBase === sole.file_name.toLowerCase()) {
            return sole;
        }
    }
    return undefined;
}

/**
 * Remove empty raw-HTML block placeholders (e.g. the styled `<div ...></div>`
 * comment/figure boxes some report templates emit) from a markdown deliverable
 * BEFORE preview.
 *
 * The client markdown pipeline deliberately does not enable rehype-raw (XSS
 * guard, see rehypeBr.ts), so raw HTML renders as escaped literal text. An empty
 * styled box is pure layout scaffolding meant for the derived HTML/PDF — in the
 * markdown preview it just leaks as an ugly `<div style=...></div>` string.
 * Stripping only *empty* paired block tags removes that noise with zero content
 * loss (content-bearing HTML is left untouched). Preview-only: the stored .md
 * keeps the tags so the HTML/PDF derivation is unaffected.
 */
export function stripEmptyHtmlPlaceholders(md: string): string {
    if (!md) return md;
    // Loop to collapse simple nesting (`<div><div></div></div>`).
    let out = md;
    let prev: string;
    do {
        prev = out;
        out = out.replace(/<(div|section|p|span|figure)\b[^>]*>\s*<\/\1>/gi, '');
    } while (out !== prev);
    return out;
}

/**
 * True for a deliverable that opens in the standalone sandboxed viewer TAB
 * instead of the in-place preview (see openHtmlArtifactViewer).
 *
 * Single source of truth for the two panel hooks that route the click and for
 * the row hint that marks it, so the marker can never disagree with what the
 * click actually does.
 */
export function isHtmlArtifact(file: ArtifactFile): boolean {
    return getFileExtension(file.file_name) === 'html';
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
 *
 * The viewer opens as its OWN tab at `/html`, so it cannot derive the share
 * token from its location the way in-page surfaces do — carry it in the query
 * when we are on a share route, or a share recipient's HTML report 403s.
 */
export function openHtmlArtifactViewer(file: ArtifactFile, versionId: string): void {
    const params = new URLSearchParams({ url: file.file_url, vid: versionId || '' });
    const shareToken = getShareTokenFromPath();
    if (shareToken) {
        params.set('share', shareToken);
    }
    window.open(`${__APP_ENV__.BASE_URL}/html?${params.toString()}`, '_blank');
}

/**
 * Give the standalone HTML viewer tab (`/html`) the right tab identity.
 *
 * The report is rendered inside a sandboxed `<iframe srcDoc>`, so its own
 * `<head>` (`<title>` / `<link rel="icon">`) cannot influence THIS browser tab —
 * the browser derives the tab title and favicon from the top-level `/html`
 * document only. Without this, a generated report tab would fall back to the
 * generic page favicon instead of the configured brand icon (品牌定制 →
 * 浏览器标签图标). So we set both here:
 *   - favicon: the brand favicon resolved by brand-runtime.js (falls back to the
 *     bundled default), so the tab matches the rest of the app;
 *   - title: the report's own `<title>`, so multiple report tabs stay
 *     distinguishable (DOMParser does not execute scripts, so reading the title
 *     from untrusted HTML is safe).
 */
export function applyHtmlViewerTabIdentity(htmlContent: string): void {
    const faviconUrl =
        window.BRAND_CONFIG?.assets?.favicon?.url ||
        `${__APP_ENV__.BASE_URL}/assets/bisheng/favicon.ico`;
    let iconLink = document.head.querySelector<HTMLLinkElement>("link[rel~='icon']");
    if (!iconLink) {
        iconLink = document.createElement('link');
        iconLink.rel = 'icon';
        document.head.appendChild(iconLink);
    }
    iconLink.href = faviconUrl;

    const reportTitle = new DOMParser()
        .parseFromString(htmlContent || '', 'text/html')
        .title.trim();
    if (reportTitle) {
        document.title = reportTitle;
    }
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
