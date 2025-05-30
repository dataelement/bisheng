import React, { forwardRef } from "react";
import CsvIcon from "./csv.svg?react";
import DocIcon from "./doc.svg?react";
import DocxIcon from "./docx.svg?react";
import ImageIcon from "./image.svg?react";
import PdfIcon from "./pdf.svg?react";
import PptIcon from "./ppt.svg?react";
import PptxIcon from "./pptx.svg?react";
import TxtIcon from "./txt.svg?react";
import XlsIcon from "./xls.svg?react";
import XlsxIcon from "./xlsx.svg?react";

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

// 文件扩展名到图标组件的映射
const iconComponents: Record<FileType, React.ComponentType<any>> = {
    pdf: PdfIcon,
    txt: TxtIcon,
    doc: DocIcon,
    docx: DocxIcon,
    ppt: PptIcon,
    pptx: PptxIcon,
    md: TxtIcon,
    html: TxtIcon,
    jpg: ImageIcon,
    jpeg: ImageIcon,
    png: ImageIcon,
    bmp: ImageIcon,
    csv: CsvIcon,
    xls: XlsIcon,
    xlsx: XlsxIcon
};

interface FileIconProps extends React.PropsWithChildren<{
    className?: string;
    type: FileType;
}> { }

export const FileIcon = forwardRef<
    SVGSVGElement & { className: any },
    FileIconProps
>((props, ref) => {

    const IconComponent = iconComponents[props.type || 'txt'];

    if (!IconComponent) {
        console.warn(`No icon found for type: ${props.type}`);
        return null;
    }

    return <IconComponent ref={ref} className={props.className} {...props} />;
});