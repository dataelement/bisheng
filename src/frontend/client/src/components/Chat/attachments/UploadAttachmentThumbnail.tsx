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

interface UploadAttachmentThumbnailShellProps {
    fileName: string;
    variant?: UploadThumbnailVariant;
    canClick?: boolean;
    isUploading?: boolean;
    onClick?: () => void;
    onRemove?: () => void;
    allowRemoveWhileUploading?: boolean;
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
    overlay,
    className,
    children,
}: UploadAttachmentThumbnailShellProps) {
    const showRemove = onRemove && (!isUploading || allowRemoveWhileUploading);

    return (
        <Tooltip>
            <TooltipTrigger asChild>
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
                        <div className="absolute inset-0 flex items-center justify-center bg-black/25">
                            <Loader2 className="size-6 animate-spin text-white" />
                        </div>
                    )}

                    {overlay}

                    {showRemove && (
                        <button
                            type="button"
                            onClick={(e) => {
                                e.stopPropagation();
                                onRemove();
                            }}
                            className="absolute right-1.5 top-1.5 hidden size-5 items-center justify-center rounded-full bg-black/50 text-white transition-colors hover:bg-black/70 group-hover:flex coarse-pointer:flex"
                            aria-label="Remove"
                        >
                            <Outlined.Close size={12} />
                        </button>
                    )}
                </div>
            </TooltipTrigger>
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
        >
            {previewUrl ? (
                <img src={previewUrl} alt="" className="size-full object-cover" />
            ) : (
                <>
                    <span className="absolute left-3 top-3 text-sm font-medium text-[#666]">
                        {extensionLabel}
                    </span>
                    <span className="absolute bottom-3 left-3 right-3 truncate text-sm text-[#333]">
                        {displayName}
                    </span>
                </>
            )}
        </UploadAttachmentThumbnailShell>
    );
}
