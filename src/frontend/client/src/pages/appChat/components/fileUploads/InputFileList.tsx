import { MediaAttachmentChip } from '~/components/Chat/attachments/MediaAttachmentChip';
import { FileUploadThumbnail } from '~/components/Chat/attachments/UploadAttachmentThumbnail';
import { isMediaAttachmentFile } from '~/utils/mediaAttachmentUtils';
import { isUploadFileParsing, type UploadAttachment } from './uploadUtils';

export interface InputFileListProps {
    files: UploadAttachment[];
    uploadMode?: string;
    onRemove: (clientId: string) => void;
}

export function InputFileList({ files, uploadMode, onRemove }: InputFileListProps) {
    const renderInlineFileChip = (file: UploadAttachment, index: number) => {
        const isMedia = isMediaAttachmentFile({ name: file.name });
        const isParsing = isUploadFileParsing(file, uploadMode);

        if (isMedia) {
            return (
                <MediaAttachmentChip
                    key={file.id || index}
                    file={{
                        name: file.name,
                        filepath: file.filePath,
                        cover_filepath: file.cover_filepath,
                        isUploading: file.isUploading || isParsing,
                        mediaPreviewUrl: file.mediaPreviewUrl,
                        mediaCoverUrl: file.mediaCoverUrl,
                        mediaDurationSec: file.mediaDurationSec,
                        parsingState: isParsing ? 'parsing' : undefined,
                    }}
                    onRemove={() => onRemove(file.id)}
                    variant="bar"
                />
            );
        }

        return (
            <FileUploadThumbnail
                key={file.id || index}
                fileName={file.name}
                previewUrl={/\.(png|jpe?g|bmp|gif|webp)$/i.test(file.name) ? file.previewUrl : undefined}
                variant="bar"
                isUploading={file.isUploading || isParsing}
                onRemove={() => onRemove(file.id)}
            />
        );
    };

    return <div className="flex max-w-full gap-2 overflow-x-auto overflow-y-hidden p-2 pb-3">
        {files.map(renderInlineFileChip)}
    </div>;
}
