import KnowledgePreviewWatermark from "../KnowledgePreviewWatermark";
import ExcelPreview from "./ExcelPreview";

interface XlsxViewerProps {
    fileUrl: string;
    fileExt?: string;
    zoomLevel?: number;
}

export function XlsxViewer({ fileUrl, fileExt, zoomLevel = 100 }: XlsxViewerProps) {
    const scale = zoomLevel / 100;
    return (
        <div className="min-h-0 min-w-0 flex-1 overflow-hidden flex flex-col bg-[#fbfbfb]">
            <div className="box-border flex min-h-0 flex-1 w-full justify-center py-4 px-3 sm:px-4">
                <div
                    data-preview-watermark-surface
                    className="relative flex h-full min-h-0 w-full max-w-[1600px] flex-col overflow-hidden"
                    style={{
                        transform: `scale(${scale})`,
                        transformOrigin: "top center",
                    }}
                >
                    <ExcelPreview filePath={fileUrl} fileExt={fileExt} />
                    <KnowledgePreviewWatermark />
                </div>
            </div>
        </div>
    );
}
