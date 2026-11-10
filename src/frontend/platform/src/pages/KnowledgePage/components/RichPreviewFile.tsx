import { useState } from "react";
import { MarkdownViewer as SharedMarkdownViewer } from '@bisheng/file-viewers/markdown';
import { MediaTranscriptTabs as SharedMediaTranscriptTabs } from '@bisheng/file-viewers/transcript';
import { usePreviewLocale } from '@bisheng/file-viewers/locale';
import { PlatformMediaPlayer } from '@/components/bs-comp/preview/DocumentPreview';
import { Outlined } from "bisheng-icons";


import { useTranslation } from "react-i18next";
import TxtFileViewer from "./TxtFileViewer";

declare const __APP_ENV__: any;

type PreviewData = {
  original_url?: string;
  preview_url?: string;
  file_source?: string;
  source_url?: string;
  final_url?: string;
  web_title?: string;
  media_kind?: string;
  html_preview_url?: string;
};

type WebTab = "html" | "text";

const AUDIO_EXTENSIONS = new Set(["mp3", "wav", "m4a", "aac", "flac", "ogg"]);
const VIDEO_EXTENSIONS = new Set(["mp4", "mov", "avi", "mkv", "webm"]);

export type RichPreviewData = PreviewData;

export function isMediaUploadSuffix(suffix?: string) {
  if (!suffix) return false;
  const ext = suffix.toLowerCase();
  return AUDIO_EXTENSIONS.has(ext) || VIDEO_EXTENSIONS.has(ext);
}

export function buildMediaUploadPreviewData(
  originalUrl: string,
  transcriptUrl: string,
  suffix: string,
): PreviewData {
  const ext = suffix.toLowerCase();
  const isVideo = VIDEO_EXTENSIONS.has(ext);
  return {
    original_url: originalUrl,
    preview_url: transcriptUrl,
    file_source: isVideo ? "video_transcript" : "audio_transcript",
    media_kind: isVideo ? "video" : "audio",
  };
}

function normalizeUrl(url?: string) {
  if (!url) return "";
  return url.replace(/https?:\/\/[^/]+/, __APP_ENV__.BASE_URL);
}

function getExtensionFromUrl(url?: string) {
  if (!url) return "";
  const path = url.split("?")[0].split("#")[0];
  const filename = path.split("/").pop() || "";
  const dotIndex = filename.lastIndexOf(".");
  return dotIndex >= 0 ? filename.slice(dotIndex + 1).toLowerCase() : "";
}

function isMediaUrl(url?: string) {
  const ext = getExtensionFromUrl(url);
  return AUDIO_EXTENSIONS.has(ext) || VIDEO_EXTENSIONS.has(ext);
}

export function isRichKnowledgePreview(previewData?: PreviewData) {
  if (!previewData) return false;
  const ext = getExtensionFromUrl(previewData.original_url || previewData.preview_url);
  return (
    previewData.file_source === "web_link"
    || previewData.file_source === "audio_transcript"
    || previewData.file_source === "video_transcript"
    || previewData.media_kind === "audio"
    || previewData.media_kind === "video"
    || AUDIO_EXTENSIONS.has(ext)
    || VIDEO_EXTENSIONS.has(ext)
  );
}

function isMediaPreview(previewData?: PreviewData) {
  if (!previewData) return false;
  const ext = getExtensionFromUrl(previewData.original_url || previewData.preview_url);
  return (
    previewData.file_source === "audio_transcript"
    || previewData.file_source === "video_transcript"
    || previewData.media_kind === "audio"
    || previewData.media_kind === "video"
    || AUDIO_EXTENSIONS.has(ext)
    || VIDEO_EXTENSIONS.has(ext)
  );
}

function isVideoPreview(previewData?: PreviewData) {
  if (!previewData) return false;
  const ext = getExtensionFromUrl(previewData.original_url || previewData.preview_url);
  return previewData.file_source === "video_transcript" || previewData.media_kind === "video" || VIDEO_EXTENSIONS.has(ext);
}

function TextFromUrl({ fileUrl }: { fileUrl: string }) {
  const locale = usePreviewLocale();
  const url = normalizeUrl(fileUrl);
  return <SharedMarkdownViewer resource={{ originalUrl: url, previewUrl: url }} locale={locale} />;
}
export function MediaTranscriptTabs({ fileUrl, className }: { fileUrl: string; className?: string }) {
  const locale = usePreviewLocale();
  const url = normalizeUrl(fileUrl);
  return <SharedMediaTranscriptTabs key={url} resource={{ originalUrl: '', previewUrl: url }} locale={locale} className={className} />;
}

export default function RichPreviewFile({ file, previewData }: { file: any; previewData: PreviewData }) {
  const { t } = useTranslation();
  const [webTab, setWebTab] = useState<WebTab>("html");
  const isMedia = isMediaPreview(previewData);
  const isVideo = isVideoPreview(previewData);
  const sourceUrl = previewData?.final_url || previewData?.source_url || "";
  const mediaTextUrl = previewData?.preview_url && !isMediaUrl(previewData.preview_url) ? previewData.preview_url : "";
  const textUrl = isMedia ? mediaTextUrl : previewData?.preview_url || previewData?.original_url || "";
  const htmlUrl = previewData?.html_preview_url || "";
  const originalUrl = previewData?.original_url || "";
  const mediaUrl = normalizeUrl(originalUrl);
  const title = previewData?.web_title || file?.file_name || file?.fileName || file?.name || "";

  if (isMedia) {
    return (
      <div className="flex h-full min-h-0 flex-col bg-gray-50">
        <div className="shrink-0 overflow-visible p-3 pb-0">
          <section className="overflow-visible rounded-md border bg-white p-3 shadow-sm">
            <div className="mb-2 text-sm font-medium text-gray-800">{title}</div>
            {isVideo ? (
              <PlatformMediaPlayer kind="video" src={mediaUrl} />
            ) : (
              <div className="flex min-h-[160px] flex-col justify-end overflow-visible py-1">
                <PlatformMediaPlayer kind="audio" src={mediaUrl} />
              </div>
            )}
          </section>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-3 pt-3">
          <MediaTranscriptTabs fileUrl={mediaTextUrl} />
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-gray-50">
      <div className="flex shrink-0 items-center justify-between border-b bg-white px-3 py-2">
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setWebTab("html")}
            className={`h-8 rounded-md px-3 text-sm ${webTab === "html" ? "bg-primary text-white" : "bg-gray-100 text-gray-600"}`}
          >
            {t("mediaPreview.webPreview")}
          </button>
          <button
            type="button"
            onClick={() => setWebTab("text")}
            className={`h-8 rounded-md px-3 text-sm ${webTab === "text" ? "bg-primary text-white" : "bg-gray-100 text-gray-600"}`}
          >
            {t("mediaPreview.entryText")}
          </button>
        </div>
        {sourceUrl ? (
          <a className="flex items-center gap-1 text-sm text-primary" href={sourceUrl} target="_blank" rel="noreferrer">
            <Outlined.ViewOnNewTab className="size-4" />
            {t("mediaPreview.openSourcePage")}
          </a>
        ) : null}
      </div>
      <div className="min-h-0 flex-1 overflow-hidden">
        {webTab === "html" ? (
          htmlUrl ? <TxtFileViewer html filePath={htmlUrl} /> : (
            <div className="flex h-full items-center justify-center text-sm text-gray-500">
              {t("mediaPreview.noWebSnapshot")}
            </div>
          )
        ) : textUrl ? (
          <TextFromUrl fileUrl={textUrl} />
        ) : null}
      </div>
    </div>
  );
}
