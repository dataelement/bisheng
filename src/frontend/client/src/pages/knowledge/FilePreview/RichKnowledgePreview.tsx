// @ts-strict-ignore
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import i18next from "i18next";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";
import type { KnowledgeFilePreview } from "~/api/knowledge";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";
import { MediaPlayer } from "./MediaPlayer";
import { resolveKnowledgePreviewUrl } from "./previewUrlUtils";
import { TopBar } from "./TopBar";

interface RichKnowledgePreviewProps {
    fileName: string;
    preview: KnowledgeFilePreview;
    actions?: ReactNode;
    /** Actions pinned to the far right of the TopBar, after the download button. */
    trailingActions?: ReactNode;
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

interface TranscriptCue {
    /** Raw timestamp label, e.g. "00:00:03 - 00:00:05". */
    time: string;
    text: string;
}

/** A cue line opens with its timestamp in brackets: "[00:00:03 - 00:00:05] …". */
const CUE_PATTERN = /^\[(\d{1,2}:\d{2}(?::\d{2})?(?:\s*-\s*\d{1,2}:\d{2}(?::\d{2})?)?)\]\s*/;

/**
 * Split a transcript into timestamp/text pairs so the time can be rendered as its
 * own label instead of running inline with the sentence. Lines without a leading
 * timestamp continue the cue above them; text before the first cue is returned as
 * `preamble`. No cue found → the caller falls back to plain markdown.
 */
function parseTranscriptCues(markdown: string): { preamble: string; cues: TranscriptCue[] } {
    const cues: TranscriptCue[] = [];
    const preambleLines: string[] = [];

    for (const rawLine of markdown.split("\n")) {
        const line = rawLine.trim();
        if (!line) continue;
        const match = line.match(CUE_PATTERN);
        if (match) {
            cues.push({ time: match[1].replace(/\s*-\s*/, " - "), text: line.slice(match[0].length).trim() });
        } else if (cues.length) {
            const last = cues[cues.length - 1];
            last.text = last.text ? `${last.text} ${line}` : line;
        } else {
            preambleLines.push(line);
        }
    }

    return { preamble: preambleLines.join("\n\n"), cues };
}

/* Transcript markdown matches the cue text size. `.prose` (vendored typography CSS)
   hard-sets its own font-size from --markdown-font-size — the global chat font-size
   preference — and is emitted after the utilities, so the override needs `!`. */
const TRANSCRIPT_MARKDOWN_SIZE = "!text-body";

function TranscriptCueList({ cues }: { cues: TranscriptCue[] }) {
    return (
        <ol className="space-y-4">
            {cues.map((cue, index) => (
                <li key={`${cue.time}-${index}`}>
                    <div className="text-caption tabular-nums text-text-3">{cue.time}</div>
                    <p className="mt-1 text-body text-text-1">{cue.text}</p>
                </li>
            ))}
        </ol>
    );
}

function MarkdownBody({ content, className }: { content: string; className?: string }) {
    return (
        <div className={cn("prose prose-sm max-w-none text-text-1", className)}>
            <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[[rehypeHighlight, { detect: true, ignoreMissing: true }]]}
            >
                {content}
            </ReactMarkdown>
        </div>
    );
}

function MarkdownBlock({ content }: { content: string }) {
    return (
        <div className="flex-1 overflow-auto bg-[#fbfbfb]">
            <div className="flex justify-center px-4 py-6">
                <div className="w-full max-w-[800px] rounded-sm bg-white shadow-md">
                    <div className="p-8">
                        <MarkdownBody content={content} />
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
                if (!response.ok) {
                    throw new Error(i18next.t("com_knowledge.failure_status", { 0: response.status }));
                }
                return response.text();
            })
            .then((text) => {
                if (!cancelled) setContent(text);
            })
            .catch((err: Error) => {
                if (!cancelled) {
                    setError(err.message || i18next.t("com_knowledge.load_file_failed"));
                }
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, [fileUrl]);

    if (loading) {
        return (
            <div className="flex flex-1 items-center justify-center bg-[#fbfbfb] text-sm text-text-3">
                {localize("com_knowledge.loading")}
            </div>
        );
    }
    if (error) {
        return (
            <div className="flex flex-1 items-center justify-center bg-[#fbfbfb] text-sm text-text-3">
                {error}
            </div>
        );
    }
    return <MarkdownBlock content={content} />;
}

/** Transcript pane of a media preview: 识别文本 / 入库文本 tabs over the parsed
 *  markdown. Exported so citation previews render the same pane. */
export function MediaTranscriptTabs({ fileUrl }: { fileUrl: string }) {
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
    const { preamble, cues } = parseTranscriptCues(activeContent);

    return (
        <section className="flex h-full min-h-0 flex-col bg-white">
            {/* 12px inset: the segmented control's own 3px padding lines its label
                up with the 16px-inset transcript text below. */}
            <div className="flex shrink-0 items-center px-3 pt-4">
                {/* Segmented control — mirrors the include/exclude tabs in
                    Subscription/CreateChannel/FilterConditionEditor. */}
                <div className="flex flex-shrink-0 rounded-[6px] bg-fill-1 p-[3px]">
                    <button
                        type="button"
                        onClick={() => setActiveTab("recognized")}
                        className={`whitespace-nowrap rounded-sm px-[12px] py-[2px] text-center text-[14px] leading-[22px] transition-colors ${activeTab === "recognized"
                            ? "bg-blue-500/15 font-medium text-blue-500"
                            : "bg-transparent text-text-3 hover:bg-fill-2"}`}
                    >
                        {localize("com_knowledge.recognized_text")}
                    </button>
                    <button
                        type="button"
                        onClick={() => setActiveTab("entry")}
                        className={`whitespace-nowrap rounded-sm px-[12px] py-[2px] text-center text-[14px] leading-[22px] transition-colors ${activeTab === "entry"
                            ? "bg-blue-500/15 font-medium text-blue-500"
                            : "bg-transparent text-text-3 hover:bg-fill-2"}`}
                    >
                        {localize("com_knowledge.knowledge_entry_text")}
                    </button>
                </div>
            </div>
            {loading ? (
                <div className="flex flex-1 items-center justify-center text-sm text-text-3">
                    {localize("com_knowledge.loading")}
                </div>
            ) : error ? (
                <div className="flex flex-1 items-center justify-center text-sm text-text-3">{error}</div>
            ) : (
                // pb clears the AI dock pinned at the bottom of the page.
                <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-[114px] pt-3">
                    {cues.length ? (
                        <>
                            {preamble ? <MarkdownBody content={preamble} className={TRANSCRIPT_MARKDOWN_SIZE} /> : null}
                            <TranscriptCueList cues={cues} />
                        </>
                    ) : (
                        <MarkdownBody content={activeContent} className={TRANSCRIPT_MARKDOWN_SIZE} />
                    )}
                </div>
            )}
        </section>
    );
}

export function RichKnowledgePreview({
    fileName,
    preview,
    actions,
    trailingActions,
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

    if (isMedia) {
        return (
            <div className="flex h-full w-full flex-col overflow-hidden bg-white">
                {!compactMode && (
                    <TopBar
                        fileName={fileName}
                        showZoom={false}
                        onDownload={allowDownload ? onDownloadFile : undefined}
                        actions={actions}
                        trailingActions={trailingActions}
                    />
                )}
                {/* Side-by-side on md+: player left, transcript right, split by a single
                    divider line (no card border/shadow). Stacked on narrow screens. */}
                <div className="flex min-h-0 flex-1 flex-col md:flex-row">
                    <div className="shrink-0 p-4 md:w-1/2 md:overflow-y-auto">
                        <MediaPlayer
                            kind={isVideo ? "video" : "audio"}
                            src={mediaPlaybackUrl}
                            allowDownload={allowDownload}
                            onDownload={onDownloadFile}
                        />
                    </div>
                    {mediaTextUrl ? (
                        <>
                            <div className="h-px shrink-0 bg-fill-3 md:h-auto md:w-px" />
                            <div className="flex min-h-0 min-w-0 flex-1 flex-col">
                                <MediaTranscriptTabs fileUrl={mediaTextUrl} />
                            </div>
                        </>
                    ) : null}
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
                    trailingActions={trailingActions}
                />
            )}
            <div className="flex min-h-0 flex-1 overflow-hidden">
                {webLinkMarkdownUrl ? (
                    <MarkdownFromUrl fileUrl={webLinkMarkdownUrl} />
                ) : (
                    <div className="flex h-full items-center justify-center text-sm text-text-3">
                        {localize("com_knowledge.fetch_preview_link_failed")}
                    </div>
                )}
            </div>
        </div>
    );
}
