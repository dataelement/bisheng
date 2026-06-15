import ExcelPreview from "./ExcelPreview";

interface XlsxViewerProps {
    fileUrl: string;
    fileExt?: string;
    zoomLevel?: number;
}

export function XlsxViewer({ fileUrl, fileExt, zoomLevel = 100 }: XlsxViewerProps) {
    const scale = zoomLevel / 100;
    return (
        <div className="min-w-0 flex-1 overflow-hidden flex flex-col bg-[#fbfbfb]">
            {/* pb-24 keeps the Excel horizontal scrollbar above the bottom AI dock
                (KnowledgeAiBottomDock, absolute bottom-0) so it stays reachable. */}
            <div className="box-border flex flex-1 min-h-0 w-full justify-center pt-4 pb-24 px-3 sm:px-4">
                <div
                    className="w-full max-w-[1600px] h-full"
                    style={{
                        transform: `scale(${scale})`,
                        transformOrigin: "top center",
                    }}
                >
                    <ExcelPreview filePath={fileUrl} fileExt={fileExt} />
                </div>
            </div>
        </div>
    );
}
