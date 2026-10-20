import { useState } from 'react';
import { OGDialog, OGDialogContent } from '~/components/ui';
import { FileIcon, getFileTypebyFileName } from '~/components/ui/icon/File/FileIcon';
import FilePreview from '~/pages/knowledge/FilePreview';
import { getViewerType } from '~/pages/knowledge/FilePreview/viewers';
import { downloadFile } from '~/utils';
import {
    getChatAttachmentFileName,
    resolveChatAttachmentUrl,
} from './chatAttachmentUtils';
import { toChatArtifact } from './collectChatAttachments';
import type { ArtifactFile } from '~/components/Linsight/Artifacts/artifactUtils';

interface ChatHistoryFileRowProps {
    onPreviewFile?: (file: ArtifactFile) => void;
    file: {
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
export function ChatHistoryFileRow({ file, onPreviewFile }: ChatHistoryFileRowProps) {
    const [previewOpen, setPreviewOpen] = useState(false);
    const fileName = getChatAttachmentFileName(file);
    const fileType = getFileTypebyFileName(fileName);
    const fileUrl = resolveChatAttachmentUrl(file);
    const viewerType = getViewerType(fileType);
    const canPreview = !!fileUrl && viewerType !== 'unsupported';
    const canDownload = !!fileUrl && !canPreview;
    const isInteractive = canPreview || canDownload;

    const handleClick = () => {
        const artifact = toChatArtifact(file);
        if (artifact && onPreviewFile) {
            onPreviewFile(artifact);
            return;
        }
        if (canPreview) {
            setPreviewOpen(true);
            return;
        }
        if (canDownload && fileUrl) {
            downloadFile(fileUrl, fileName);
        }
    };

    return (
        <>
            <button type="button" className="dsh-chat-attachment" onClick={handleClick} disabled={!isInteractive}
                title={fileName}>
                <FileIcon type={fileType || 'txt'} className="size-7 shrink-0" />
                <span className="min-w-0 flex-1">
                    <span className="dsh-resource-name block text-text-1">{fileName}</span>
                    <span className="dsh-resource-meta block">{fileType.toUpperCase()}</span>
                </span>
            </button>

            {canPreview && fileUrl && (
                <OGDialog open={previewOpen} onOpenChange={setPreviewOpen}>
                    <OGDialogContent
                        showCloseButton
                        className="flex h-[min(85vh,900px)] w-[min(92vw,960px)] max-w-none flex-col overflow-hidden p-0"
                    >
                        <FilePreview
                            fileName={fileName}
                            fileType={fileType}
                            fileUrl={fileUrl}
                        />
                    </OGDialogContent>
                </OGDialog>
            )}
        </>
    );
}
