import React from 'react';
import { TxtIcon } from '~/components/icons';
import { FileStatus } from '~/api/knowledge';

const renderSvgIcon = (icon: React.ReactNode, className: string) => (
    <span className={`${className} inline-flex shrink-0 items-center justify-center overflow-hidden [&>svg]:size-full`}>
        {icon}
    </span>
);

const fileIconExtensions = new Set([
    'txt',
    'doc',
    'docx',
    'ppt',
    'pptx',
    'md',
    'html',
    'xls',
    'xlsx',
    'csv',
    'pdf',
    'png',
    'jpg',
    'jpeg',
    'bmp',
    'wps',
    'dps',
    'et',
    'mp3',
    'wav',
    'm4a',
    'aac',
    'flac',
    'ogg',
    'mp4',
    'mov',
    'avi',
    'mkv',
    'webm',
]);

const FileIconRenderer = ({
    file,
    isFolder,
    className = 'size-[64px]',
    showThumbnail = true,
}: {
    file: any;
    isFolder: boolean;
    className?: string;
    showThumbnail?: boolean;
}) => {
    const iconSlotClass = `${className} shrink-0 object-contain`;

    const extension = file.name?.split('.').pop()?.toLowerCase();

    if (isFolder) {
        return (
            <img
                src={`${__APP_ENV__.BASE_URL}/assets/knowledge-portal/folder@2x.png`}
                alt=""
                className={iconSlotClass}
            />
        );
    }

    if (extension && fileIconExtensions.has(extension)) {
        // Design icons override for the common doc types; others fall back to the
        // per-extension svg set.
        const overrideIconByExtension: Record<string, string> = {
            doc: "word@2x.png",
            docx: "word@2x.png",
            pdf: "pdf@2x.png",
            md: "md.png",
        };
        const overrideIcon = overrideIconByExtension[extension];
        return (
            <img
                src={`${__APP_ENV__.BASE_URL}/assets/knowledge-portal/${overrideIcon ?? `file-${extension}.svg`}`}
                alt=""
                className={iconSlotClass}
            />
        );
    }

    // Only show thumbnail when file is successfully parsed
    if (showThumbnail && file.thumbnail && file.status === FileStatus.SUCCESS) {
        return <img src={file.thumbnail} alt={file.name} className={iconSlotClass} />;
    }

    return renderSvgIcon(<TxtIcon />, iconSlotClass);
};

export default FileIconRenderer;
