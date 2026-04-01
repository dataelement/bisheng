import ExcelPreview from "./ExcelPreview";

interface XlsxViewerProps {
    fileUrl: string;
    fileExt?: string;
    zoomLevel?: number;
}

export function XlsxViewer({ fileUrl, fileExt, zoomLevel = 100 }: XlsxViewerProps) {
    const scale = zoomLevel / 100;
    return (
        <div className="flex-1 overflow-auto bg-[#fbfbfb] p-4 flex justify-center">
            <div
                style={{
                    transform: `scale(${scale})`,
                    transformOrigin: "top center",
                }}
            >
                <ExcelPreview filePath={fileUrl} fileExt={fileExt} />
            </div>
        </div>
    );
}
