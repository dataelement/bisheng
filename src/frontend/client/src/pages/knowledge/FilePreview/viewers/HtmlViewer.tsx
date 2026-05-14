import { useEffect, useState } from "react";
import { useLocalize } from "~/hooks";

interface HtmlViewerProps {
    fileUrl: string;
    zoomLevel: number;
}

export function HtmlViewer({ fileUrl, zoomLevel }: HtmlViewerProps) {
    const localize = useLocalize();
  const [htmlContent, setHtmlContent] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const fetchHtml = async () => {
            try {
                setLoading(true);
                const response = await fetch(fileUrl);
                if (!response.ok) throw new Error(localize("com_knowledge.failure_status", { 0: response.status }));
                const text = await response.text();
                setHtmlContent(text);
                setError(null);
            } catch (err: any) {
                setError(err.message || localize("com_knowledge.load_html_failed"));
            } finally {
                setLoading(false);
            }
        };
        fetchHtml();
    }, [fileUrl]);

    if (loading) {
        return (
            <div className="flex-1 flex items-center justify-center text-[#86909c]">
                {localize("com_knowledge.loading")}</div>
        );
    }

    if (error) {
        return (
            <div className="flex-1 flex items-center justify-center">
                <div className="flex flex-col items-center gap-3 text-[#86909c]">
                    <div className="text-4xl">🌐</div>
                    <p>{error}</p>
                </div>
            </div>
        );
    }

    const scale = zoomLevel / 100;

    return (
        <div className="flex-1 overflow-auto bg-[#fbfbfb]">
            <div className="w-full h-full">
                <iframe
                    srcDoc={htmlContent || ""}
                    title={localize("com_knowledge.html_preview")}
                    sandbox="allow-same-origin"
                    className="w-full h-full border-none bg-white"
                    style={{
                        transform: `scale(${scale})`,
                        transformOrigin: "top left",
                        width: `${100 / scale}%`,
                        height: `${100 / scale}%`,
                    }}
                />
            </div>
        </div>
    );
}
