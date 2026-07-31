import { resolveKnowledgePreviewUrl } from '~/pages/knowledge/FilePreview/previewUrlUtils';

export function getChatAttachmentFileName(file: {
    name?: string;
    file_name?: string;
    filename?: string;
}): string {
    return file.name || file.file_name || file.filename || 'File';
}

export function resolveChatAttachmentUrl(file: {
    filepath?: string;
    file_path?: string;
    file_url?: string;
    url?: string;
    path?: string;
    previewUrl?: string;
}): string | undefined {
    if (file.previewUrl) return file.previewUrl;
    const remote = file.filepath || file.file_path || file.file_url || file.url || file.path;
    if (!remote || remote.startsWith('blob:')) return undefined;
    return resolveKnowledgePreviewUrl(remote);
}
