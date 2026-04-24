import { FileText, X } from "lucide-react";
import FileView from "@/components/bs-comp/FileView";
import { FileIcon } from "@/components/bs-icons/file";
import DocxPreview from "@/pages/KnowledgePage/components/DocxFileViewer";
import TxtFileViewer from "@/pages/KnowledgePage/components/TxtFileViewer";
import type { ChatCitation } from "@/controllers/API";
import {
  getCitationDocumentFileType,
  getCitationDocumentName,
  getCitationDocumentUrl,
  getCitationItemBBoxes,
  isRagCitation,
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
}: {
  fileType: string;
  fileUrl: string;
  fileName: string;
  bboxes: CitationPdfBBox[];
  targetBBox: CitationPdfBBox | null;
}) {
  const baseUrl = __APP_ENV__?.BASE_URL || "";
  switch (fileType) {
    case "pdf":
    case "ppt":
    case "pptx":
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
          <div>该类型文件不支持预览</div>
        </div>
      );
  }
}

export function CitationDocumentPreviewContent({
  preview,
  compactMode = false,
  className,
}: CitationDocumentPreviewContentProps) {
  if (!preview || !isRagCitation(preview.detail)) {
    return null;
  }

  const { detail, itemId, locateChunk } = preview;
  const fileName = getCitationDocumentName(detail);
  const rawFileUrl = getCitationDocumentUrl(detail);
  const fileType = resolveFileType(detail, rawFileUrl);
  const fileUrl = toAbsolutePreviewUrl(rawFileUrl);
  const shouldLocateChunk = locateChunk && fileType === "pdf";
  const bboxes: CitationPdfBBox[] = shouldLocateChunk ? getCitationItemBBoxes(detail, itemId) : [];
  const targetBBox = bboxes[0] ?? null;

  return (
    <div className={className || "min-h-0 flex-1"}>
      {fileUrl ? (
        <div className="h-full min-h-0 overflow-hidden">
          {renderPreviewContent({ fileType, fileUrl, fileName, bboxes, targetBBox })}
        </div>
      ) : (
        <div className="flex h-full items-center justify-center text-[14px] text-[#86909C]">
          暂无可预览文件地址
        </div>
      )}
    </div>
  );
}

export default function CitationDocumentPreviewDrawer({
  preview,
  onClose,
}: CitationDocumentPreviewDrawerProps) {
  if (!preview || !isRagCitation(preview.detail)) {
    return null;
  }

  const { detail } = preview;
  const fileName = getCitationDocumentName(detail);

  return (
    <>
      <div
        className="fixed inset-0 z-[58] bg-black/10"
        aria-hidden="true"
        onClick={onClose}
      />
      <aside
        className="fixed inset-y-0 right-0 z-[60] flex w-[min(860px,calc(100vw-24px))] flex-col border-l border-[#E5E6EB] bg-white shadow-[0_8px_28px_rgba(0,0,0,0.16)]"
        aria-label="文档预览"
      >
        <div className="flex h-14 shrink-0 items-center justify-between border-b border-[#F2F3F5] px-5">
          <div className="flex min-w-0 items-center gap-2">
            <FileText className="size-4 shrink-0 text-[#165DFF]" />
            <h2 className="min-w-0 truncate text-[16px] font-semibold leading-6 text-[#1D2129]" title={fileName}>
              {fileName}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex size-8 items-center justify-center rounded-[6px] text-[#86909C] hover:bg-[#F2F3F5] hover:text-[#4E5969]"
            aria-label="关闭文档预览"
          >
            <X className="size-5" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-hidden">
          <CitationDocumentPreviewContent preview={preview} />
        </div>
      </aside>
    </>
  );
}
