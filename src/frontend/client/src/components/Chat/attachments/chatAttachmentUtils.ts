import { getAttachmentUrl } from '~/api/chatApi';
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

/** The conversation attachment a fresh link can be issued for, if the file was kept permanently. */
export function getReissuableAttachment(
    file: { file_id?: string; object_name?: string },
    conversationId?: string,
): { conversationId: string; fileId: string } | undefined {
    if (!conversationId || !file.file_id || !file.object_name) return undefined;
    return { conversationId, fileId: String(file.file_id) };
}

/**
 * A fresh link for a kept attachment. The stored link expires with the temp
 * bucket, so it is only the answer when no fresh one can be issued.
 */
export async function reissueAttachmentUrl(
    attachment: { conversationId: string; fileId: string } | undefined,
    fallback: string | undefined,
): Promise<string | undefined> {
    if (!attachment) return fallback;
    const fresh = await getAttachmentUrl(attachment.conversationId, attachment.fileId);
    return fresh ? resolveKnowledgePreviewUrl(fresh) : fallback;
}
