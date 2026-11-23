import { useState } from 'react';
import { OGDialog, OGDialogContent } from '~/components/ui';
import { getFileTypeIcon, getFileTypebyFileName } from '~/components/ui/icon/File/FileIcon';
import FilePreview from '~/pages/knowledge/FilePreview';
import { getViewerType } from '~/pages/knowledge/FilePreview/viewers';
import { downloadFile } from '~/utils';
import {
    getChatAttachmentFileName,
    getReissuableAttachment,
    reissueAttachmentUrl,
    resolveChatAttachmentUrl,
} from './chatAttachmentUtils';
import { toChatArtifact } from './collectChatAttachments';
import type { ArtifactFile } from '~/components/Linsight/Artifacts/artifactUtils';

interface ChatHistoryFileRowProps {
    onPreviewFile?: (file: ArtifactFile) => void;
    /** Lets a kept attachment open through a fresh link instead of its expiring upload link. */
    conversationId?: string;
    file: {
        file_id?: string;
        object_name?: string;
        name?: string;
        file_name?: string;
        filename?: string;
        filepath?: string;
        file_path?: string;
        file_url?: string;
        url?: string;
        path?: string;
        previewUrl?: string;
    };
}

/** Horizontal history attachment card with a shared workspace preview. */
export function ChatHistoryFileRow({ file, conversationId, onPreviewFile }: ChatHistoryFileRowProps) {
    const [previewUrl, setPreviewUrl] = useState<string | null>(null);
    const fileName = getChatAttachmentFileName(file);
    const fileType = getFileTypebyFileName(fileName);
    const TypeIcon = getFileTypeIcon(fileName);
    const fileUrl = resolveChatAttachmentUrl(file);
    const viewerType = getViewerType(fileType);
    const canPreview = !!fileUrl && viewerType !== 'unsupported';
    const canDownload = !!fileUrl && !canPreview;
    const isInteractive = canPreview || canDownload;

    const handleClick = async () => {
        const artifact = toChatArtifact(file, conversationId);
        if (artifact && onPreviewFile) {
            onPreviewFile(artifact);
            return;
        }
        const url = await reissueAttachmentUrl(getReissuableAttachment(file, conversationId), fileUrl);
        if (!url) return;
        if (canPreview) {
            setPreviewUrl(url);
            return;
        }
        if (canDownload) {
            downloadFile(url, fileName);
        }
    };

    return (
        <>
            <button type="button" className="dsh-chat-attachment" onClick={handleClick} disabled={!isInteractive}
                title={fileName}>
                <span className="dsh-resource-icon"><TypeIcon size={28} /></span>
                <span className="min-w-0 flex-1">
                    <span className="dsh-resource-name block text-text-1">{fileName}</span>
                    <span className="dsh-resource-meta block">{fileType.toUpperCase()}</span>
                </span>
            </button>

            {canPreview && previewUrl && (
                <OGDialog open onOpenChange={(open) => !open && setPreviewUrl(null)}>
                    <OGDialogContent
                        showCloseButton
                        className="flex h-[min(85vh,900px)] w-[min(92vw,960px)] max-w-none flex-col overflow-hidden p-0"
                    >
                        <FilePreview
                            fileName={fileName}
                            fileType={fileType}
                            fileUrl={previewUrl}
                        />
                    </OGDialogContent>
                </OGDialog>
            )}
        </>
    );
}
