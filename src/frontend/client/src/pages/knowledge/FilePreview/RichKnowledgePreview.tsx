// @ts-strict-ignore
import { MarkdownViewer as SharedMarkdownViewer } from '@bisheng/file-viewers/markdown';
import { MediaTranscriptTabs as SharedMediaTranscriptTabs } from '@bisheng/file-viewers/transcript';
import { usePreviewLocale } from '@bisheng/file-viewers/locale';
import type { ReactNode } from "react";
import type { KnowledgeFilePreview } from "~/api/knowledge";
import { useLocalize } from "~/hooks";
import { MediaPlayer } from "./MediaPlayer";
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

function MarkdownFromUrl({ fileUrl }: { fileUrl: string }) {
  const locale = usePreviewLocale();
  const url = resolveKnowledgePreviewUrl(fileUrl);
  return <SharedMarkdownViewer resource={{ originalUrl: url, previewUrl: url }} locale={locale} />;
}
export function MediaTranscriptTabs({ fileUrl }: { fileUrl: string }) {
  const locale = usePreviewLocale();
  const url = resolveKnowledgePreviewUrl(fileUrl);
  return <SharedMediaTranscriptTabs bottomInset={114} key={url} resource={{ originalUrl: '', previewUrl: url }} locale={locale} />;
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

    if (isMedia) {
        return (
            <div className="flex h-full w-full flex-col overflow-hidden bg-white">
                {!compactMode && (
                    <TopBar
                        fileName={fileName}
                        showZoom={false}
                        onDownload={allowDownload ? onDownloadFile : undefined}
                        actions={actions}
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
