import { BookType, File, FileMinus, Heading, Image, Loader2, Table2 } from "lucide-react";
import React from "react";

export type FileType =
    | 'pdf'
    | 'doc'
    | 'docx'
    | 'ppt'
    | 'pptx'
    | 'md' | 'html' | 'txt'
    | 'jpg'
    | 'jpeg'
    | 'png'
    | 'bmp'
    | 'csv'
    | 'xls'
    | 'xlsx';

const fileTypeColors: Record<FileType, string> = {
    pdf: 'bg-[#FA423E]',
    txt: 'bg-gray-500',
    doc: 'bg-[#0285FF]',
    docx: 'bg-[#0285FF]',
    ppt: 'bg-[#FF9800]',
    pptx: 'bg-[#FF9800]',
    md: 'bg-gray-400',
    html: 'bg-red-500',
    jpg: 'bg-primary',
    jpeg: 'bg-primary',
    png: 'bg-primary',
    bmp: 'bg-primary',
    csv: 'bg-[#06B84C]',
    xls: 'bg-[#06B84C]',
    xlsx: 'bg-[#06B84C]'
};

// 文件扩展名到图标组件的映射
const baseClassName = 'size-10 p-3 text-white flex items-center justify-center rounded-[10px]'
const iconComponents: Record<FileType, any> = {
    pdf: <div className={`${baseClassName} ${fileTypeColors.pdf}`}>
        <FileMinus />
    </div>,
    txt: <div className={`${baseClassName} ${fileTypeColors.txt}`}>
        <FileMinus />
    </div>,
    doc: <div className={`${baseClassName} ${fileTypeColors.doc}`}>
        <BookType />
    </div>,
    docx: <div className={`${baseClassName} ${fileTypeColors.docx}`}>
        <BookType />
    </div>,
    ppt: <div className={`${baseClassName} ${fileTypeColors.ppt}`}>
        <FileMinus />
    </div>,
    pptx: <div className={`${baseClassName} ${fileTypeColors.pptx}`}>
        <FileMinus />
    </div>,
    md: <div className={`${baseClassName} ${fileTypeColors.md}`}>
        <FileMinus />
    </div>,
    html: <div className={`${baseClassName} ${fileTypeColors.html}`}>
        <Heading />
    </div>,
    jpg: <div className={`${baseClassName} ${fileTypeColors.jpg}`}>
        <Image />
    </div>,
    jpeg: <div className={`${baseClassName} ${fileTypeColors.jpeg}`}>
        <Image />
    </div>,
    png: <div className={`${baseClassName} ${fileTypeColors.png}`}>
        <Image />
    </div>,
    bmp: <div className={`${baseClassName} ${fileTypeColors.bmp}`}>
        <Image />
    </div>,
    csv: <div className={`${baseClassName} ${fileTypeColors.csv}`}>
        <Table2 />
    </div>,
    xls: <div className={`${baseClassName} ${fileTypeColors.xls}`}>
        <Table2 />
    </div>,
    xlsx: <div className={`${baseClassName} ${fileTypeColors.xlsx}`}>
        <Table2 />
    </div>
};

interface FileIconProps extends React.PropsWithChildren<{
    className?: string;
    type: FileType;
    loading?: boolean
}> { }

export const FileIcon: React.FC<FileIconProps> = ({ loading = false, type, className }: FileIconProps) => {

    if (loading) {
        const bgColor = fileTypeColors[type] || 'bg-gray-500';

        return (
            <div className={`size-10 min-w-10 flex items-center justify-center rounded-[10px] text-white ${bgColor} ${className}`}>
                <Loader2 size={28} className="animate-spin" />
            </div>
        );
    }

    const baseIcon = iconComponents[type] || iconComponents.txt;

    return React.cloneElement(baseIcon, {
        className: `${baseIcon.props.className} ${className}`
    });
};

const getSizeClass = (size: 'sm' | 'md' | 'lg') => {
    switch (size) {
        case 'sm': return 'size-8';
        case 'lg': return 'size-12';
        default: return 'size-10';
    }
};

export const getFileTypebyFileName = (fileName: string) => {
    return fileName ? fileName.split('.').pop()?.toLocaleLowerCase() as FileType : '';
}