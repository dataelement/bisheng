import ExcelPreview from "./ExcelPreview";

interface XlsxViewerProps {
    fileUrl: string;
    fileExt?: string;
}

export function XlsxViewer({ fileUrl, fileExt }: XlsxViewerProps) {
    return (
        <div className="flex-1 overflow-auto bg-[#fbfbfb] p-4">
            <ExcelPreview filePath={fileUrl} fileExt={fileExt} />
        </div>
    );
}
