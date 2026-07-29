import { Loader2, Play, Video } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import useLocalize from '~/hooks/useLocalize';
import {
    extractMediaFilepath,
    formatMediaDuration,
    getMediaDisplayBaseName,
    getMediaFileExtensionLabel,
    getMediaKind,
    isMediaAttachmentFile,
    resolveMediaCoverUrl,
    resolveMediaPlaybackUrl,
    type MediaParsingState,
} from '~/utils/mediaAttachmentUtils';
import { cn } from '~/utils';
import {
    UploadAttachmentThumbnailShell,
    type UploadThumbnailVariant,
} from './UploadAttachmentThumbnail';

export interface MediaAttachmentFile {
    name?: string;
    file_name?: string;
    filename?: string;
    filepath?: string;
    file_path?: string;
    isUploading?: boolean;
    mediaPreviewUrl?: string;
    previewUrl?: string;
    cover_filepath?: string;
    mediaCoverUrl?: string;
    mediaDurationSec?: number;
    parsingState?: MediaParsingState;
}

interface MediaAttachmentChipProps {
    file: MediaAttachmentFile;
    /** Input bar chips may remove; sent-message chips are read-only. */
    onRemove?: () => void;
    /** Compact row in message bubble vs wider input-bar card. */
    variant?: UploadThumbnailVariant;
    className?: string;
}

export function MediaAttachmentChip({
    file,
    onRemove,
    variant = 'bar',
    className,
}: MediaAttachmentChipProps) {
    const localize = useLocalize();
    const navigate = useNavigate();

    const fileName = file.name || file.file_name || file.filename || 'Media';
    const kind = getMediaKind(fileName);
    const durationLabel = formatMediaDuration(file.mediaDurationSec);
    const isUploading = !!file.isUploading;
    const isParsing = file.parsingState === 'parsing';
    const playbackUrl = resolveMediaPlaybackUrl(file);
    const coverUrl = kind === 'video' ? resolveMediaCoverUrl(file) : undefined;
    const mediaFilepath = extractMediaFilepath(file);
    const canPlay = !!playbackUrl && !isUploading;
    const parsingLabel = localize('com_chat.media_parsing');
    const isSquareCard = variant === 'message' || variant === 'bar';

    const handlePlay = () => {
        if (!canPlay || !playbackUrl) return;
        navigate('/c/media-playback', {
            state: {
                url: playbackUrl,
                filepath: mediaFilepath,
                name: fileName,
                kind,
            },
        });
    };

    if (isSquareCard && kind === 'video') {
        return (
            <UploadAttachmentThumbnailShell
                fileName={fileName}
                variant={variant}
                canClick={canPlay}
                isUploading={isUploading}
                onClick={handlePlay}
                onRemove={onRemove}
                allowRemoveWhileUploading={variant === 'bar'}
                className={cn('bg-[#f0f0f0]', className)}
                overlay={
                    isParsing ? (
                        <div className="absolute inset-0 flex items-center justify-center bg-black/45 px-2 text-center text-xs text-white">
                            {parsingLabel}
                        </div>
                    ) : undefined
                }
            >
                {coverUrl ? (
                    <img src={coverUrl} alt="" className="size-full object-cover" />
                ) : (
                    <div className="flex size-full items-center justify-center text-[#999]">
                        <Video className="size-8" />
                    </div>
                )}

                {canPlay && (
                    <div className="absolute bottom-2 left-2 flex items-center gap-1 rounded-full bg-white px-2 py-0.5 text-xs font-medium leading-none text-[#212121] shadow-sm">
                        <Play className="size-3 shrink-0" />
                        {durationLabel && <span>{durationLabel}</span>}
                    </div>
                )}
            </UploadAttachmentThumbnailShell>
        );
    }

    if (isSquareCard && kind === 'audio') {
        const extensionLabel = getMediaFileExtensionLabel(fileName);
        const displayName = getMediaDisplayBaseName(fileName);

        return (
            <UploadAttachmentThumbnailShell
                fileName={fileName}
                variant={variant}
                canClick={canPlay}
                isUploading={isUploading}
                onClick={handlePlay}
                onRemove={onRemove}
                allowRemoveWhileUploading={variant === 'bar'}
                className={className}
                overlay={
                    isParsing ? (
                        <div className="absolute inset-0 flex items-center justify-center bg-black/45 px-2 text-center text-xs text-white">
                            {parsingLabel}
                        </div>
                    ) : undefined
                }
            >
                <span className="absolute left-3 top-3 text-sm font-medium text-[#666]">
                    {extensionLabel}
                </span>
                <span className="absolute bottom-3 left-3 right-3 truncate text-sm text-[#333]">
                    {displayName}
                </span>
            </UploadAttachmentThumbnailShell>
        );
    }

    return null;
}

export function isMediaChipFile(file: unknown): file is MediaAttachmentFile {
    return !!file && typeof file === 'object' && isMediaAttachmentFile(file as MediaAttachmentFile);
}
