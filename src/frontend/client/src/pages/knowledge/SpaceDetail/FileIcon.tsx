import { Folder } from 'lucide-react';
import React from 'react';
import { DocxIcon, PptxIcon, XlsxIcon, TxtIcon } from '~/components/icons';

const FileIconRenderer = ({ file, isFolder }) => {
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

    if (file.thumbnail) {
        return <img src={file.thumbnail} alt={file.name} className="w-full h-full object-contain" />;
    }

    return iconMap[extension] || <TxtIcon className="size-16 text-[#c9cdd4]" strokeWidth={1.5} />;
};

export default FileIconRenderer;