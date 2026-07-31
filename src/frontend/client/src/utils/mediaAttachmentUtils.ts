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

/** Uppercase file extension label for history cards, e.g. MP3. */
export function getMediaFileExtensionLabel(fileName: string): string {
    const baseName = fileName.split('/').pop()?.split('?')[0] || fileName;
    const ext = baseName.includes('.') ? baseName.split('.').pop() : '';
    return (ext || 'FILE').toUpperCase();
}

/** Basename without extension for truncated history card labels. */
export function getMediaDisplayBaseName(fileName: string): string {
    const baseName = fileName.split('/').pop()?.split('?')[0] || fileName;
    const dotIndex = baseName.lastIndexOf('.');
    return dotIndex > 0 ? baseName.slice(0, dotIndex) : baseName;
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

/** Capture a JPEG poster from the first decoded video frame for local chip preview. */
export function captureVideoPosterFromFile(file: File): Promise<string | undefined> {
    return new Promise((resolve) => {
        const url = URL.createObjectURL(file);
        const video = document.createElement('video');
        video.muted = true;
        video.playsInline = true;
        video.preload = 'auto';

        const cleanup = () => {
            URL.revokeObjectURL(url);
            video.removeAttribute('src');
            video.load();
        };

        video.onloadeddata = () => {
            video.currentTime = 0.001;
        };
        video.onseeked = () => {
            try {
                const width = video.videoWidth;
                const height = video.videoHeight;
                if (!width || !height) {
                    cleanup();
                    resolve(undefined);
                    return;
                }
                const canvas = document.createElement('canvas');
                canvas.width = width;
                canvas.height = height;
                const ctx = canvas.getContext('2d');
                if (!ctx) {
                    cleanup();
                    resolve(undefined);
                    return;
                }
                ctx.drawImage(video, 0, 0, width, height);
                canvas.toBlob(
                    (blob) => {
                        cleanup();
                        resolve(blob ? URL.createObjectURL(blob) : undefined);
                    },
                    'image/jpeg',
                    0.85,
                );
            } catch {
                cleanup();
                resolve(undefined);
            }
        };
        video.onerror = () => {
            cleanup();
            resolve(undefined);
        };
        video.src = url;
    });
}

/** Strip presigned query params; keep bucket/object path only. */
export function stripMinioPresignedQuery(filepath: string): string {
    if (!filepath) return filepath;
    if (/^https?:\/\//.test(filepath)) {
        try {
            return new URL(filepath).pathname;
        } catch {
            // fall through
        }
    }
    const queryIndex = filepath.indexOf('?');
    return queryIndex >= 0 ? filepath.slice(0, queryIndex) : filepath;
}

/** Normalize stored MinIO paths before share-url refresh requests. */
export function normalizeMinioObjectPath(filepath: string): string {
    let path = stripMinioPresignedQuery(filepath);
    for (let i = 0; i < 2; i += 1) {
        try {
            const decoded = decodeURIComponent(path);
            if (decoded === path) break;
            path = decoded;
        } catch {
            break;
        }
    }
    return path;
}

export function extractMediaFilepath(file: {
    filepath?: string;
    file_path?: string;
    file_url?: string;
    url?: string;
    path?: string;
}): string | undefined {
    const remote = file.filepath || file.file_path || file.file_url || file.url || file.path;
    if (!remote || remote.startsWith('blob:')) return undefined;
    return remote;
}

export function extractMediaCoverFilepath(file: {
    cover_filepath?: string;
}): string | undefined {
    const remote = file.cover_filepath;
    if (!remote || remote.startsWith('blob:')) return undefined;
    return remote;
}

export function resolveMediaCoverUrl(file: {
    cover_filepath?: string;
    mediaCoverUrl?: string;
}): string | undefined {
    const local = file.mediaCoverUrl;
    if (local) return local;
    const remote = extractMediaCoverFilepath(file);
    if (!remote) return undefined;
    return resolveKnowledgePreviewUrl(remote);
}

export function resolveMediaPlaybackUrl(file: {
    filepath?: string;
    file_path?: string;
    file_url?: string;
    url?: string;
    path?: string;
    mediaPreviewUrl?: string;
    previewUrl?: string;
}): string | undefined {
    const local = file.mediaPreviewUrl || file.previewUrl;
    if (local) return local;
    const remote = extractMediaFilepath(file);
    if (!remote) return undefined;
    return resolveKnowledgePreviewUrl(remote);
}

/** History rows must not replay ephemeral UI-only parsing flags. */
export function normalizeHistoryMediaFiles<T extends Record<string, unknown>>(files: T[]): T[] {
    if (!Array.isArray(files) || !files.length) return files;
    return files.map((file) => {
        if (!isMediaAttachmentFile(file as { name?: string; file_name?: string; filename?: string })) {
            return file;
        }
        if (file.parsingState !== 'parsing') return file;
        const { parsingState, ...rest } = file;
        return rest as T;
    });
}
