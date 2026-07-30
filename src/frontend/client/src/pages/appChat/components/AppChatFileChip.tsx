import { useState } from 'react';
import { MediaAttachmentChip } from '~/components/Chat/attachments/MediaAttachmentChip';
import { OGDialog, OGDialogContent } from '~/components/ui';
import { getFileTypebyFileName } from '~/components/ui/icon/File/FileIcon';
import { resolveKnowledgePreviewUrl } from '~/pages/knowledge/FilePreview/previewUrlUtils';
import { isMediaAttachmentFile } from '~/utils/mediaAttachmentUtils';
import { cn } from '~/utils';
import { type AppChatFileLike, normalizeAppChatFile } from '../appChatFileUtils';
import ChatFile from './ChatFile';

const IMAGE_FILE_TYPES = new Set(['jpg', 'jpeg', 'png', 'bmp', 'gif', 'webp']);

interface AppChatFileChipProps {
    file: AppChatFileLike;
    variant?: 'bar' | 'message';
    className?: string;
}

export function AppChatFileChip({ file, variant = 'message', className }: AppChatFileChipProps) {
    const { name, path } = normalizeAppChatFile(file);
    const [previewOpen, setPreviewOpen] = useState(false);

    if (isMediaAttachmentFile({ name })) {
        return (
            <MediaAttachmentChip
                file={{
                    name,
                    filename: name,
                    filepath: path,
                    file_path: path,
                    cover_filepath: file.cover_filepath,
                    mediaDurationSec: file.mediaDurationSec,
                    parsingState: file.parsingState,
                }}
                variant={variant}
                className={className}
            />
        );
    }

    const fileType = getFileTypebyFileName(name);
    const previewUrl = path ? resolveKnowledgePreviewUrl(path) : undefined;
    const isImage = IMAGE_FILE_TYPES.has(fileType) && !!previewUrl;

    if (isImage) {
        return (
            <>
                <button
                    type="button"
                    onClick={() => setPreviewOpen(true)}
                    className={cn(
                        'group flex min-w-52 max-w-sm items-center gap-2 rounded-xl border bg-white p-2 text-left cursor-pointer',
                        className,
                    )}
                >
                    <img
                        src={previewUrl}
                        alt=""
                        className="size-10 shrink-0 rounded object-cover"
                    />
                    <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium text-gray-700" title={name}>
                            {name}
                        </div>
                    </div>
                </button>
                <OGDialog open={previewOpen} onOpenChange={setPreviewOpen}>
                    <OGDialogContent
                        showCloseButton={false}
                        className="w-auto max-w-[92vw] overflow-hidden bg-transparent p-0 shadow-none"
                        disableScroll={false}
                    >
                        <img
                            src={previewUrl}
                            alt={name}
                            className="max-h-[85vh] max-w-full rounded-md object-contain"
                        />
                    </OGDialogContent>
                </OGDialog>
            </>
        );
    }

    return <ChatFile fileName={name} filePath={path} />;
}
