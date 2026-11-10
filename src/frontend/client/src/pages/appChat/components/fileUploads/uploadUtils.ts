import type { ArchiveFile } from '~/api/archiveUpload';
import { isFileNameAccepted } from '~/common/chatAccept';
import { getMediaKind } from '~/utils/mediaAttachmentUtils';

export type UploadAttachment = {
    id: string;
    name: string;
    fileId?: string;
    file_id?: string;
    filePath?: string;
    isUploading?: boolean;
    parsingStatus?: string;
    cover_filepath?: string;
    mediaCoverUrl?: string;
    mediaPreviewUrl?: string;
    mediaDurationSec?: number;
    previewUrl?: string;
};

export type ParseStatusEntry = {
    parsing_status?: string;
    cover_filepath?: string;
};

type UploadPayload = {
    filepath?: string;
    file_path?: string;
    file_id?: string;
    cover_filepath?: string;
    parsing_status?: string;
    archive_files?: ArchiveFile[];
};

/** Isolated blob for XHR: preview readers must not stall the transfer. */
export function createUploadPayload(file: File): File | Blob {
    if (getMediaKind(file.name) === 'video') {
        return file.slice(0, file.size, file.type || undefined);
    }
    return file;
}

/** Accept both unified API envelopes and legacy upload payloads. */
export function unwrapUploadPayload(response: unknown): UploadPayload {
    const envelope = response as { status_code?: number; data?: UploadPayload } | null;
    if (envelope?.status_code != null && envelope.data != null) return envelope.data;
    if (envelope?.data?.filepath != null || envelope?.data?.file_path != null) return envelope.data;
    return (response ?? {}) as UploadPayload;
}

export function notifyUploadedFiles<T>(getUploadedFileIds: () => T[], onChange: (files: T[]) => void) {
    const uploaded = getUploadedFileIds();
    onChange(uploaded.length ? uploaded : []);
}

export function logUploadStage(fileName: string, stage: string, startedAt: number, extra?: Record<string, unknown>) {
    const elapsedMs = Math.round(performance.now() - startedAt);
    console.info(`[client.media_upload] STAGE ${stage} elapsed_ms=${elapsedMs} file=${fileName}`, extra ?? '');
}

export function normalizeParseStatusEntry(entry: unknown): ParseStatusEntry | null {
    if (typeof entry === 'string') return { parsing_status: entry };
    if (entry && typeof entry === 'object') return entry as ParseStatusEntry;
    return null;
}

export function applyParseStatusToFile<T extends UploadAttachment>(file: T, entry: ParseStatusEntry) {
    const nextStatus = entry.parsing_status;
    if (!nextStatus || nextStatus === 'failed') return null;
    const coverFilepath = entry.cover_filepath;
    const next = {
        ...file,
        parsingStatus: nextStatus,
        isUploading: false,
        ...(coverFilepath ? { cover_filepath: coverFilepath } : {}),
    };
    if (coverFilepath && file.mediaCoverUrl?.startsWith('blob:')) {
        URL.revokeObjectURL(file.mediaCoverUrl);
        next.mediaCoverUrl = undefined;
    }
    return next;
}

export function isUploadFileParsing(file: UploadAttachment, uploadMode?: string) {
    if (!file?.parsingStatus || ['completed', 'failed'].includes(file.parsingStatus)) return false;
    return uploadMode === 'linsight';
}

export function checkFileType(file: File, accepts?: string) {
    if (!accepts || accepts === '*') return true;
    if (isFileNameAccepted(file.name, accepts)) return true;
    return accepts.split(',').map(type => type.trim().toLowerCase())
        .some(type => !type.startsWith('.') && file.type.match(new RegExp(type.replace('*', '.*'))));
}
