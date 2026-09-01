// @ts-strict-ignore
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Download, FileText, Loader2, X } from "lucide-react";
import FileView from "@/components/bs-comp/FileView";
import { cname } from "@/components/bs-ui/utils";
import { FileIcon } from "@/components/bs-icons/file";
import { ExcelPreview } from "@bisheng/file-viewers";
import DocxPreview from "@/pages/KnowledgePage/components/DocxFileViewer";
import TxtFileViewer from "@/pages/KnowledgePage/components/TxtFileViewer";
import { MediaTranscriptTabs } from "@/pages/KnowledgePage/components/RichPreviewFile";
import { getCitationDetail, type ChatCitation } from "@/controllers/API";
import {
  getCitationDocumentDownloadUrl,
  getCitationDocumentFileType,
  getCitationDocumentName,
  getCitationDocumentPreviewUrl,
  getCitationItemBBoxes,
  isMediaCitation,
  isRagCitation,
  isRagCitationMissingPreviewUrl,
  toAbsolutePreviewUrl,
  type CitationPdfBBox,
} from "./citationUtils";

declare const __APP_ENV__: any;

export type CitationDocumentPreviewState = {
  detail: ChatCitation;
  itemId?: string;
  locateChunk?: boolean;
};

type CitationDocumentPreviewDrawerProps = {
  preview: CitationDocumentPreviewState | null;
  onClose: () => void;
};

type CitationDocumentPreviewContentProps = {
  preview: CitationDocumentPreviewState | null;
  compactMode?: boolean;
  className?: string;
};

function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(() => {
    if (typeof window === "undefined") {
      return false;
    }
    return window.matchMedia(query).matches;
  });

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const mediaQuery = window.matchMedia(query);
    const handleChange = () => setMatches(mediaQuery.matches);
    handleChange();
    mediaQuery.addEventListener("change", handleChange);
    return () => {
      mediaQuery.removeEventListener("change", handleChange);
    };
  }, [query]);

  return matches;
}

function getExtFromUrl(url: string) {
  const path = url.split("?")[0].split("#")[0];
  return path.split(".").pop()?.toLowerCase() || "";
}

function resolveFileType(detail: ChatCitation, rawUrl: string) {
  const urlExt = getExtFromUrl(rawUrl);
  if (urlExt) {
    return urlExt;
  }

  const fileType = getCitationDocumentFileType(detail);
  if (fileType) {
    return fileType;
  }

  const name = getCitationDocumentName(detail);
  return name.split(".").pop()?.toLowerCase() || "";
}

/** Audio/video citation: the clip itself plus the transcript the answer quoted,
 *  the same pairing the knowledge space shows. */
const VIDEO_CITATION_EXTENSIONS = new Set(["mp4", "mov", "avi", "mkv", "webm"]);

function MediaPreview({ fileUrl, transcriptUrl, isVideo }: { fileUrl: string; transcriptUrl: string; isVideo: boolean }) {
  return (
    <div className="flex h-full min-h-0 flex-col bg-gray-50">
      <div className="shrink-0 overflow-visible p-3 pb-0">
        <section className="overflow-visible rounded-md border bg-white p-3 shadow-sm">
          {isVideo ? (
            <video className="max-h-[280px] w-full rounded bg-black" src={fileUrl} controls />
          ) : (
            <div className="flex min-h-[120px] flex-col justify-end overflow-visible py-1">
              <audio className="w-full" src={fileUrl} controls />
            </div>
          )}
        </section>
      </div>
      {transcriptUrl ? (
        <div className="min-h-0 flex-1 overflow-y-auto p-3 pt-3">
          <MediaTranscriptTabs fileUrl={transcriptUrl} />
        </div>
      ) : null}
    </div>
  );
}

function buildPdfLabels(bboxes: CitationPdfBBox[]) {
  const labels: Record<number, { id: string; label: [number, number, number, number]; active: boolean; txt: string }[]> = {};
  bboxes.forEach((item, index) => {
    const page = item.page + 1;
    if (!labels[page]) {
      labels[page] = [];
    }
    labels[page].push({
      id: `${page}-${index}-${item.bbox.join("-")}`,
      label: item.bbox,
      active: true,
      txt: "",
    });
  });
  return labels;
}

function renderPreviewContent({
  fileType,
  fileUrl,
  fileName,
  bboxes,
  targetBBox,
  t,
}: {
  t: (key: string) => string;
  fileType: string;
  fileUrl: string;
  fileName: string;
  bboxes: CitationPdfBBox[];
  targetBBox: CitationPdfBBox | null;
}) {
  const baseUrl = __APP_ENV__?.BASE_URL || "";
  switch (fileType) {
    case "pdf":
      return (
        <FileView
          startIndex={1}
          scrollTo={targetBBox ? [targetBBox.page + 1, targetBBox.bbox[1] || 0] : [1, 0]}
          fileUrl={fileUrl}
          labels={buildPdfLabels(bboxes)}
        />
      );
    case "md":
      return <TxtFileViewer markdown filePath={fileUrl} />;
    case "html":
      return <TxtFileViewer html filePath={fileUrl} />;
    case "csv":
    case "xlsx":
    case "xls":
    case "et":
      return <ExcelPreview filePath={fileUrl} />;
    case "txt":
      return <TxtFileViewer filePath={fileUrl} />;
    case "doc":
    case "docx":
      return <DocxPreview filePath={fileUrl} />;
    case "png":
    case "jpg":
    case "jpeg":
    case "bmp":
      return (
        <div className="flex h-full items-start justify-center overflow-auto bg-[#F5F6F8] p-6">
          <img
            className="max-w-full border"
            src={fileUrl.replace(/https?:\/\/[^/]+/, baseUrl)}
            alt={fileName}
          />
        </div>
      );
    default:
      return (
        <div className="flex h-full flex-col items-center justify-center gap-3 text-[14px] text-[#86909C]">
          <FileIcon type="txt" className="size-16 opacity-60" />
          <div>{t("citation.unsupportedPreview")}</div>
        </div>
      );
  }
}

/**
 * Auto-resolve a RAG citation detail when the preview URL is missing.
 * Returns the resolved detail (or the original one if already complete / non-RAG).
 */
function useResolvedCitationDetail(preview: CitationDocumentPreviewState | null) {
  const [resolvedDetail, setResolvedDetail] = useState<ChatCitation | null>(null);
  const [isResolving, setIsResolving] = useState(false);

  const originalDetail = preview?.detail ?? null;
  const citationId = originalDetail?.citationId;

  useEffect(() => {
    setResolvedDetail(null);
    setIsResolving(false);

    if (!originalDetail || !citationId) {
      return;
    }

    if (!isRagCitationMissingPreviewUrl(originalDetail)) {
      // Already has URL or not a RAG citation — no resolve needed
      return;
    }

    if (citationId.startsWith("citation:")) {
      return;
    }

    let cancelled = false;
    setIsResolving(true);

    getCitationDetail(citationId)
      .then((resolved) => {
        if (!cancelled && resolved) {
          setResolvedDetail(resolved);
        }
      })
      .catch(() => {
        // Resolve failed — keep using original detail
      })
      .finally(() => {
        if (!cancelled) {
          setIsResolving(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [citationId, originalDetail]);

  const effectiveDetail = resolvedDetail || originalDetail;

  return { effectiveDetail, isResolving };
}

export function CitationDocumentPreviewContent({
  preview,
  compactMode = false,
  className,
}: CitationDocumentPreviewContentProps) {
  const { t } = useTranslation();
  const { effectiveDetail, isResolving } = useResolvedCitationDetail(preview);

  if (!preview || !isRagCitation(effectiveDetail)) {
    return null;
  }

  const { itemId, locateChunk } = preview;
  const fileName = getCitationDocumentName(effectiveDetail);
  const isMedia = isMediaCitation(effectiveDetail);
  // A clip renders from the original file (the player), with its transcript —
  // which is what the preview URL points at — beside it. Everything else
  // renders from the preview stand-in.
  const rawFileUrl = isMedia
    ? getCitationDocumentDownloadUrl(effectiveDetail)
    : getCitationDocumentPreviewUrl(effectiveDetail);
  const fileType = resolveFileType(effectiveDetail, rawFileUrl);
  const fileUrl = toAbsolutePreviewUrl(rawFileUrl);
  const transcriptUrl = isMedia ? toAbsolutePreviewUrl(getCitationDocumentPreviewUrl(effectiveDetail)) : "";
  const shouldLocateChunk = locateChunk && fileType === "pdf";
  const bboxes: CitationPdfBBox[] = shouldLocateChunk ? getCitationItemBBoxes(effectiveDetail, itemId) : [];
  const targetBBox = bboxes[0] ?? null;

  return (
    <div className={className || "flex h-full min-h-0 flex-1 flex-col"}>
      {isResolving ? (
        <div className="flex h-full items-center justify-center gap-2 text-[14px] text-[#86909C]">
          <Loader2 className="size-4 animate-spin" />
          {t("citation.loadingPreview")}
        </div>
      ) : isMedia && fileUrl ? (
        <div className="h-full min-h-0 overflow-hidden">
          <MediaPreview
            fileUrl={fileUrl}
            transcriptUrl={transcriptUrl}
            isVideo={VIDEO_CITATION_EXTENSIONS.has(fileType)}
          />
        </div>
      ) : fileUrl ? (
        <div className="h-full min-h-0 overflow-hidden">
          {renderPreviewContent({ fileType, fileUrl, fileName, bboxes, targetBBox, t })}
        </div>
      ) : (
        <div className="flex h-full items-center justify-center text-[14px] text-[#86909C]">
          {t("citation.noPreviewUrl")}
        </div>
      )}
    </div>
  );
}

export default function CitationDocumentPreviewDrawer({
  preview,
  onClose,
}: CitationDocumentPreviewDrawerProps) {
  const { t } = useTranslation();
  const { effectiveDetail } = useResolvedCitationDetail(preview);
  const isPhoneViewport = useMediaQuery("(max-width: 576px)");
  const isNarrowLayout = useMediaQuery("(max-width: 768px)");
  const isFullBleedMobile = isPhoneViewport;
  const drawerRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!preview || !isRagCitation(effectiveDetail) || !isFullBleedMobile) {
      return;
    }

    const originalBodyOverflow = document.body.style.overflow;
    const originalHtmlOverflow = document.documentElement.style.overflow;
    document.body.style.overflow = "hidden";
    document.documentElement.style.overflow = "hidden";

    return () => {
      document.body.style.overflow = originalBodyOverflow;
      document.documentElement.style.overflow = originalHtmlOverflow;
    };
  }, [effectiveDetail, isFullBleedMobile, preview]);

  useEffect(() => {
    if (!preview || !isRagCitation(effectiveDetail) || isFullBleedMobile) {
      return;
    }

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (!target || drawerRef.current?.contains(target)) return;
      onClose();
    };

    document.addEventListener("pointerdown", handlePointerDown, true);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown, true);
    };
  }, [effectiveDetail, isFullBleedMobile, onClose, preview]);

  if (!preview || !isRagCitation(effectiveDetail)) {
    return null;
  }

  const fileName = getCitationDocumentName(effectiveDetail);
  const downloadFileUrl = toAbsolutePreviewUrl(getCitationDocumentDownloadUrl(effectiveDetail));

  const handleDownload = () => {
    if (!downloadFileUrl) return;
    const link = document.createElement("a");
    link.href = downloadFileUrl;
    link.download = fileName;
    link.target = "_blank";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const drawer = (
    <aside
      ref={drawerRef}
      className={cname(
        "fixed flex flex-col bg-white",
        isFullBleedMobile && "inset-0 z-[120] overflow-hidden overscroll-contain touch-pan-y",
        !isFullBleedMobile && "inset-y-0 right-0 z-[121] w-[min(520px,calc(var(--bs-vw,100vw)-24px))] border-l border-[#E5E6EB] shadow-[0_8px_28px_rgba(0,0,0,0.16)]",
      )}
      aria-label={t("citation.documentPreview")}
      onClick={(event) => event.stopPropagation()}
      onPointerDown={(event) => event.stopPropagation()}
    >
      <div
        className={cname(
          "flex shrink-0 items-center justify-between border-b border-[#F2F3F5]",
          isFullBleedMobile ? "h-11 px-2 pt-[env(safe-area-inset-top,0px)]" : "h-14 px-3",
        )}
      >
        <div className="flex min-w-0 items-center gap-2">
          {(!isNarrowLayout || isFullBleedMobile) && <FileText className="size-4 shrink-0 text-[#165DFF]" />}
          <h2
            className={cname(
              "min-w-0 truncate font-semibold text-[#1D2129]",
              isNarrowLayout ? "text-[14px] leading-5" : "text-[16px] leading-6",
            )}
            title={fileName}
          >
            {fileName}
          </h2>
          {isNarrowLayout && (
            <button
              type="button"
              onClick={handleDownload}
              disabled={!downloadFileUrl}
              className={cname(
                "shrink-0 items-center justify-center text-[#86909C] hover:bg-[#F2F3F5] hover:text-[#335CFF] disabled:cursor-not-allowed disabled:text-[#C9CDD4]",
                isFullBleedMobile ? "inline-flex size-8 rounded-md" : "inline-flex size-6 rounded-[6px]",
              )}
              aria-label={t("citation.downloadDocument")}
            >
              <Download className="size-4" />
            </button>
          )}
        </div>
        <div className="flex items-center gap-1">
          {!isNarrowLayout && (
            <button
              type="button"
              onClick={handleDownload}
              disabled={!downloadFileUrl}
              className="inline-flex size-8 shrink-0 items-center justify-center rounded-[6px] text-[#86909C] hover:bg-[#F2F3F5] hover:text-[#335CFF] disabled:cursor-not-allowed disabled:text-[#C9CDD4]"
              aria-label={t("citation.downloadDocument")}
            >
              <Download className="size-4" />
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            className={cname(
              "items-center justify-center text-[#A9AEB8] hover:bg-[#F2F3F5] hover:text-[#4E5969]",
              isFullBleedMobile ? "inline-flex size-8 rounded-md" : "inline-flex size-6 rounded-[6px]",
            )}
            aria-label={t("citation.closeDocumentPreview")}
          >
            <X className="size-4" strokeWidth={1.5} />
          </button>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden overscroll-contain [-webkit-overflow-scrolling:touch]">
        <CitationDocumentPreviewContent preview={preview} compactMode={isNarrowLayout} />
      </div>
    </aside>
  );

  if (isFullBleedMobile) {
    return drawer;
  }

  return drawer;
}
