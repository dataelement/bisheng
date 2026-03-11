import * as mammoth from "mammoth";
import { useEffect, useRef, useState } from "react";

interface DocxViewerProps {
    fileUrl: string;
    zoomLevel: number;
}

export function DocxViewer({ fileUrl, zoomLevel }: DocxViewerProps) {
    const [htmlContent, setHtmlContent] = useState("");
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const containerRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const fetchAndConvert = async () => {
            try {
                setLoading(true);
                const response = await fetch(fileUrl);
                if (!response.ok) throw new Error(`加载失败: ${response.status}`);
                const arrayBuffer = await response.arrayBuffer();
                const result = await mammoth.convertToHtml({ arrayBuffer });
                setHtmlContent(result.value);
                setError(null);
            } catch (err: any) {
                setError(err.message || "无法加载文档");
            } finally {
                setLoading(false);
            }
        };
        fetchAndConvert();
    }, [fileUrl]);

    if (loading) {
        return (
            <div className="flex-1 flex items-center justify-center text-[#86909c]">
                文档加载中...
            </div>
        );
    }

    if (error) {
        return (
            <div className="flex-1 flex items-center justify-center">
                <div className="flex flex-col items-center gap-3 text-[#86909c]">
                    <div className="text-4xl">📄</div>
                    <p>{error}</p>
                </div>
            </div>
        );
    }

    const scale = zoomLevel / 100;

    return (
        <div className="flex-1 overflow-auto bg-[#fbfbfb]">
            <div className="flex justify-center py-6 px-4">
                <div
                    ref={containerRef}
                    className="bg-white shadow-md max-w-[800px] w-full rounded-sm"
                    style={{
                        transform: `scale(${scale})`,
                        transformOrigin: "top center",
                    }}
                >
                    <style>{`
                        .docx-content {
                            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                            line-height: 1.8;
                            padding: 40px 60px;
                            font-size: 14px;
                            color: #1d2129;
                        }
                        .docx-content p { margin: 0 0 1em 0; }
                        .docx-content table { border-collapse: collapse; width: 100%; margin: 1em 0; }
                        .docx-content table td, .docx-content table th { border: 1px solid #ddd; padding: 8px 12px; }
                        .docx-content table th { background: #f7f8fa; font-weight: 600; }
                        .docx-content img { max-width: 100%; height: auto; }
                        .docx-content h1, .docx-content h2, .docx-content h3 { color: #1d2129; margin: 1.5em 0 0.5em; }
                    `}</style>
                    <div
                        className="docx-content"
                        dangerouslySetInnerHTML={{ __html: htmlContent }}
                    />
                </div>
            </div>
        </div>
    );
}
