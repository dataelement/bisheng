import React from 'react';
import { DocxIcon, PptxIcon, XlsxIcon, TxtIcon } from '~/components/icons';
import { FileStatus } from '~/api/knowledge';

const iconSlotClass = 'h-[35px] w-[40px] shrink-0 object-contain';

const FileIconRenderer = ({ file, isFolder }: { file: any; isFolder: boolean }) => {
    const iconMap = {
        'doc': <DocxIcon className={iconSlotClass} />,
        'docx': <DocxIcon className={iconSlotClass} />,
        'ppt': <PptxIcon className={iconSlotClass} />,
        'pptx': <PptxIcon className={iconSlotClass} />,
        'xls': <XlsxIcon className={iconSlotClass} />,
        'xlsx': <XlsxIcon className={iconSlotClass} />,
        'txt': <TxtIcon className={iconSlotClass} />,
    };

    const extension = file.name?.split('.').pop()?.toLowerCase();

    if (isFolder) {
        return (
            <img
                src={`${__APP_ENV__.BASE_URL}/assets/channel/Subtract.svg`}
                alt=""
                className={iconSlotClass}
            />
        );
    }

    // Only show thumbnail when file is successfully parsed
    if (file.thumbnail && file.status === FileStatus.SUCCESS) {
        return <img src={file.thumbnail} alt={file.name} className="w-full h-full object-contain" />;
    }

    return iconMap[extension] || <TxtIcon className={`${iconSlotClass} text-[#c9cdd4]`} strokeWidth={1.5} />;
};

export default FileIconRenderer;