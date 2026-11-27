import request from './request';

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

interface ArchiveResult {
    files: ArchiveFile[];
    archive_id: string;
    archive_name: string;
    ignored: string[];
}

export async function uploadArchive(file: File, accepts: string, signal?: AbortSignal): Promise<ArchiveResult> {
    const data = new FormData();
    data.append('file', file);
    data.append('accepts', accepts);
    const result = await request.post('/api/v1/knowledge/upload-archive', data, {
        headers: { 'Content-Type': 'multipart/form-data' }, signal, timeout: 90000,
    });
    if (result?.status_code !== 200 || !Array.isArray(result.data?.files)) {
        throw new Error(result?.status_message || 'ZIP upload failed');
    }
    return result.data;
}
