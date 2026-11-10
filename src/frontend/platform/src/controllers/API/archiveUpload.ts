import request from '@/controllers/request';

export interface ArchiveFile {
    file_id: string;
    file_name: string;
    file_path: string;
    relative_path: string;
    source_path: string;
    display_name: string;
    archive_id: string;
    size: number;
}

export async function uploadArchive(file: File, accepts: string, signal?: AbortSignal): Promise<ArchiveFile[]> {
    const data = new FormData();
    data.append('file', file);
    data.append('accepts', accepts);
    const result = await request.post('/api/v1/knowledge/upload-archive', data, {
        headers: { 'Content-Type': 'multipart/form-data' }, signal, timeout: 90000,
    });
    // The platform interceptor unwraps the unified envelope.
    const payload = result as unknown as { files: ArchiveFile[] };
    if (!Array.isArray(payload?.files)) throw new Error('ZIP upload failed');
    return payload.files;
}
