import { LoadingIcon } from "@/components/bs-icons/loading";
import { ExternalLink } from "lucide-react";
import { useEffect, useState } from "react";
import { MarkdownView } from "./PreviewParagraph";
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

type MediaTab = "recognized" | "entry";
type WebTab = "html" | "text";

const AUDIO_EXTENSIONS = new Set(["mp3", "wav", "m4a", "aac", "flac", "ogg"]);
const VIDEO_EXTENSIONS = new Set(["mp4", "mov", "avi", "mkv", "webm"]);

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

function extractMarkdownSection(markdown: string, heading: string) {
  const pattern = new RegExp(`^##\\s+${heading}\\s*$`, "m");
  const match = markdown.match(pattern);
  if (!match || match.index === undefined) return "";
  const start = match.index + match[0].length;
  const rest = markdown.slice(start);
  const nextHeading = rest.search(/^##\s+/m);
  return (nextHeading >= 0 ? rest.slice(0, nextHeading) : rest).trim();
}

function TextFromUrl({ fileUrl, section }: { fileUrl: string; section?: string }) {
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    fetch(normalizeUrl(fileUrl))
      .then((response) => {
        if (!response.ok) throw new Error(`Failed to fetch file: ${response.status}`);
        return response.text();
      })
      .then((text) => {
        if (!cancelled) setContent(text);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [fileUrl]);

  if (loading) {
    return <div className="flex h-full items-center justify-center text-gray-400"><LoadingIcon /></div>;
  }
  if (error) {
    return <div className="flex h-full items-center justify-center text-sm text-red-500">{error}</div>;
  }

  const sectionText = section ? extractMarkdownSection(content, section) : "";
  const text = sectionText || content;
  return (
    <div className="h-full overflow-y-auto bg-gray-50 p-4">
      <MarkdownView noHead data={{ text }} />
    </div>
  );
}

export default function RichPreviewFile({ file, previewData }: { file: any; previewData: PreviewData }) {
  const [mediaTab, setMediaTab] = useState<MediaTab>("recognized");
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
              <video className="max-h-[280px] w-full rounded bg-black" src={mediaUrl} controls />
            ) : (
              <div className="flex min-h-[160px] flex-col justify-end overflow-visible py-1">
                <audio className="w-full" src={mediaUrl} controls />
              </div>
            )}
          </section>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-3 pt-3">
          <div className="flex min-h-[320px] flex-col overflow-hidden rounded-md border bg-white shadow-sm">
            <div className="flex shrink-0 gap-2 border-b px-3 py-2">
              <button
                type="button"
                onClick={() => setMediaTab("recognized")}
                className={`h-8 rounded-md px-3 text-sm ${mediaTab === "recognized" ? "bg-primary text-white" : "bg-gray-100 text-gray-600"}`}
              >
                识别文本
              </button>
              <button
                type="button"
                onClick={() => setMediaTab("entry")}
                className={`h-8 rounded-md px-3 text-sm ${mediaTab === "entry" ? "bg-primary text-white" : "bg-gray-100 text-gray-600"}`}
              >
                入库文本
              </button>
            </div>
            {mediaTextUrl ? (
              <div className="min-h-0 flex-1 overflow-hidden">
                <TextFromUrl fileUrl={mediaTextUrl} section={mediaTab === "recognized" ? "识别文本" : "入库文本"} />
              </div>
            ) : null}
          </div>
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
            网页预览
          </button>
          <button
            type="button"
            onClick={() => setWebTab("text")}
            className={`h-8 rounded-md px-3 text-sm ${webTab === "text" ? "bg-primary text-white" : "bg-gray-100 text-gray-600"}`}
          >
            入库文本
          </button>
        </div>
        {sourceUrl ? (
          <a className="flex items-center gap-1 text-sm text-primary" href={sourceUrl} target="_blank" rel="noreferrer">
            <ExternalLink className="size-4" />
            打开原网页
          </a>
        ) : null}
      </div>
      <div className="min-h-0 flex-1 overflow-hidden">
        {webTab === "html" ? (
          htmlUrl ? <TxtFileViewer html filePath={htmlUrl} /> : (
            <div className="flex h-full items-center justify-center text-sm text-gray-500">
              暂无网页快照，请查看入库文本或打开原网页。
            </div>
          )
        ) : textUrl ? (
          <TextFromUrl fileUrl={textUrl} />
        ) : null}
      </div>
    </div>
  );
}
