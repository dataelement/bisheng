import { useEffect, useState } from "react";

interface TextViewerProps {
    fileUrl: string;
    zoomLevel: number;
}

export function TextViewer({ fileUrl, zoomLevel }: TextViewerProps) {
    const [content, setContent] = useState("");
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const fetchText = async () => {
            try {
                setLoading(true);
                const response = await fetch(fileUrl);
                if (!response.ok) throw new Error(`加载失败: ${response.status}`);
                const text = await response.text();
                setContent(text);
                setError(null);
            } catch (err: any) {
                setError(err.message || "无法加载文件");
            } finally {
                setLoading(false);
            }
        };
        fetchText();
    }, [fileUrl]);

    if (loading) {
        return (
            <div className="flex-1 flex items-center justify-center text-[#86909c]">
                加载中...
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
                    className="bg-white shadow-md max-w-[800px] w-full rounded-sm"
                    style={{
                        transform: `scale(${scale})`,
                        transformOrigin: "top center",
                    }}
                >
                    <pre className="p-10 text-sm leading-relaxed text-[#1d2129] font-mono whitespace-pre-wrap break-words">
                        {content}
                    </pre>
                </div>
            </div>
        </div>
    );
}
