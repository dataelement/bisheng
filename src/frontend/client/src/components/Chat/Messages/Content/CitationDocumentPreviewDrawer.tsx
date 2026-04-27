import { Download, FileText, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useSetRecoilState } from 'recoil';
import type { ChatCitation } from '~/api/chatApi';
import { useLocalize, useMediaQuery, usePrefersMobileLayout } from '~/hooks';
import store from '~/store';
import FilePreview from '~/pages/knowledge/FilePreview';
import { cn } from '~/utils';
import {
  getCitationDocumentFileType,
  getCitationDocumentName,
  getCitationDocumentUrl,
  getCitationItemBBoxes,
  isRagCitation,
  resolveCitationDocumentUrl,
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
  const detail = preview?.detail ?? null;
  const canRenderPreview = !!detail && isRagCitation(detail);
  const itemId = preview?.itemId;
  const locateChunk = preview?.locateChunk;
  const fileName = detail ? getCitationDocumentName(detail) : '';
  const rawFileUrl = detail ? getCitationDocumentUrl(detail) : '';
  const [resolvedRawFileUrl, setResolvedRawFileUrl] = useState(rawFileUrl);
  const [isResolvingFileUrl, setIsResolvingFileUrl] = useState(false);
  const fileType = canRenderPreview
    ? resolveFileType(detail as ChatCitation, resolvedRawFileUrl || rawFileUrl)
    : '';
  const fileUrl = toAbsolutePreviewUrl(resolvedRawFileUrl || rawFileUrl);
  const shouldLocateChunk = !!locateChunk && fileType === 'pdf';
  const bboxes: CitationPdfBBox[] = shouldLocateChunk
    ? getCitationItemBBoxes(detail as ChatCitation, itemId)
    : [];
  const targetBBox = bboxes[0] ?? null;

  useEffect(() => {
    let active = true;
    setResolvedRawFileUrl(rawFileUrl);

    if (!canRenderPreview || !detail) {
      setIsResolvingFileUrl(false);
      return () => {
        active = false;
      };
    }

    if (rawFileUrl) {
      setIsResolvingFileUrl(false);
      return () => {
        active = false;
      };
    }

    setIsResolvingFileUrl(true);
    void resolveCitationDocumentUrl(detail as ChatCitation).then((nextUrl) => {
      if (!active) return;
      setResolvedRawFileUrl(nextUrl || '');
      setIsResolvingFileUrl(false);
    });

    return () => {
      active = false;
    };
  }, [canRenderPreview, detail, rawFileUrl]);

  if (!canRenderPreview) {
    return null;
  }

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
      ) : isResolvingFileUrl ? (
        <div className="flex h-full items-center justify-center text-[14px] text-[#86909C]">
          正在加载文件预览...
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
  const localize = useLocalize();
  const isNarrowLayout = usePrefersMobileLayout();
  const isPhoneViewport = useMediaQuery('(max-width: 576px)');
  const isFullBleedMobile = isPhoneViewport;
  const setChatMobileNavHidden = useSetRecoilState(store.chatMobileNavHiddenState);
  const detail = preview?.detail ?? null;
  const fileName = getCitationDocumentName(detail);
  const [resolvedRawFileUrl, setResolvedRawFileUrl] = useState(() => getCitationDocumentUrl(detail));
  const fileUrl = toAbsolutePreviewUrl(resolvedRawFileUrl);
  const canRenderPreview = !!preview && isRagCitation(preview.detail);

  useEffect(() => {
    if (!canRenderPreview || !isNarrowLayout) return;

    const originalBodyOverflow = document.body.style.overflow;
    const originalHtmlOverflow = document.documentElement.style.overflow;
    document.body.style.overflow = 'hidden';
    document.documentElement.style.overflow = 'hidden';

    return () => {
      document.body.style.overflow = originalBodyOverflow;
      document.documentElement.style.overflow = originalHtmlOverflow;
    };
  }, [canRenderPreview, isNarrowLayout]);

  useEffect(() => {
    if (!canRenderPreview || !isNarrowLayout || !isFullBleedMobile) return;
    setChatMobileNavHidden(true);
    return () => {
      setChatMobileNavHidden(false);
    };
  }, [canRenderPreview, isNarrowLayout, isFullBleedMobile, setChatMobileNavHidden]);

  useEffect(() => {
    let active = true;
    const nextRawFileUrl = getCitationDocumentUrl(detail);
    setResolvedRawFileUrl(nextRawFileUrl);

    if (nextRawFileUrl) {
      return () => {
        active = false;
      };
    }

    if (!detail || !isRagCitation(detail)) {
      return () => {
        active = false;
      };
    }

    void resolveCitationDocumentUrl(detail).then((nextUrl) => {
      if (!active) return;
      setResolvedRawFileUrl(nextUrl || '');
    });

    return () => {
      active = false;
    };
  }, [detail]);

  if (!canRenderPreview) {
    return null;
  }

  const handleDownload = async () => {
    const nextFileUrl = toAbsolutePreviewUrl(resolvedRawFileUrl || await resolveCitationDocumentUrl(detail));
    setResolvedRawFileUrl((current) => current || nextFileUrl);
    if (!nextFileUrl) return;
    const link = document.createElement('a');
    link.href = nextFileUrl;
    link.download = fileName;
    link.target = '_blank';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const drawer = (
    <aside
      className={cn(
        'fixed flex flex-col bg-white',
        isFullBleedMobile && 'z-[120] inset-0 overflow-hidden overscroll-contain touch-pan-y',
        !isFullBleedMobile &&
        'z-[121] inset-y-0 right-0 w-[min(520px,calc(100vw-24px))] border-l border-[#E5E6EB] shadow-[0_8px_28px_rgba(0,0,0,0.16)]',
      )}
      aria-label="文档预览"
      onClick={(event) => event.stopPropagation()}
      onPointerDown={(event) => event.stopPropagation()}
    >
      <div
        className={cn(
          'flex shrink-0 items-center justify-between border-b border-[#F2F3F5]',
          isFullBleedMobile && 'h-11 px-2 pt-[env(safe-area-inset-top,0px)]',
          !isFullBleedMobile && 'h-10 px-4',
        )}
      >
        <div className="flex min-w-0 items-center gap-2">
          {(!isNarrowLayout || isFullBleedMobile) && <FileText className="size-4 shrink-0 text-[#165DFF]" />}
          <h2
            className={cn(
              'min-w-0 truncate font-semibold text-[#1D2129]',
              isNarrowLayout ? 'text-[14px] leading-5' : 'text-[16px] leading-6',
            )}
            title={fileName}
          >
            {fileName}
          </h2>
          {isNarrowLayout && (
            <button
              type="button"
              onClick={handleDownload}
              disabled={!fileUrl}
              className={cn(
                'shrink-0 items-center justify-center text-[#86909C] hover:bg-[#F2F3F5] hover:text-[#335CFF] disabled:cursor-not-allowed disabled:text-[#C9CDD4]',
                isFullBleedMobile
                  ? 'inline-flex size-8 rounded-md'
                  : 'inline-flex size-6 rounded-[6px]',
              )}
              aria-label={localize("com_knowledge.download_file")}
            >
              <Download className="size-4" />
            </button>
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          className={cn(
            'items-center justify-center text-[#A9AEB8] hover:bg-[#F2F3F5] hover:text-[#4E5969]',
            isFullBleedMobile
              ? 'inline-flex size-8 rounded-md'
              : 'inline-flex size-6 rounded-[6px]',
          )}
          aria-label="关闭文档预览"
        >
          <X className="size-4" strokeWidth={1.5} />
        </button>
      </div>

      <div
        className={cn(
          'min-h-0 flex-1 overflow-y-auto overscroll-contain [-webkit-overflow-scrolling:touch]',
        )}
      >
        <CitationDocumentPreviewContent preview={preview} compactMode={isNarrowLayout} />
      </div>
    </aside>
  );

  if (isFullBleedMobile) {
    return drawer;
  }

  return (
    <div className="pointer-events-none fixed inset-0 z-[120]">
      <button
        type="button"
        aria-label="关闭文档预览"
        className="absolute inset-0 z-0 pointer-events-auto bg-transparent"
        onClick={onClose}
      />
      {drawer}
    </div>
  );
}
