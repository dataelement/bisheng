import { useLocalize } from "~/hooks";
import KnowledgePreviewWatermark from "../KnowledgePreviewWatermark";

interface ImageViewerProps {
    fileUrl: string;
    zoomLevel: number;
}

export function ImageViewer({ fileUrl, zoomLevel }: ImageViewerProps) {
    const localize = useLocalize();
  const scale = zoomLevel / 100;

    return (
        <div className="flex-1 overflow-auto bg-[#fbfbfb]">
            <div className="flex items-center justify-center min-h-full p-8">
                <div
                    data-preview-watermark-surface
                    className="relative inline-block max-w-full overflow-hidden rounded-sm shadow-md"
                    style={{
                        transform: `scale(${scale})`,
                        transformOrigin: "center center",
                    }}
                >
                    <img
                        src={fileUrl}
                        alt={localize("com_knowledge.image_preview")}
                        className="block max-w-full"
                    />
                    <KnowledgePreviewWatermark />
                </div>
            </div>
        </div>
    );
}
