import { useState } from 'react';
import { OGDialog, OGDialogContent } from '~/components/ui';
import { getFileTypeIcon, getFileTypebyFileName } from '~/components/ui/icon/File/FileIcon';
import FilePreview from '~/pages/knowledge/FilePreview';
import { getViewerType } from '~/pages/knowledge/FilePreview/viewers';
import { downloadFile } from '~/utils';
import { formatBytes } from '~/utils/files';
import {
    getChatAttachmentFileName,
    resolveChatAttachmentUrl,
} from './chatAttachmentUtils';

interface ChatHistoryFileRowProps {
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
        size?: number | string;
    };
}

/** Horizontal card for documents sent in chat. */
export function ChatHistoryFileRow({ file }: ChatHistoryFileRowProps) {
    const [previewOpen, setPreviewOpen] = useState(false);
    const fileName = getChatAttachmentFileName(file);
    const fileType = getFileTypebyFileName(fileName);
    const TypeIcon = getFileTypeIcon(fileName);
    const bytes = Number(file.size ?? NaN);
    const fileDetails = [
        fileName.includes('.') ? fileType.toUpperCase() : '',
        Number.isFinite(bytes) && bytes >= 0 ? formatBytes(bytes, 1, true) : '',
    ].filter(Boolean).join(' · ');
    const fileUrl = resolveChatAttachmentUrl(file);
    const viewerType = getViewerType(fileType);
    const canPreview = !!fileUrl && viewerType !== 'unsupported';
    const canDownload = !!fileUrl && !canPreview;
    const isInteractive = canPreview || canDownload;

    const handleClick = () => {
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
            <button
                type="button"
                className="flex h-16 w-60 max-w-full shrink-0 items-center gap-2.5 rounded-2xl border border-border-base bg-bg-page px-3 text-left enabled:hover:bg-fill-1 focus-visible:shadow-focus"
                disabled={!isInteractive}
                onClick={handleClick}
                title={fileName}
            >
                <TypeIcon size={28} className="shrink-0 text-text-2" />
                <span className="min-w-0 flex-1">
                    <span className="block truncate text-body font-medium text-text-1">{fileName}</span>
                    {fileDetails && <span className="block truncate text-caption text-text-3">{fileDetails}</span>}
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
