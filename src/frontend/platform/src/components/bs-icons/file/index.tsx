import React, { forwardRef } from "react";
import BmpIcon from "./bmp.svg?react";
import ExcelIcon from "./excel.svg?react";
import HtmlIcon from "./html.svg?react";
import JpgIcon from "./jpg.svg?react";
import MarkdownIcon from "./markdown.svg?react";
import PdfIcon from "./pdf.svg?react";
import PngIcon from "./png.svg?react";
import PptIcon from "./ppt.svg?react";
import TxtIcon from "./txt.svg?react";
import WordIcon from "./word.svg?react";

export type FileType =
    | 'pdf'
    | 'txt'
    | 'doc' | 'docx'
    | 'ppt' | 'pptx'
    | 'md'
    | 'html'
    | 'jpg' | 'jpeg'
    | 'png'
    | 'bmp'
    | 'csv'
    | 'xls' | 'xlsx';

// 文件扩展名到图标组件的映射
const iconComponents: Record<FileType, React.ComponentType<any>> = {
    pdf: PdfIcon,
    txt: TxtIcon,
    doc: WordIcon,
    docx: WordIcon,
    ppt: PptIcon,
    pptx: PptIcon,
    md: MarkdownIcon,
    html: HtmlIcon,
    jpg: JpgIcon,
    jpeg: JpgIcon,
    png: PngIcon,
    bmp: BmpIcon,
    csv: ExcelIcon,
    xls: ExcelIcon,
    xlsx: ExcelIcon
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