import { Loader2, Play, Video } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import useLocalize from '~/hooks/useLocalize';
import usePrefersMobileLayout from '~/hooks/usePrefersMobileLayout';
import MediaPlaybackDialog from './MediaPlaybackDialog';
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
    InputPanelFileLabels,
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
    const isMobile = usePrefersMobileLayout();
    const [playbackOpen, setPlaybackOpen] = useState(false);

    const fileName = file.name || file.file_name || file.filename || 'Media';
    const kind = getMediaKind(fileName);
    const durationLabel = formatMediaDuration(file.mediaDurationSec);
    const isUploading = !!file.isUploading;
    const isParsing = file.parsingState === 'parsing';
    const playbackUrl = resolveMediaPlaybackUrl(file);
    const rawCoverUrl = kind === 'video' ? resolveMediaCoverUrl(file) : undefined;
    // A `blob:` cover is the composer's local first frame, captured off the picked
    // file and revoked the moment the message is sent. The composer shows it; a
    // sent bubble must not, or it would pin a dead URL that also outranks the
    // server cover once parsing produces one.
    const resolvedCoverUrl =
        variant === 'message' && rawCoverUrl?.startsWith('blob:') ? undefined : rawCoverUrl;
    // A composer poster is a local blob that is revoked once the message is sent;
    // the sent bubble then holds a dead URL until the server cover arrives. Fall
    // back to the icon instead of rendering a broken image.
    const [coverFailed, setCoverFailed] = useState(false);
    useEffect(() => {
        setCoverFailed(false);
    }, [resolvedCoverUrl]);
    const coverUrl = coverFailed ? undefined : resolvedCoverUrl;
    const mediaFilepath = extractMediaFilepath(file);
    const canPlay = !!playbackUrl && !isUploading;
    const parsingLabel = localize('com_chat.media_parsing');
    const isSquareCard = variant === 'message' || variant === 'bar';

    const playbackSource = {
        url: playbackUrl,
        filepath: mediaFilepath,
        name: fileName,
        kind,
    };

    // Only mounted on pointer devices; a phone navigates to the full-screen page.
    const playbackDialog = isMobile ? null : (
        <MediaPlaybackDialog open={playbackOpen} onOpenChange={setPlaybackOpen} source={playbackSource} />
    );

    const handlePlay = () => {
        if (!canPlay || !playbackUrl) return;
        // A phone gets the whole screen and the platform's own back gesture; a
        // pointer device gets a dialog, because navigating away would tear down
        // the composer and lose attachments staged but not yet sent.
        if (isMobile) {
            navigate('/c/media-playback', { state: playbackSource });
            return;
        }
        setPlaybackOpen(true);
    };

    if (isSquareCard && kind === 'video') {
        const extensionLabel = getMediaFileExtensionLabel(fileName);
        const displayName = getMediaDisplayBaseName(fileName);

        return (
            <>
                <UploadAttachmentThumbnailShell
                    fileName={fileName}
                    variant={variant}
                    canClick={canPlay}
                    isUploading={isUploading}
                    onClick={handlePlay}
                    onRemove={onRemove}
                    allowRemoveWhileUploading={variant === 'bar'}
                    showHoverFileName={false}
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
                        <img
                            src={coverUrl}
                            alt=""
                            className="size-full object-cover"
                            onError={() => setCoverFailed(true)}
                        />
                    ) : (
                        <>
                            <div className="flex size-full items-center justify-center text-[#999]">
                                <Video className="size-8" />
                            </div>
                            <InputPanelFileLabels
                                extensionLabel={extensionLabel}
                                displayName={displayName}
                                variant={variant}
                            />
                            {variant === 'message' && (
                                <>
                                    <span className="absolute left-3 top-3 text-sm font-medium text-[#666]">
                                        {extensionLabel}
                                    </span>
                                    <span className="absolute bottom-3 left-3 right-3 truncate text-sm text-[#333]">
                                        {displayName}
                                    </span>
                                </>
                            )}
                        </>
                    )}

                    {canPlay && coverUrl && (
                        <div
                            className={cn(
                                'absolute bottom-2 left-2 z-[1] flex items-center gap-1 rounded-full bg-white px-2 py-0.5 text-xs font-medium leading-none text-[#212121] shadow-sm transition-opacity',
                                variant === 'bar' && 'group-hover:opacity-0',
                            )}
                        >
                            <Play className="size-3 shrink-0" />
                            {durationLabel && <span>{durationLabel}</span>}
                        </div>
                    )}

                    {/* No cover yet — a video the user has only just picked, since
                        the poster comes back from the server. The duration is
                        known regardless (it is read off the local file), so it
                        goes top-right, opposite the extension label, rather than
                        over the file name at the bottom. */}
                    {!coverUrl && durationLabel && (
                        <span className="absolute right-3 top-3 z-[1] text-sm text-[#666]">
                            {durationLabel}
                        </span>
                    )}
                </UploadAttachmentThumbnailShell>
                {playbackDialog}
            </>
        );
    }

    if (isSquareCard && kind === 'audio') {
        const extensionLabel = getMediaFileExtensionLabel(fileName);
        const displayName = getMediaDisplayBaseName(fileName);

        return (
            <>
                <UploadAttachmentThumbnailShell
                    fileName={fileName}
                    variant={variant}
                    canClick={canPlay}
                    isUploading={isUploading}
                    onClick={handlePlay}
                    onRemove={onRemove}
                    allowRemoveWhileUploading={variant === 'bar'}
                    showHoverFileName={false}
                    className={className}
                    overlay={
                        isParsing ? (
                            <div className="absolute inset-0 flex items-center justify-center bg-black/45 px-2 text-center text-xs text-white">
                                {parsingLabel}
                            </div>
                        ) : undefined
                    }
                >
                    <InputPanelFileLabels
                        extensionLabel={extensionLabel}
                        displayName={displayName}
                        variant={variant}
                    />
                    {variant === 'message' && (
                        <>
                            <span className="absolute left-3 top-3 text-sm font-medium text-[#666]">
                                {extensionLabel}
                            </span>
                            <span className="absolute bottom-3 left-3 right-3 truncate text-sm text-[#333]">
                                {displayName}
                            </span>
                        </>
                    )}
                    {/* Audio has no poster at all, so the duration always sits
                        here — opposite the extension label, clear of the name. */}
                    {durationLabel && (
                        <span className="absolute right-3 top-3 z-[1] text-sm text-[#666]">
                            {durationLabel}
                        </span>
                    )}
                </UploadAttachmentThumbnailShell>
                {playbackDialog}
            </>
        );
    }

    return null;
}

export function isMediaChipFile(file: unknown): file is MediaAttachmentFile {
    return !!file && typeof file === 'object' && isMediaAttachmentFile(file as MediaAttachmentFile);
}
