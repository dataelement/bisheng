import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";
import type { KnowledgeFilePreview } from "~/api/knowledge";
import { useLocalize } from "~/hooks";
import { resolveKnowledgePreviewUrl } from "./previewUrlUtils";
import { TopBar } from "./TopBar";

interface RichKnowledgePreviewProps {
    fileName: string;
    preview: KnowledgeFilePreview;
    actions?: ReactNode;
    allowDownload?: boolean;
    onDownloadFile?: () => void;
    compactMode?: boolean;
}

type MediaTab = "recognized" | "entry";

const MEDIA_SOURCES = new Set(["audio_transcript", "video_transcript"]);
const AUDIO_EXTENSIONS = new Set(["mp3", "wav", "m4a", "aac", "flac", "ogg"]);
const VIDEO_EXTENSIONS = new Set(["mp4", "mov", "avi", "mkv", "webm"]);

function getExtensionFromUrl(url?: string): string {
    if (!url) return "";
    const path = url.split("?")[0].split("#")[0];
    const filename = path.split("/").pop() || "";
    const dotIndex = filename.lastIndexOf(".");
    return dotIndex >= 0 ? filename.slice(dotIndex + 1).toLowerCase() : "";
}

function isMediaUrl(url?: string): boolean {
    const ext = getExtensionFromUrl(url);
    return AUDIO_EXTENSIONS.has(ext) || VIDEO_EXTENSIONS.has(ext);
}

function isMediaPreview(preview: KnowledgeFilePreview): boolean {
    const ext = getExtensionFromUrl(preview.original_url || preview.preview_url);
    return (
        MEDIA_SOURCES.has(preview.file_source)
        || preview.media_kind === "audio"
        || preview.media_kind === "video"
        || AUDIO_EXTENSIONS.has(ext)
        || VIDEO_EXTENSIONS.has(ext)
    );
}

function isVideoPreview(preview: KnowledgeFilePreview): boolean {
    const ext = getExtensionFromUrl(preview.original_url || preview.preview_url);
    return preview.file_source === "video_transcript" || preview.media_kind === "video" || VIDEO_EXTENSIONS.has(ext);
}

function extractMarkdownSection(markdown: string, heading: string): string {
    const pattern = new RegExp(`^##\\s+${heading}\\s*$`, "m");
    const match = markdown.match(pattern);
    if (!match || match.index === undefined) return "";
    const start = match.index + match[0].length;
    const rest = markdown.slice(start);
    const nextHeading = rest.search(/^##\s+/m);
    return (nextHeading >= 0 ? rest.slice(0, nextHeading) : rest).trim();
}

function MarkdownBlock({ content }: { content: string }) {
    return (
        <div className="flex-1 overflow-auto bg-[#fbfbfb]">
            <div className="flex justify-center px-4 py-6">
                <div className="w-full max-w-[800px] rounded-sm bg-white shadow-md">
                    <div className="prose prose-sm max-w-none p-8 text-[#1d2129]">
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

function MarkdownFromUrl({ fileUrl }: { fileUrl: string }) {
    const localize = useLocalize();
    const [content, setContent] = useState("");
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");

    useEffect(() => {
        let cancelled = false;
        if (!fileUrl) {
            setLoading(false);
            setContent("");
            setError("");
            return () => {
                cancelled = true;
            };
        }
        setLoading(true);
        setError("");
        fetch(resolveKnowledgePreviewUrl(fileUrl))
            .then((response) => {
                if (!response.ok) throw new Error(localize("com_knowledge.failure_status", { 0: response.status }));
                return response.text();
            })
            .then((text) => {
                if (!cancelled) setContent(text);
            })
            .catch((err: Error) => {
                if (!cancelled) setError(err.message || localize("com_knowledge.load_file_failed"));
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, [fileUrl, localize]);

    if (loading) {
        return (
            <div className="flex flex-1 items-center justify-center bg-[#fbfbfb] text-sm text-[#86909c]">
                {localize("com_knowledge.loading")}
            </div>
        );
    }
    if (error) {
        return (
            <div className="flex flex-1 items-center justify-center bg-[#fbfbfb] text-sm text-[#86909c]">
                {error}
            </div>
        );
    }
    return <MarkdownBlock content={content} />;
}

function MediaTranscriptTabs({ fileUrl }: { fileUrl: string }) {
    const localize = useLocalize();
    const [activeTab, setActiveTab] = useState<MediaTab>("recognized");
    const [content, setContent] = useState("");
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");

    useEffect(() => {
        let cancelled = false;
        if (!fileUrl) {
            setLoading(false);
            setContent("");
            return () => {
                cancelled = true;
            };
        }
        setLoading(true);
        setError("");
        fetch(resolveKnowledgePreviewUrl(fileUrl))
            .then((response) => {
                if (!response.ok) throw new Error(localize("com_knowledge.failure_status", { 0: response.status }));
                return response.text();
            })
            .then((text) => {
                if (!cancelled) setContent(text);
            })
            .catch((err: Error) => {
                if (!cancelled) setError(err.message || localize("com_knowledge.load_file_failed"));
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, [fileUrl]);

    const entryText = extractMarkdownSection(content, "入库文本") || content;
    const recognizedText = extractMarkdownSection(content, "识别文本") || content;
    const activeContent = activeTab === "recognized" ? recognizedText : entryText;

    return (
        <section className="flex min-h-[420px] flex-col overflow-hidden rounded-[8px] border border-[#e5e6eb] bg-white shadow-sm">
            <div className="flex shrink-0 items-center gap-2 border-b border-[#e5e6eb] bg-white px-4 py-3">
                <button
                    type="button"
                    onClick={() => setActiveTab("recognized")}
                    className={`h-8 rounded-[6px] px-3 text-sm ${activeTab === "recognized" ? "bg-primary text-white" : "bg-[#f2f3f5] text-[#4e5969]"}`}
                >
                    {localize("com_knowledge.recognized_text")}
                </button>
                <button
                    type="button"
                    onClick={() => setActiveTab("entry")}
                    className={`h-8 rounded-[6px] px-3 text-sm ${activeTab === "entry" ? "bg-primary text-white" : "bg-[#f2f3f5] text-[#4e5969]"}`}
                >
                    {localize("com_knowledge.knowledge_entry_text")}
                </button>
            </div>
            {loading ? (
                <div className="flex flex-1 items-center justify-center text-sm text-[#86909c]">
                    {localize("com_knowledge.loading")}
                </div>
            ) : error ? (
                <div className="flex flex-1 items-center justify-center text-sm text-[#86909c]">{error}</div>
            ) : (
                <MarkdownBlock content={activeContent} />
            )}
        </section>
    );
}

export function RichKnowledgePreview({
    fileName,
    preview,
    actions,
    allowDownload = true,
    onDownloadFile,
    compactMode = false,
}: RichKnowledgePreviewProps) {
    const localize = useLocalize();
    const isMedia = isMediaPreview(preview);
    const isVideo = isVideoPreview(preview);
    const mediaTextUrl = preview.preview_url && !isMediaUrl(preview.preview_url)
        ? resolveKnowledgePreviewUrl(preview.preview_url)
        : "";
    const webLinkMarkdownUrl = resolveKnowledgePreviewUrl(preview.preview_url || preview.original_url || "");
    const mediaPlaybackUrl = resolveKnowledgePreviewUrl(preview.original_url || "");

    const title = useMemo(() => {
        if (preview.file_source === "web_link") {
            return preview.web_title || fileName;
        }
        return fileName;
    }, [fileName, preview.file_source, preview.web_title]);

    if (isMedia) {
        return (
            <div className="flex h-full w-full flex-col overflow-hidden bg-[#f5f7fb]">
                {!compactMode && (
                    <TopBar
                        fileName={fileName}
                        showZoom={false}
                        onDownload={allowDownload ? onDownloadFile : undefined}
                        actions={actions}
                    />
                )}
                <div className="flex-1 overflow-auto p-5">
                    <div className="mx-auto flex w-full max-w-[980px] flex-col gap-4">
                        <section className="rounded-[8px] border border-[#e5e6eb] bg-white p-4 shadow-sm">
                            <div className="mb-3 text-base font-semibold text-[#1d2129]">{title}</div>
                            {isVideo ? (
                                <video
                                    className="max-h-[420px] w-full rounded-[6px] bg-black"
                                    src={mediaPlaybackUrl}
                                    controls
                                />
                            ) : (
                                <audio className="w-full" src={mediaPlaybackUrl} controls />
                            )}
                        </section>
                        {mediaTextUrl ? <MediaTranscriptTabs fileUrl={mediaTextUrl} /> : null}
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="flex h-full w-full flex-col overflow-hidden bg-[#f5f7fb]">
            {!compactMode && (
                <TopBar
                    fileName={fileName}
                    showZoom={false}
                    onDownload={allowDownload ? onDownloadFile : undefined}
                    actions={actions}
                />
            )}
            <div className="flex min-h-0 flex-1 overflow-hidden">
                {webLinkMarkdownUrl ? (
                    <MarkdownFromUrl fileUrl={webLinkMarkdownUrl} />
                ) : (
                    <div className="flex h-full items-center justify-center text-sm text-[#86909c]">
                        {localize("com_knowledge.fetch_preview_link_failed")}
                    </div>
                )}
            </div>
        </div>
    );
}
