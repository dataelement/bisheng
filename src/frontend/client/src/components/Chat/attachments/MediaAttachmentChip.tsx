import { Loader2, Music2, Play, Video } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { Outlined } from 'bisheng-icons';
import useLocalize from '~/hooks/useLocalize';
import {
    formatMediaDuration,
    getMediaKind,
    isMediaAttachmentFile,
    resolveMediaPlaybackUrl,
    type MediaParsingState,
} from '~/utils/mediaAttachmentUtils';
import { cn } from '~/utils';

export interface MediaAttachmentFile {
    name?: string;
    file_name?: string;
    filename?: string;
    filepath?: string;
    file_path?: string;
    isUploading?: boolean;
    mediaPreviewUrl?: string;
    previewUrl?: string;
    mediaDurationSec?: number;
    parsingState?: MediaParsingState;
}

interface MediaAttachmentChipProps {
    file: MediaAttachmentFile;
    /** Input bar chips may remove; sent-message chips are read-only. */
    onRemove?: () => void;
    /** Compact row in message bubble vs wider input-bar card. */
    variant?: 'bar' | 'message';
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
    const canPlay = !!playbackUrl && !isUploading;

    const handlePlay = () => {
        if (!canPlay || !playbackUrl) return;
        navigate('/c/media-playback', {
            state: {
                url: playbackUrl,
                name: fileName,
                kind,
            },
        });
    };

    const Icon = kind === 'video' ? Video : Music2;
    const widthClass = variant === 'bar' ? 'w-[148px]' : 'w-full max-w-sm';

    return (
        <div
            className={cn(
                'group relative flex h-[30px] shrink-0 items-center gap-1 rounded-md bg-white px-2 text-xs text-[#212121]',
                canPlay && 'cursor-pointer',
                widthClass,
                className,
            )}
            onClick={canPlay ? handlePlay : undefined}
            title={fileName}
        >
            <span className="relative flex size-4 shrink-0 items-center justify-center text-[#999]">
                {isUploading ? (
                    <Loader2 className="size-4 animate-spin" />
                ) : kind === 'video' && playbackUrl ? (
                    <video
                        src={playbackUrl}
                        muted
                        playsInline
                        preload="metadata"
                        className="size-4 rounded-[2px] object-cover"
                    />
                ) : (
                    <Icon className="size-4" />
                )}
                {canPlay && !isUploading && (
                    <Play className="absolute size-2.5 text-white drop-shadow opacity-0 transition-opacity group-hover:opacity-100" />
                )}
            </span>

            <span className="min-w-0 flex-1 truncate text-left">{fileName}</span>

            {durationLabel && !isUploading && (
                <span className="shrink-0 text-[10px] text-[#999]">{durationLabel}</span>
            )}

            {isParsing && (
                <span className="shrink-0 text-[10px] text-primary">
                    {localize('com_chat.media_parsing')}
                </span>
            )}

            {onRemove && !isUploading && (
                <button
                    type="button"
                    onClick={(e) => {
                        e.stopPropagation();
                        onRemove();
                    }}
                    className="hidden size-4 shrink-0 items-center justify-center rounded text-slate-400 transition-colors hover:text-slate-600 group-hover:flex coarse-pointer:flex"
                    aria-label="Remove"
                >
                    <Outlined.Close size={12} />
                </button>
            )}
        </div>
    );
}

export function isMediaChipFile(file: unknown): file is MediaAttachmentFile {
    return !!file && typeof file === 'object' && isMediaAttachmentFile(file as MediaAttachmentFile);
}
