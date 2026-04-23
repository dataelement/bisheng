import { FileText, X } from 'lucide-react';
import type { ChatCitation } from '~/api/chatApi';
import { useLocalize } from '~/hooks';
import useMediaQuery from '~/hooks/useMediaQuery';
import FilePreview from '~/pages/knowledge/FilePreview';
import { cn } from '~/utils';
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

type CitationDocumentPreviewContentProps = {
  preview: CitationDocumentPreviewState | null;
  compactMode?: boolean;
  className?: string;
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
  const shouldLocateChunk = locateChunk && fileType === 'pdf';
  const bboxes: CitationPdfBBox[] = shouldLocateChunk ? getCitationItemBBoxes(detail, itemId) : [];
  const targetBBox = bboxes[0] ?? null;

  return (
    <div className={cn('min-h-0 flex-1', className)}>
      {fileUrl ? (
        <FilePreview
          fileName={fileName}
          fileType={fileType}
          fileUrl={fileUrl}
          highlightBboxes={bboxes}
          targetBBox={targetBBox}
          compactMode={compactMode}
        />
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
  const localize = useLocalize();
  const isH5 = useMediaQuery('(max-width: 576px)');
  /** 576 以下：文档预览撑满视口（与订阅文章 H5 全屏阅读一致） */
  const isLt576 = useMediaQuery('(max-width: 575px)');
  const isFullBleedMobile = isH5 && isLt576;
  if (!preview || !isRagCitation(preview.detail)) {
    return null;
  }

  const { detail } = preview;
  const fileName = getCitationDocumentName(detail);
  const rawFileUrl = getCitationDocumentUrl(detail);
  const fileUrl = toAbsolutePreviewUrl(rawFileUrl);
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
        className={cn(
          'z-[60] flex flex-col bg-white',
          isFullBleedMobile && 'fixed inset-0',
          isH5 &&
            !isFullBleedMobile &&
            'fixed inset-x-0 bottom-0 top-[44px] rounded-t-2xl',
          !isH5 &&
            'fixed inset-y-0 right-0 w-[min(860px,calc(100vw-24px))] border-l border-[#E5E6EB] shadow-[0_8px_28px_rgba(0,0,0,0.16)]',
        )}
        aria-label="文档预览"
      >
        <div
          className={cn(
            'flex shrink-0 items-center justify-between border-b border-[#F2F3F5]',
            isFullBleedMobile && 'min-h-12 px-3 pt-[env(safe-area-inset-top,0px)]',
            isH5 && !isFullBleedMobile && 'h-12 px-3',
            !isH5 && 'h-14 px-5',
          )}
        >
          <div className="flex min-w-0 items-center gap-2">
            {(!isH5 || isFullBleedMobile) && (
              <FileText className="size-4 shrink-0 text-[#165DFF]" />
            )}
            {(!isH5 || isFullBleedMobile) && (
              <h2
                className={cn(
                  'min-w-0 truncate font-semibold text-[#1D2129]',
                  isH5 ? 'text-[14px] leading-5' : 'text-[16px] leading-6',
                )}
                title={fileName}
              >
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

        <div
          className={cn(
            'min-h-0 flex-1',
            isFullBleedMobile && 'pb-[calc(4.875rem+env(safe-area-inset-bottom,0px))]',
            isH5 && !isFullBleedMobile && 'pb-[78px]',
          )}
        >
          <CitationDocumentPreviewContent preview={preview} compactMode={isH5} />
        </div>
        {isH5 && (
          <div
            className={cn(
              'absolute inset-x-0 bottom-0 z-10 border-t border-[#F2F3F5] bg-white px-4',
              isFullBleedMobile
                ? 'pb-[calc(0.75rem+env(safe-area-inset-bottom,0px))] pt-3'
                : 'py-3',
            )}
          >
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
