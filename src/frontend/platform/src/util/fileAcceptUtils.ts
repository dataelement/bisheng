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

/** Normalize legacy string or array dialog_file_accept / form file_type. */
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

/**
 * Whether an upload-type setting includes images.
 *
 * The setting (`dialog_file_accept` on dialog input, `file_type` on a form item)
 * became a multi-select and holds an array of kinds now, where it used to hold
 * one of the strings 'all' / 'file' / 'image'. Comparing it to a bare string
 * still compiles and still runs — it just never matches, which is how the image
 * variable stayed on offer for a document-only node and stopped being named
 * when the type was changed. Ask through here so both shapes answer the same.
 *
 * Media stays enabled while normalizing: this asks about images, and whether
 * the deployment offers audio/video has no bearing on the answer.
 */
export function acceptsImages(value: unknown): boolean {
    return normalizeFileAccept(value, { mediaEnabled: true }).includes('image');
}

/** Build `<input accept="">` value from normalized kinds. */
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
