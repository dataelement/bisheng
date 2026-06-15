import * as mammoth from "mammoth";
import { useEffect, useRef, useState } from "react";
import { useLocalize } from "~/hooks";

interface DocxViewerProps {
    fileUrl: string;
    zoomLevel: number;
}

export function DocxViewer({ fileUrl, zoomLevel }: DocxViewerProps) {
    const localize = useLocalize();
  const [htmlContent, setHtmlContent] = useState("");
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const containerRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const fetchAndConvert = async () => {
            try {
                setLoading(true);
                const response = await fetch(fileUrl);
                if (!response.ok) throw new Error(localize("com_knowledge.failure_status", { 0: response.status }));
                const arrayBuffer = await response.arrayBuffer();
                const result = await mammoth.convertToHtml({ arrayBuffer });
                setHtmlContent(result.value);
                setError(null);
            } catch (err: any) {
                setError(err.message || localize("com_knowledge.load_doc_failed"));
            } finally {
                setLoading(false);
            }
        };
        fetchAndConvert();
    }, [fileUrl]);

    if (loading) {
        return (
            <div className="flex-1 flex items-center justify-center text-[#86909c]">
                {localize("com_knowledge.doc_loading")}</div>
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
        <div className="scrollbar-os min-w-0 flex-1 overflow-auto bg-[#fbfbfb]">
            <div className="box-border flex w-full justify-center py-6 px-3 sm:px-4">
                <div
                    ref={containerRef}
                    className="w-full max-w-[800px] rounded-sm bg-white shadow-md"
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
                            /* Break long unbreakable tokens (URLs, ASCII art, no-space CJK runs)
                               so they wrap inside the page width instead of overflowing right. */
                            overflow-wrap: anywhere;
                            word-break: break-word;
                        }
                        /* Mobile: shrink the side padding so narrow screens
                           don't waste 120px on margins. Matches the 767px
                           breakpoint used by usePrefersMobileLayout. */
                        @media (max-width: 767px) {
                            .docx-content {
                                padding: 24px 16px;
                            }
                        }
                        .docx-content p { margin: 0 0 1em 0; }
                        /* table-layout: fixed prevents wide columns from blowing
                           out the frame; column widths from mammoth are honored
                           via <col> if present, otherwise they share width equally. */
                        .docx-content table { border-collapse: collapse; width: 100%; max-width: 100%; margin: 1em 0; table-layout: fixed; }
                        .docx-content table td, .docx-content table th { border: 1px solid #ddd; padding: 8px 12px; overflow-wrap: break-word; word-break: break-word; }
                        .docx-content table th { background: #f7f8fa; font-weight: 600; }
                        .docx-content img { max-width: 100%; height: auto; }
                        .docx-content pre, .docx-content code { white-space: pre-wrap; overflow-wrap: break-word; word-break: break-word; }
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
