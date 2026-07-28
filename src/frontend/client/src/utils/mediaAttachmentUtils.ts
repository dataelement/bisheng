import { isMediaFileName } from '~/pages/knowledge/knowledgeUtils';
import { resolveKnowledgePreviewUrl } from '~/pages/knowledge/FilePreview/previewUrlUtils';

export type MediaAttachmentKind = 'audio' | 'video';

export type MediaParsingState = 'parsing' | 'done';

const VIDEO_EXTENSIONS = new Set(['mp4', 'mov', 'avi', 'mkv', 'webm']);

export function isMediaAttachmentFile(file: { name?: string; file_name?: string; filename?: string }): boolean {
    const name = file.name || file.file_name || file.filename || '';
    return isMediaFileName(name);
}

export function getMediaKind(fileName: string): MediaAttachmentKind {
    const ext = fileName.split('.').pop()?.toLowerCase() ?? '';
    return VIDEO_EXTENSIONS.has(ext) ? 'video' : 'audio';
}

/** Format seconds as m:ss (omit when invalid). */
export function formatMediaDuration(seconds?: number | null): string | undefined {
    if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return undefined;
    const total = Math.floor(seconds);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
}

/** Read duration from a local File via loadedmetadata (caller owns object URL lifecycle). */
export function readMediaDurationFromFile(file: File): Promise<number | undefined> {
    return new Promise((resolve) => {
        const url = URL.createObjectURL(file);
        const kind = getMediaKind(file.name);
        const el = document.createElement(kind === 'video' ? 'video' : 'audio');
        el.preload = 'metadata';
        el.muted = true;

        const cleanup = () => {
            URL.revokeObjectURL(url);
            el.removeAttribute('src');
            el.load();
        };

        el.onloadedmetadata = () => {
            const duration = el.duration;
            cleanup();
            if (!Number.isFinite(duration) || duration <= 0) {
                resolve(undefined);
                return;
            }
            resolve(duration);
        };
        el.onerror = () => {
            cleanup();
            resolve(undefined);
        };
        el.src = url;
    });
}

export function resolveMediaPlaybackUrl(file: {
    filepath?: string;
    file_path?: string;
    mediaPreviewUrl?: string;
    previewUrl?: string;
}): string | undefined {
    const local = file.mediaPreviewUrl || file.previewUrl;
    if (local) return local;
    const remote = file.filepath || file.file_path;
    if (!remote) return undefined;
    return resolveKnowledgePreviewUrl(remote);
}
