import type { ReactNode } from 'react';
import { Outlined } from 'bisheng-icons';
import { ContextResourceCard } from '../Input/ContextResourceCard';
import { getFileTypeIcon } from '~/components/ui/icon/File/FileIcon';
import useLocalize from '~/hooks/useLocalize';
import { formatBytes } from '~/utils/files';

interface FileAttachmentResourceCardProps {
    name: string;
    size?: number | string;
    thumbnail?: ReactNode;
    onClick?: () => void;
    onRemove?: () => void;
}

export function FileAttachmentResourceCard({ name, size, thumbnail, onClick, onRemove }: FileAttachmentResourceCardProps) {
    const TypeIcon = getFileTypeIcon(name);
    const bytes = Number(size);
    const description = [
        name.split('.').pop()?.toUpperCase(),
        Number.isFinite(bytes) && bytes >= 0 ? formatBytes(bytes, 1, true) : '',
    ].filter(Boolean).join(' · ');
    return <ContextResourceCard
        label={name}
        description={description}
        thumbnail={!!thumbnail}
        icon={thumbnail || <TypeIcon size={28} />}
        onClick={onClick}
        onRemove={onRemove}
    />;
}

interface FolderAttachmentResourceCardProps {
    name: string;
    fileCount: number;
    expanded?: boolean;
    onClick?: () => void;
    onRemove?: () => void;
}

export function FolderAttachmentResourceCard({ name, fileCount, expanded, onClick, onRemove }: FolderAttachmentResourceCardProps) {
    const localize = useLocalize();
    const label = `${name} (${localize('com_folder_upload_file_count', { 0: fileCount })})`;
    return <ContextResourceCard
        label={label}
        icon={<Outlined.FolderClose size={16} />}
        expanded={expanded}
        onClick={onClick}
        onRemove={onRemove}
    />;
}
