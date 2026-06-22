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
    | 'wps'
    | 'ppt'
    | 'pptx'
    | 'dps'
    | 'md' | 'html' | 'txt' | 'json'
    | 'jpg'
    | 'jpeg'
    | 'png'
    | 'bmp'
    | 'mp3'
    | 'wav'
    | 'm4a'
    | 'aac'
    | 'flac'
    | 'ogg'
    | 'mp4'
    | 'mov'
    | 'avi'
    | 'mkv'
    | 'webm'
    | 'csv'
    | 'et'
    | 'xls'
    | 'xlsx';

// 文件扩展名到图标组件的映射
const iconComponents: Record<FileType, React.ComponentType<any>> = {
    pdf: PdfIcon,
    txt: TxtIcon,
    json: TxtIcon,
    doc: DocIcon,
    docx: DocxIcon,
    wps: DocxIcon,
    ppt: PptIcon,
    pptx: PptxIcon,
    dps: PptxIcon,
    md: TxtIcon,
    html: TxtIcon,
    jpg: ImageIcon,
    jpeg: ImageIcon,
    png: ImageIcon,
    bmp: ImageIcon,
    mp3: TxtIcon,
    wav: TxtIcon,
    m4a: TxtIcon,
    aac: TxtIcon,
    flac: TxtIcon,
    ogg: TxtIcon,
    mp4: TxtIcon,
    mov: TxtIcon,
    avi: TxtIcon,
    mkv: TxtIcon,
    webm: TxtIcon,
    csv: CsvIcon,
    et: XlsxIcon,
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
        return <TxtIcon ref={ref} className={props.className} {...props} />;
    }

    return <IconComponent ref={ref} className={props.className} {...props} />;
});
