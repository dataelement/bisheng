import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { useLocalize } from "~/hooks";

interface MarkdownViewerProps {
    fileUrl: string;
    zoomLevel: number;
}

export function MarkdownViewer({ fileUrl, zoomLevel }: MarkdownViewerProps) {
    const localize = useLocalize();
  const [content, setContent] = useState("");
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const fetchMarkdown = async () => {
            try {
                setLoading(true);
                const response = await fetch(fileUrl);
                if (!response.ok) throw new Error(localize("com_knowledge.failure_status", { 0: response.status }));
                const text = await response.text();
                setContent(text);
                setError(null);
            } catch (err: any) {
                setError(err.message || localize("com_knowledge.load_file_failed"));
            } finally {
                setLoading(false);
            }
        };
        fetchMarkdown();
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
                    <div className="text-4xl">📝</div>
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
                    className="bg-white shadow-md max-w-[800px] w-full rounded-sm"
                    style={{
                        transform: `scale(${scale})`,
                        transformOrigin: "top center",
                    }}
                >
                    <div className="prose prose-sm max-w-none p-10 text-[#1d2129]">
                        <ReactMarkdown
                            remarkPlugins={[remarkGfm]}
                            rehypePlugins={[[rehypeHighlight, { detect: true, ignoreMissing: true }]]}
                        >
                            {content}
                        </ReactMarkdown>
                    </div>
                </div>
            </div>
        </div>
    );
}
