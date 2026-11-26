import { useState, type ComponentProps } from 'react';
import type { ArtifactFile } from '~/components/Linsight/Artifacts/artifactUtils';
import { groupAttachmentsByFolder } from '~/components/Linsight/Input/ContextChips';
import { isImageFileName } from '~/components/ui/icon/File/FileIcon';
import { MessageImage } from '../Messages/Content/MessageImage';
import { FolderAttachmentResourceCard } from './AttachmentResourceCards';
import { ChatHistoryFileRow } from './ChatHistoryFileRow';
import { isMediaChipFile, MediaAttachmentChip, type MediaAttachmentFile } from './MediaAttachmentChip';
import { getChatAttachmentFileName } from './chatAttachmentUtils';

type Attachment = ComponentProps<typeof ChatHistoryFileRow>['file'] & MediaAttachmentFile & {
    clientId?: string;
    relative_path?: string;
};
type DisplayAttachment = Attachment & { clientId: string; name: string };

interface AttachmentPreviewProps {
    conversationId?: string;
    onPreviewFile?: (file: ArtifactFile) => void;
}

function MessageAttachment({ file, conversationId, onPreviewFile }: AttachmentPreviewProps & { file: DisplayAttachment }) {
    if (isImageFileName(file.name)) {
        return <MessageImage
            variant="resource"
            conversationId={conversationId}
            fileId={file.file_id}
            altText={file.name}
            initialUrl={file.filepath || file.file_path || file.file_url}
        />;
    }
    if (isMediaChipFile(file)) return <MediaAttachmentChip file={file} variant="resource" />;
    return <ChatHistoryFileRow file={file} variant="resource" conversationId={conversationId} onPreviewFile={onPreviewFile} />;
}

interface MessageAttachmentFolderProps extends AttachmentPreviewProps {
    name: string;
    files: DisplayAttachment[];
}

function MessageAttachmentFolder({ name, files, conversationId, onPreviewFile }: MessageAttachmentFolderProps) {
    const [expanded, setExpanded] = useState(false);
    return <div className="flex min-w-0 max-w-full flex-col items-end">
        <FolderAttachmentResourceCard name={name} fileCount={files.length} expanded={expanded}
            onClick={() => setExpanded(value => !value)} />
        {expanded && <div className="dsh-attachment-rail mt-2 flex max-w-full flex-wrap justify-end">
            {files.map(file => <MessageAttachment key={file.clientId} file={file} conversationId={conversationId} onPreviewFile={onPreviewFile} />)}
        </div>}
    </div>;
}

interface MessageAttachmentsProps extends AttachmentPreviewProps {
    files?: Attachment[];
}

/** Sent uploads use the composer's cards, with folder members opened on demand. */
export function MessageAttachments({ files, conversationId, onPreviewFile }: MessageAttachmentsProps) {
    if (!files?.length) return null;
    const groups = groupAttachmentsByFolder(files.map((file, index) => ({
        ...file,
        clientId: String(file.clientId ?? file.file_id ?? index),
        name: getChatAttachmentFileName(file),
    })));

    return <div className="dsh-attachment-rail mb-2 mt-1 flex min-w-0 max-w-full flex-wrap justify-end">
        {groups.map(group => group.folderName ? (
            <MessageAttachmentFolder key={group.key} name={group.folderName} files={group.files}
                conversationId={conversationId} onPreviewFile={onPreviewFile} />
        ) : (
            <MessageAttachment key={group.key} file={group.files[0]} conversationId={conversationId} onPreviewFile={onPreviewFile} />
        ))}
    </div>;
}
