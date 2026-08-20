import React from 'react';
import { Colored } from 'bisheng-icons';
import { FileStatus, FileType } from '~/api/knowledge';
import { TxtIcon, FolderIcon } from '~/components/icons';
import { cn } from '~/utils';

const iconSlotClass = 'size-16 shrink-0';
const wrapperClass = 'flex size-full items-center justify-center';

// Per-type vertical gradient backdrops (Figma 11671:34378). Two stops on white.
// md / html share the txt slate-grey palette (FileMd / FileHtml main fill is #344054 = rgba(52,64,84)).
// csv shares the xls parrot-green palette (FileCsv mixes #0072FF + #00C650).
// audio follows FileAudio orange #FF9908; video follows FileVideo purple #A140FF.
const FILE_TYPE_BG = {
    folder: 'bg-[linear-gradient(180deg,rgba(240,246,253,0.05)_0%,rgb(var(--brand-500)/0.05)_100%)]',
    doc: 'bg-[linear-gradient(180deg,rgba(223,238,255,0.05)_0%,rgba(0,114,255,0.05)_100%)]',
    ppt: 'bg-[linear-gradient(180deg,rgba(255,231,233,0.05)_0%,rgba(255,62,76,0.05)_100%)]',
    xls: 'bg-[linear-gradient(180deg,rgba(226,245,234,0.05)_0%,rgba(0,198,80,0.05)_100%)]',
    csv: 'bg-[linear-gradient(180deg,rgba(226,245,234,0.05)_0%,rgba(0,198,80,0.05)_100%)]',
    txt: 'bg-[linear-gradient(180deg,rgba(225,227,230,0.05)_0%,rgba(52,64,84,0.05)_100%)]',
    md: 'bg-[linear-gradient(180deg,rgba(225,227,230,0.05)_0%,rgba(52,64,84,0.05)_100%)]',
    html: 'bg-[linear-gradient(180deg,rgba(225,227,230,0.05)_0%,rgba(52,64,84,0.05)_100%)]',
    audio: 'bg-[linear-gradient(180deg,rgba(255,243,223,0.05)_0%,rgba(255,153,8,0.05)_100%)]',
    video: 'bg-[linear-gradient(180deg,rgba(243,231,255,0.05)_0%,rgba(161,64,255,0.05)_100%)]',
} as const;

type FileTypeKey = keyof typeof FILE_TYPE_BG;

const EXTENSION_TO_TYPE: Record<string, FileTypeKey> = {
    doc: 'doc',
    docx: 'doc',
    ppt: 'ppt',
    pptx: 'ppt',
    xls: 'xls',
    xlsx: 'xls',
    csv: 'csv',
    txt: 'txt',
    md: 'md',
    markdown: 'md',
    html: 'html',
    htm: 'html',
    mp3: 'audio',
    wav: 'audio',
    m4a: 'audio',
    aac: 'audio',
    flac: 'audio',
    ogg: 'audio',
    mp4: 'video',
    mov: 'video',
    avi: 'video',
    mkv: 'video',
    webm: 'video',
};

/** Icon components, not elements: the slot size is a render-time decision
 *  (`iconClassName`), so baking `iconSlotClass` into a fixed element would make
 *  every caller render at 64px and get center-cropped by a smaller slot. */
type IconComponent = React.ComponentType<{ className?: string }>;

const TYPE_TO_ICON: Record<FileTypeKey, IconComponent> = {
    folder: FolderIcon,
    doc: Colored.FileDoc,
    ppt: Colored.FilePptx,
    xls: Colored.FileXls,
    csv: Colored.FileCsv,
    txt: Colored.FileTxt,
    md: Colored.FileMd,
    html: Colored.FileHtml,
    audio: Colored.FileAudio,
    video: Colored.FileVideo,
};

const FileIconRenderer = ({ file, isFolder, iconClassName, thumbBordered, transparentBg }: { file: any; isFolder: boolean; iconClassName?: string; thumbBordered?: boolean; transparentBg?: boolean }) => {
    // H5 mobile list: suppress the per-type gradient backdrop so colored icons
    // sit on a transparent slot (desktop card path stays untouched).
    const bgFor = (key: FileTypeKey) => (transparentBg ? '' : FILE_TYPE_BG[key]);
    // Every branch renders at this size — a slot smaller than the icon would
    // otherwise crop the glyph instead of scaling it.
    const slotClass = iconClassName ?? iconSlotClass;
    const renderTypeIcon = (key: FileTypeKey) => {
        const Icon = TYPE_TO_ICON[key];
        return <Icon className={slotClass} />;
    };

    if (isFolder) {
        return (
            <div className={cn(wrapperClass, bgFor('folder'))}>
                {renderTypeIcon('folder')}
            </div>
        );
    }

    const extension: string = file.name?.split('.').pop()?.toLowerCase() ?? '';
    const typeKey: FileTypeKey | undefined =
        file.type === FileType.WEB ? 'html'
            : file.type === FileType.AUDIO ? 'audio'
                : file.type === FileType.VIDEO ? 'video'
                    : EXTENSION_TO_TYPE[extension];

    // Plain-text / structured-text formats (txt / md / csv) never render a
    // thumbnail. Once parsed they show their colored placeholder icon; before
    // parsing they fall through to the neutral line-art placeholder below.
    if ((typeKey === 'md' || typeKey === 'txt' || typeKey === 'csv' || typeKey === 'html') && file.status === FileStatus.SUCCESS) {
        return (
            <div className={cn(wrapperClass, bgFor(typeKey))}>
                {renderTypeIcon(typeKey)}
            </div>
        );
    }

    // Only show thumbnail when file is successfully parsed.
    // object-top so the preview keeps the page header (title area) visible instead
    // of clipping it equally top & bottom.
    if (file.thumbnail && file.status === FileStatus.SUCCESS) {
        return <img src={file.thumbnail} alt={file.name} className={cn("size-full object-cover object-top", thumbBordered && "rounded-md border border-[#EBECF0]")} />;
    }

    // For non-success states (uploading/processing/failed/etc.), use the neutral
    // line-art placeholder (matches Figma 11671:34497). Bg handled by the wrapper.
    const isParsed = file.status === FileStatus.SUCCESS;
    if (!isParsed) {
        return (
            <div className={wrapperClass}>
                <TxtIcon className={slotClass} />
            </div>
        );
    }

    const resolvedKey: FileTypeKey = typeKey ?? 'txt';

    return (
        <div className={cn(wrapperClass, bgFor(resolvedKey))}>
            {renderTypeIcon(resolvedKey)}
        </div>
    );
};

export default FileIconRenderer;
