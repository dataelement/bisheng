import type { ArtifactFile } from '~/components/Linsight/Artifacts/artifactUtils';
import { getChatAttachmentFileName, resolveChatAttachmentUrl } from './chatAttachmentUtils';

type Attachment = Parameters<typeof resolveChatAttachmentUrl>[0] & Parameters<typeof getChatAttachmentFileName>[0] & { file_id?: string };

export function toChatArtifact(file: Attachment): ArtifactFile | null {
  const url = resolveChatAttachmentUrl(file);
  if (!url) return null;
  return {
    file_id: file.file_id || url,
    file_name: getChatAttachmentFileName(file),
    file_url: url,
    directUrl: url,
  };
}

export function collectChatAttachments(messages: Array<{ files?: Attachment[] | null }>): ArtifactFile[] {
  const files = new Map<string, ArtifactFile>();
  for (const message of messages) {
    for (const attachment of message.files || []) {
      const file = toChatArtifact(attachment);
      if (file) files.set(file.file_id, file);
    }
  }
  return [...files.values()];
}
