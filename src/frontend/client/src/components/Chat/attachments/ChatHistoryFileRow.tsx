import { useState } from 'react';
import { OGDialog, OGDialogContent } from '~/components/ui';
import { getFileTypebyFileName } from '~/components/ui/icon/File/FileIcon';
import FilePreview from '~/pages/knowledge/FilePreview';
import { getViewerType } from '~/pages/knowledge/FilePreview/viewers';
import { downloadFile } from '~/utils';
import {
    getChatAttachmentFileName,
    resolveChatAttachmentUrl,
} from './chatAttachmentUtils';
import { FileUploadThumbnail } from './UploadAttachmentThumbnail';

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
    };
}

/** Square history attachment card for non-media files (doc/pdf/image/etc.). */
export function ChatHistoryFileRow({ file }: ChatHistoryFileRowProps) {
    const [previewOpen, setPreviewOpen] = useState(false);
    const fileName = getChatAttachmentFileName(file);
    const fileType = getFileTypebyFileName(fileName);
    const fileUrl = resolveChatAttachmentUrl(file);
    const viewerType = getViewerType(fileType);
    const canPreview = !!fileUrl && viewerType !== 'unsupported';
    const canDownload = !!fileUrl && !canPreview;
    const isInteractive = canPreview || canDownload;
    const previewUrl = viewerType === 'image' ? fileUrl : undefined;

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
            <FileUploadThumbnail
                fileName={fileName}
                previewUrl={previewUrl}
                variant="message"
                onClick={isInteractive ? handleClick : undefined}
            />

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
