import { FileText, X } from 'lucide-react';
import type { ChatCitation } from '~/api/chatApi';
import { useMediaQuery } from '~/hooks';
import { useLocalize } from '~/hooks';
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
  const localize = useLocalize();
  const isH5 = useMediaQuery('(max-width: 768px)');
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
  const handleDownload = () => {
    if (!fileUrl) return;
    const link = document.createElement('a');
    link.href = fileUrl;
    link.download = fileName;
    link.target = '_blank';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <>
      <div
        className={`fixed inset-0 z-[58] ${isH5 ? 'bg-black/20' : 'bg-black/10'}`}
        aria-hidden="true"
        onClick={onClose}
      />
      <aside
        className={
          isH5
            ? "fixed inset-x-0 bottom-0 top-[44px] z-[60] flex flex-col rounded-t-2xl bg-white"
            : "fixed inset-y-0 right-0 z-[60] flex w-[min(860px,calc(100vw-24px))] flex-col border-l border-[#E5E6EB] bg-white shadow-[0_8px_28px_rgba(0,0,0,0.16)]"
        }
        aria-label="文档预览"
      >
        <div className={`flex shrink-0 items-center justify-between border-b border-[#F2F3F5] ${isH5 ? 'h-12 px-3' : 'h-14 px-5'}`}>
          <div className="flex min-w-0 items-center gap-2">
            {!isH5 && <FileText className="size-4 shrink-0 text-[#165DFF]" />}
            {!isH5 && (
              <h2 className={`min-w-0 truncate font-semibold text-[#1D2129] ${isH5 ? 'text-[14px] leading-5' : 'text-[16px] leading-6'}`} title={fileName}>
                {fileName}
              </h2>
            )}
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

        <div className={`min-h-0 flex-1 ${isH5 ? 'pb-[78px]' : ''}`}>
          {fileUrl ? (
            <FilePreview
              fileName={fileName}
              fileType={fileType}
              fileUrl={fileUrl}
              highlightBboxes={bboxes}
              targetBBox={targetBBox}
              compactMode={isH5}
            />
          ) : (
            <div className="flex h-full items-center justify-center text-[14px] text-[#86909C]">
              暂无可预览文件地址
            </div>
          )}
        </div>
        {isH5 && (
          <div className="absolute inset-x-0 bottom-0 z-10 border-t border-[#F2F3F5] bg-white px-4 py-3">
            <button
              type="button"
              onClick={handleDownload}
              disabled={!fileUrl}
              className="inline-flex h-11 w-full items-center justify-center rounded-[8px] border border-[#335CFF] bg-white text-[16px] font-medium leading-none text-[#335CFF] disabled:cursor-not-allowed disabled:border-[#C9CDD4] disabled:text-[#C9CDD4]"
            >
              {localize("com_knowledge.download_file")}
            </button>
          </div>
        )}
      </aside>
    </>
  );
}
