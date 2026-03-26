import { useLocalize } from "~/hooks";
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
                <img
                    src={fileUrl}
                    alt={localize("com_knowledge.image_preview")}
                    className="max-w-full shadow-md rounded-sm"
                    style={{
                        transform: `scale(${scale})`,
                        transformOrigin: "center center",
                    }}
                />
            </div>
        </div>
    );
}
