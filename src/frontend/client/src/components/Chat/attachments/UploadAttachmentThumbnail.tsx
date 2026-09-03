import { Loader2 } from 'lucide-react';
import type { ReactNode } from 'react';
import { Outlined } from 'bisheng-icons';
import { Tooltip, TooltipContent, TooltipTrigger } from '~/components/ui/Tooltip2';
import {
    getMediaDisplayBaseName,
    getMediaFileExtensionLabel,
} from '~/utils/mediaAttachmentUtils';
import { cn } from '~/utils';

export type UploadThumbnailVariant = 'bar' | 'message';

const THUMB_SIZE: Record<UploadThumbnailVariant, string> = {
    bar: 'size-[96px] rounded-2xl',
    message: 'size-[120px] rounded-xl',
};

/** Top extension + bottom basename labels used in the input panel (bar variant). */
export function InputPanelFileLabels({
    extensionLabel,
    displayName,
    variant = 'bar',
    tone = 'muted',
}: {
    extensionLabel?: string;
    displayName: string;
    variant?: UploadThumbnailVariant;
    /** `muted` on gray/doc cards; `overlay` on top of image/video previews. */
    tone?: 'muted' | 'overlay';
}) {
    if (variant !== 'bar') return null;

    const bottomClass =
        tone === 'overlay'
            ? 'text-sm text-white [text-shadow:0_1px_3px_rgba(0,0,0,0.85)]'
            : 'text-sm text-[#333]';

    return (
        <>
            {extensionLabel && (
                <span className="absolute left-3 top-3 z-[1] text-sm font-medium text-[#666]">
                    {extensionLabel}
                </span>
            )}
            <span
                className={cn('absolute bottom-3 left-3 right-3 z-[1] truncate', bottomClass)}
            >
                {displayName}
            </span>
        </>
    );
}

interface UploadAttachmentThumbnailShellProps {
    fileName: string;
    variant?: UploadThumbnailVariant;
    canClick?: boolean;
    isUploading?: boolean;
    onClick?: () => void;
    onRemove?: () => void;
    allowRemoveWhileUploading?: boolean;
    /** When false, skip hover filename overlay (e.g. video cover uses play badge only). */
    showHoverFileName?: boolean;
    overlay?: ReactNode;
    className?: string;
    children: ReactNode;
}

export function UploadAttachmentThumbnailShell({
    fileName,
    variant = 'bar',
    canClick = false,
    isUploading = false,
    onClick,
    onRemove,
    allowRemoveWhileUploading = false,
    showHoverFileName = true,
    overlay,
    className,
    children,
}: UploadAttachmentThumbnailShellProps) {
    const isInputPanel = variant === 'bar';
    const showRemove = onRemove && (!isUploading || allowRemoveWhileUploading);

    const card = (
        <div
            className={cn(
                'group relative shrink-0 overflow-hidden bg-[#ebebeb]',
                THUMB_SIZE[variant],
                canClick && 'cursor-pointer',
                className,
            )}
            onClick={canClick ? onClick : undefined}
        >
            {children}

            {isUploading && (
                <div className="absolute inset-0 z-[2] flex items-center justify-center bg-black/25">
                    <Loader2 className="size-6 animate-spin text-white" />
                </div>
            )}

            {overlay}

            {isInputPanel && (
                <div
                    className={cn(
                        'pointer-events-none absolute inset-0 z-[3] bg-black/40 opacity-0 transition-opacity',
                        'group-hover:opacity-100 coarse-pointer:opacity-0',
                    )}
                />
            )}

            {isInputPanel && showHoverFileName && (
                <div
                    className={cn(
                        'pointer-events-none absolute inset-x-0 bottom-0 z-[4] truncate px-2 pb-2 pt-6 text-[11px] leading-tight text-white',
                        'bg-gradient-to-t from-black/75 via-black/35 to-transparent',
                        'opacity-0 transition-opacity group-hover:opacity-100 coarse-pointer:opacity-0',
                    )}
                >
                    {fileName}
                </div>
            )}

            {showRemove && (
                <button
                    type="button"
                    onClick={(e) => {
                        e.stopPropagation();
                        onRemove();
                    }}
                    className={cn(
                        'absolute right-1.5 top-1.5 z-[5] flex size-5 items-center justify-center rounded-full',
                        'bg-black/55 text-white transition-opacity hover:bg-black/75',
                        isInputPanel
                            ? 'opacity-0 group-hover:opacity-100 coarse-pointer:opacity-100'
                            : 'hidden group-hover:flex coarse-pointer:flex',
                    )}
                    aria-label="Remove"
                >
                    <Outlined.Close size={12} />
                </button>
            )}
        </div>
    );

    return (
        <Tooltip>
            <TooltipTrigger asChild>{card}</TooltipTrigger>
            <TooltipContent side="bottom" sideOffset={6} className="max-w-xs break-all">
                {fileName}
            </TooltipContent>
        </Tooltip>
    );
}

interface FileUploadThumbnailProps {
    fileName: string;
    previewUrl?: string;
    variant?: UploadThumbnailVariant;
    isUploading?: boolean;
    onRemove?: () => void;
    onClick?: () => void;
}

/** Square thumbnail for generic uploaded files (image preview or extension label). */
export function FileUploadThumbnail({
    fileName,
    previewUrl,
    variant = 'bar',
    isUploading = false,
    onRemove,
    onClick,
}: FileUploadThumbnailProps) {
    const extensionLabel = getMediaFileExtensionLabel(fileName);
    const displayName = getMediaDisplayBaseName(fileName);

    return (
        <UploadAttachmentThumbnailShell
            fileName={fileName}
            variant={variant}
            canClick={!!onClick && !isUploading}
            isUploading={isUploading}
            onClick={onClick}
            onRemove={onRemove}
            allowRemoveWhileUploading
            showHoverFileName={false}
        >
            {previewUrl ? (
                <>
                    <img src={previewUrl} alt="" className="size-full object-cover" />
                    <InputPanelFileLabels
                        displayName={displayName}
                        variant={variant}
                        tone="overlay"
                    />
                </>
            ) : (
                <>
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
        </UploadAttachmentThumbnailShell>
    );
}
