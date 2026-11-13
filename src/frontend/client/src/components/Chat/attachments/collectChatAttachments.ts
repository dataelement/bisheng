import type { ArtifactFile } from '~/components/Linsight/Artifacts/artifactUtils';
import {
  getChatAttachmentFileName,
  getReissuableAttachment,
  resolveChatAttachmentUrl,
} from './chatAttachmentUtils';

type Attachment = Parameters<typeof resolveChatAttachmentUrl>[0] & Parameters<typeof getChatAttachmentFileName>[0] & {
  file_id?: string;
  object_name?: string;
};

export function toChatArtifact(file: Attachment, conversationId?: string): ArtifactFile | null {
  const url = resolveChatAttachmentUrl(file);
  if (!url) return null;
  const attachment = getReissuableAttachment(file, conversationId);
  return {
    file_id: file.file_id || url,
    file_name: getChatAttachmentFileName(file),
    file_url: url,
    directUrl: url,
    ...(attachment ? { attachment } : {}),
  };
}

export function collectChatAttachments(
  messages: Array<{ files?: Attachment[] | null; conversationId?: string }>,
): ArtifactFile[] {
  const files = new Map<string, ArtifactFile>();
  for (const message of messages) {
    for (const attachment of message.files || []) {
      const file = toChatArtifact(attachment, message.conversationId);
      if (file) files.set(file.file_id, file);
    }
  }
  return [...files.values()];
}
