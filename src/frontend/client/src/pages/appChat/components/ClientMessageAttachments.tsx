import { ConversationAttachments } from '@bisheng/chat';
import type { ChatAttachment, ChatMessage } from '@bisheng/chat/core';
import { useCallback } from 'react';
import { getAttachmentUrl } from '~/api/chatApi';
import { MediaAttachmentChip } from '~/components/Chat/attachments/MediaAttachmentChip';
import { useLocalize } from '~/hooks';
import { resolveKnowledgePreviewUrl } from '~/pages/knowledge/FilePreview/previewUrlUtils';
import { downloadFile } from '~/utils';
const resolveUrl = (url: string) => resolveKnowledgePreviewUrl(url) ?? url;

export function ClientMessageAttachments({ message, conversationId }: { message: ChatMessage; conversationId: string }) {
    const t = useLocalize();
    const getImageUrl = useCallback((file: ChatAttachment) => file.id && conversationId ? getAttachmentUrl(conversationId, file.id) : Promise.resolve(file.url), [conversationId]);
    return <ConversationAttachments files={message.files} services={{ resolveUrl,
        getImageUrl: message.kind === 'user' ? getImageUrl : undefined,
        onDownload: file => downloadFile(resolveUrl(file.url), file.name),
        renderMedia: file => <MediaAttachmentChip variant="message" file={{ ...file.raw, name: file.name, filename: file.name, filepath: file.url, file_path: file.url }} />,
        labels: { formatError: t('com_agent_runtime.format_error'), download: t('shared:app_chat.attachment_download'), unavailable: t('shared:app_chat.attachment_unavailable'), close: t('shared:app_chat.close'), preview: t('shared:app_chat.image_preview') },
    }} />;
}
