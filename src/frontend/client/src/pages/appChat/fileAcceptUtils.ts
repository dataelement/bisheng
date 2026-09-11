export type UploadFileKind = 'file' | 'image' | 'media';

const FILE_SUFFIXES = [
    '.PDF', '.OFD', '.TXT', '.MD', '.HTML', '.XLS', '.XLSX', '.CSV',
    '.DOC', '.DOCX', '.PPT', '.PPTX',
];

const IMAGE_SUFFIXES = ['.PNG', '.JPEG', '.JPG', '.BMP'];

export const MEDIA_SUFFIXES = [
    '.MP3', '.WAV', '.M4A', '.AAC', '.FLAC', '.OGG',
    '.MP4', '.MOV', '.AVI', '.MKV', '.WEBM',
];

const MEDIA_EXTENSIONS = new Set(
    MEDIA_SUFFIXES.map((s) => s.slice(1).toLowerCase()),
);

export function normalizeFileAccept(
    value: unknown,
    options?: { mediaEnabled?: boolean },
): UploadFileKind[] {
    const mediaEnabled = options?.mediaEnabled ?? false;
    let kinds: UploadFileKind[] = [];

    if (Array.isArray(value)) {
        kinds = value.filter(
            (k): k is UploadFileKind => k === 'file' || k === 'image' || k === 'media',
        );
    } else if (typeof value === 'string') {
        if (value === 'all') {
            kinds = mediaEnabled ? ['file', 'image', 'media'] : ['file', 'image'];
        } else if (value === 'file' || value === 'image' || value === 'media') {
            kinds = [value];
        }
    }

    if (!mediaEnabled) {
        kinds = kinds.filter((k) => k !== 'media');
    }
    return kinds;
}

export function fileAcceptToInputAccept(kinds: UploadFileKind[]): string {
    const parts: string[] = [];
    if (kinds.includes('file')) parts.push(...FILE_SUFFIXES);
    if (kinds.includes('image')) parts.push(...IMAGE_SUFFIXES);
    if (kinds.includes('media')) parts.push(...MEDIA_SUFFIXES);
    return parts.join(',');
}

export function getFileKindByExt(ext: string): UploadFileKind {
    const normalized = ext.replace(/^\./, '').toLowerCase();
    if (MEDIA_EXTENSIONS.has(normalized)) return 'media';
    if (['png', 'jpg', 'jpeg', 'bmp'].includes(normalized)) return 'image';
    return 'file';
}

export function isMediaFileName(name: string): boolean {
    const ext = name.split('.').pop()?.toLowerCase() ?? '';
    return MEDIA_EXTENSIONS.has(ext);
}

export const MAX_MEDIA_FILES = 5;
