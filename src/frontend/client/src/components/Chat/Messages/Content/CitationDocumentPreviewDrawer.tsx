// @ts-strict-ignore
import { Outlined } from 'bisheng-icons';
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useSetRecoilState } from 'recoil';
import type { ChatCitation } from '~/api/chatApi';
import { useLocalize, useMediaQuery, usePrefersMobileLayout } from '~/hooks';
import store from '~/store';
import FilePreview from '~/pages/knowledge/FilePreview';
import { cn } from '~/utils';
import {
  getCitationDocumentFileType,
  getCitationDocumentName,
  getCitationItemBBoxes,
  isMediaCitation,
  isRagCitation,
  resolveCitationDocumentUrls,
  resolveCitationDownloadUrl,
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
  manageMobileNavVisibility?: boolean;
  /**
   * Park the drawer this many pixels in from the right edge, next to an open
   * references list instead of on top of it. Null keeps the right edge.
   */
  pairedRightOffsetPx?: number | null;
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
  const isMedia = isMediaCitation(detail);
  const [resolvedUrls, setResolvedUrls] = useState<{ originalUrl: string; previewUrl: string }>({
    originalUrl: '',
    previewUrl: '',
  });
  const [isResolvingFileUrl, setIsResolvingFileUrl] = useState(false);
  // A clip renders from the original file (the player) with its transcript
  // alongside; everything else renders from the derived preview.
  const rawViewerUrl = isMedia
    ? resolvedUrls.originalUrl || resolvedUrls.previewUrl
    : resolvedUrls.previewUrl || resolvedUrls.originalUrl;
  const fileType = canRenderPreview ? resolveFileType(detail as ChatCitation, rawViewerUrl) : '';
  const fileUrl = toAbsolutePreviewUrl(rawViewerUrl);
  const transcriptUrl = isMedia ? toAbsolutePreviewUrl(resolvedUrls.previewUrl) : '';
  const shouldLocateChunk = !!locateChunk && fileType === 'pdf';
  const bboxes: CitationPdfBBox[] = shouldLocateChunk
    ? getCitationItemBBoxes(detail as ChatCitation, itemId)
    : [];
  const targetBBox = bboxes[0] ?? null;

  useEffect(() => {
    let active = true;
    setResolvedUrls({ originalUrl: '', previewUrl: '' });

    if (!canRenderPreview || !detail) {
      setIsResolvingFileUrl(false);
      return () => {
        active = false;
      };
    }

    setIsResolvingFileUrl(true);
    void resolveCitationDocumentUrls(detail as ChatCitation).then((nextUrls) => {
      if (!active) return;
      setResolvedUrls(nextUrls);
      setIsResolvingFileUrl(false);
    });

    return () => {
      active = false;
    };
  }, [canRenderPreview, detail]);

  if (!canRenderPreview) {
    return null;
  }

  return (
    <div className={cn('flex h-full min-h-0 flex-1 flex-col', className)}>
      {fileUrl ? (
        <FilePreview
          fileName={fileName}
          fileType={fileType}
          fileUrl={fileUrl}
          transcriptUrl={transcriptUrl}
          highlightBboxes={bboxes}
          targetBBox={targetBBox}
          compactMode={compactMode}
        />
      ) : isResolvingFileUrl ? (
        <div className="flex h-full items-center justify-center text-[14px] text-text-3">
          正在加载文件预览...
        </div>
      ) : (
        <div className="flex h-full items-center justify-center text-[14px] text-text-3">
          暂无可预览文件地址
        </div>
      )}
    </div>
  );
}

export default function CitationDocumentPreviewDrawer({
  preview,
  onClose,
  manageMobileNavVisibility = true,
  pairedRightOffsetPx = null,
}: CitationDocumentPreviewDrawerProps) {
  const localize = useLocalize();
  const isNarrowLayout = usePrefersMobileLayout();
  const isPhoneViewport = useMediaQuery('(max-width: 576px)');
  const isFullBleedMobile = isPhoneViewport;
  const setChatMobileNavHidden = useSetRecoilState(store.chatMobileNavHiddenState);
  const detail = preview?.detail ?? null;
  const fileName = getCitationDocumentName(detail);
  // Download always hands back the file the user uploaded, never the derived
  // preview — otherwise a clip downloads as its transcript under an .mp4 name.
  const [resolvedRawFileUrl, setResolvedRawFileUrl] = useState('');
  const fileUrl = toAbsolutePreviewUrl(resolvedRawFileUrl);
  const canRenderPreview = !!preview && isRagCitation(preview.detail);
  // Declared, not merely referenced: the outside-click handler below reads it, so
  // without it every pointerdown threw instead of dismissing the preview.
  const drawerRef = useRef<HTMLElement | null>(null);
  const isPaired = pairedRightOffsetPx != null && !isFullBleedMobile;
  // The references panel portals itself to <body>. A document rendered inside the
  // message tree can never sit above it reliably, whatever z-index it carries, so
  // it went under the very list that opened it. Both citation entry points render
  // this drawer, so the escape is unconditional rather than tied to the
  // side-by-side layout.
  const shouldPortal = !isFullBleedMobile;

  useEffect(() => {
    if (!canRenderPreview || !isFullBleedMobile) return;

    const originalBodyOverflow = document.body.style.overflow;
    const originalHtmlOverflow = document.documentElement.style.overflow;
    document.body.style.overflow = 'hidden';
    document.documentElement.style.overflow = 'hidden';

    return () => {
      document.body.style.overflow = originalBodyOverflow;
      document.documentElement.style.overflow = originalHtmlOverflow;
    };
  }, [canRenderPreview, isFullBleedMobile]);

  useEffect(() => {
    if (!manageMobileNavVisibility || !canRenderPreview || !isNarrowLayout || !isFullBleedMobile) return;
    setChatMobileNavHidden(true);
    return () => {
      setChatMobileNavHidden(false);
    };
  }, [canRenderPreview, isFullBleedMobile, isNarrowLayout, manageMobileNavVisibility, setChatMobileNavHidden]);

  useEffect(() => {
    if (!canRenderPreview || isFullBleedMobile) return;

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (!target || drawerRef.current?.contains(target)) return;
      // Don't collapse the preview when clicking the citation marker or its
      // hover popover card — those re-drive the preview, not dismiss it.
      const el = target instanceof Element ? target : (target as any)?.parentElement;
      if (el?.closest?.('[data-citation-trigger="true"]')) return;
      if (el?.closest?.('[data-citation-popover-surface]')) return;
      onClose();
    };

    document.addEventListener('pointerdown', handlePointerDown, true);
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown, true);
    };
  }, [canRenderPreview, isFullBleedMobile, onClose]);

  useEffect(() => {
    let active = true;
    setResolvedRawFileUrl('');

    if (!detail || !isRagCitation(detail)) {
      return () => {
        active = false;
      };
    }

    void resolveCitationDownloadUrl(detail).then((nextUrl) => {
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
    const nextFileUrl = toAbsolutePreviewUrl(resolvedRawFileUrl || await resolveCitationDownloadUrl(detail));
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
      ref={drawerRef}
      data-citation-popover-surface
      className={cn(
        'fixed flex flex-col bg-white',
        isFullBleedMobile && 'z-[120] inset-0 overflow-hidden overscroll-contain touch-pan-y',
        !isFullBleedMobile &&
          'z-[140] inset-y-0 border-l border-border-base shadow-[0_8px_28px_rgba(0,0,0,0.16)]',
        // Paired: parked left of the references list and narrowed so both fit.
        // Otherwise it owns the right edge on its own, as before.
        isPaired && 'w-[min(520px,calc(100vw-384px))]',
        !isFullBleedMobile && !isPaired && 'right-0 w-[min(520px,calc(100vw-24px))]',
      )}
      style={isPaired ? { right: `${pairedRightOffsetPx}px` } : undefined}
      aria-label="文档预览"
      onClick={(event) => event.stopPropagation()}
      onPointerDown={(event) => event.stopPropagation()}
    >
      <div
        className={cn(
          'flex shrink-0 items-center justify-between border-b border-fill-2',
          // Symmetric vertical padding so icon/title/actions sit centered in the bar; safe-area only on top.
          isFullBleedMobile &&
            'px-4 pb-4 pt-[calc(env(safe-area-inset-top,0px)+16px)]',
          !isFullBleedMobile && 'px-4 py-4',
        )}
      >
        <div className="flex min-w-0 items-center gap-2">
          {(!isNarrowLayout || isFullBleedMobile) && <Outlined.File className="size-4 shrink-0 text-blue-500" />}
          <h2
            className={cn(
              'min-w-0 truncate font-semibold text-text-1',
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
                'shrink-0 items-center justify-center text-text-3 hover:bg-fill-2 hover:text-blue-500 disabled:cursor-not-allowed disabled:text-text-4',
                isFullBleedMobile
                  ? 'inline-flex size-8 rounded-md'
                  : 'inline-flex size-6 rounded-md',
              )}
              aria-label={localize("com_knowledge.download_file")}
            >
              <Outlined.Download className="size-4" />
            </button>
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          className={cn(
            'items-center justify-center text-[#A9AEB8] hover:bg-fill-2 hover:text-text-2',
            isFullBleedMobile
              ? 'inline-flex size-8 rounded-md'
              : 'inline-flex size-6 rounded-md',
          )}
          aria-label="关闭文档预览"
        >
          <Outlined.Close className="size-4" strokeWidth={1.5} />
        </button>
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden overscroll-contain [-webkit-overflow-scrolling:touch]">
        <CitationDocumentPreviewContent preview={preview} compactMode={isNarrowLayout} />
      </div>
    </aside>
  );

  if (isFullBleedMobile) {
    return drawer;
  }

  return shouldPortal ? createPortal(drawer, document.body) : drawer;
}
