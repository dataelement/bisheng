import { FileText, X } from 'lucide-react';
import type { ChatCitation } from '~/api/chatApi';
import FilePreview from '~/pages/knowledge/FilePreview';
import {
  getCitationDocumentFileType,
  getCitationDocumentName,
  getCitationDocumentUrl,
  getCitationItemBBoxes,
  isRagCitation,
  toAbsolutePreviewUrl,
  type CitationPdfBBox,
} from './citationUtils';

export type CitationDocumentPreviewState = {
  detail: ChatCitation;
  itemId?: string;
  locateChunk?: boolean;
};

type CitationDocumentPreviewDrawerProps = {
  preview: CitationDocumentPreviewState | null;
  onClose: () => void;
};

function getExtFromUrl(url: string) {
  const path = url.split('?')[0].split('#')[0];
  return path.split('.').pop()?.toLowerCase() || '';
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
  return name.split('.').pop()?.toLowerCase() || '';
}

export default function CitationDocumentPreviewDrawer({
  preview,
  onClose,
}: CitationDocumentPreviewDrawerProps) {
  if (!preview || !isRagCitation(preview.detail)) {
    return null;
  }

  const { detail, itemId, locateChunk } = preview;
  const fileName = getCitationDocumentName(detail);
  const rawFileUrl = getCitationDocumentUrl(detail);
  const fileType = resolveFileType(detail, rawFileUrl);
  const fileUrl = toAbsolutePreviewUrl(rawFileUrl);
  const shouldLocateChunk = locateChunk && fileType === 'pdf';
  const bboxes: CitationPdfBBox[] = shouldLocateChunk ? getCitationItemBBoxes(detail, itemId) : [];
  const targetBBox = bboxes[0] ?? null;

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

        <div className="min-h-0 flex-1">
          {fileUrl ? (
            <FilePreview
              fileName={fileName}
              fileType={fileType}
              fileUrl={fileUrl}
              highlightBboxes={bboxes}
              targetBBox={targetBBox}
            />
          ) : (
            <div className="flex h-full items-center justify-center text-[14px] text-[#86909C]">
              暂无可预览文件地址
            </div>
          )}
        </div>
      </aside>
    </>
  );
}
