import { Folder } from 'lucide-react';
import React from 'react';
import { DocxIcon, PptxIcon, XlsxIcon, TxtIcon } from '~/components/icons';
import { FileStatus } from '~/api/knowledge';

const FileIconRenderer = ({ file, isFolder }: { file: any; isFolder: boolean }) => {
    const iconMap = {
        'doc': <DocxIcon className="size-16" />,
        'docx': <DocxIcon className="size-16" />,
        'ppt': <PptxIcon className="size-16" />,
        'pptx': <PptxIcon className="size-16" />,
        'xls': <XlsxIcon className="size-16" />,
        'xlsx': <XlsxIcon className="size-16" />,
        'txt': <TxtIcon className="size-16" />,
    };

    const extension = file.name?.split('.').pop()?.toLowerCase();

    if (isFolder) {
        return <Folder className="size-16 fill-[#4080ff] text-[#4080ff]" />;
    }

    // Only show thumbnail when file is successfully parsed
    if (file.thumbnail && file.status === FileStatus.SUCCESS) {
        return <img src={file.thumbnail} alt={file.name} className="w-full h-full object-contain" />;
    }

    return iconMap[extension] || <TxtIcon className="size-16 text-[#c9cdd4]" strokeWidth={1.5} />;
};

export default FileIconRenderer;