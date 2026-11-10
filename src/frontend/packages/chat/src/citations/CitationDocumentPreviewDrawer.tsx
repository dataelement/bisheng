import { Outlined } from 'bisheng-icons';
import { useEffect,useRef } from 'react';
import cn from '@bisheng/ui/cn';
import { createCitationUtilities } from './preview';
import { useCitationPreview } from './useCitationPreview';
import { CitationPreviewBody } from './CitationDocumentPreview';
import { useCitationMediaQuery } from './useCitationMediaQuery';
import type { CitationDocumentPreviewState } from './types';
import type { CitationViewProps } from './viewTypes';
interface CitationDocumentPreviewDrawerProps extends CitationViewProps { preview:CitationDocumentPreviewState|null;onClose:()=>void;manageMobileNavVisibility?:boolean;showDesktopDownload?:boolean }
export function CitationDocumentPreviewDrawer({
  preview,
  onClose,
  manageMobileNavVisibility = true,showDesktopDownload=false,
  services, renderFile, isNarrowLayout = false, onMobileNavVisibility,
}: CitationDocumentPreviewDrawerProps) {
  const localize=(key:string)=>services.localize(key.startsWith('shared:')?key:'shared:citations.'+key);
  const isPhoneViewport = useCitationMediaQuery('(max-width: 576px)');
  const isFullBleedMobile = isPhoneViewport;
  const drawerRef=useRef<HTMLElement>(null);
  const state=useCitationPreview(preview,services);
  const fileName = state.fileName;
  const fileUrl=state.originalUrl;
  const canRenderPreview = !!preview && createCitationUtilities(services.localize).isFilePreviewCitation(preview.detail);

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
    onMobileNavVisibility?.(true);
    return () => {
      onMobileNavVisibility?.(false);
    };
  }, [canRenderPreview, isFullBleedMobile, isNarrowLayout, manageMobileNavVisibility, onMobileNavVisibility]);

  useEffect(() => {
    if (!canRenderPreview || isFullBleedMobile) return;

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (!target || drawerRef.current?.contains(target)) return;
      // Don't collapse the preview when clicking the citation marker or its
      // hover popover card — those re-drive the preview, not dismiss it.
      const el = target instanceof Element ? target : target.parentElement;
      if (el?.closest?.('[data-citation-trigger="true"]')) return;
      if (el?.closest?.('[data-citation-popover-surface]')) return;
      onClose();
    };

    document.addEventListener('pointerdown', handlePointerDown, true);
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown, true);
    };
  }, [canRenderPreview, isFullBleedMobile, onClose]);

  if (!canRenderPreview) {
    return null;
  }

  const handleDownload = () => { void state.download().catch(() => undefined); };

  const drawer = (
    <aside ref={drawerRef}
      className={cn(
        'fixed flex flex-col bg-white',
        isFullBleedMobile && 'z-[120] inset-0 overflow-hidden overscroll-contain touch-pan-y',
        !isFullBleedMobile &&
        'z-[121] inset-y-0 right-0 w-[min(520px,calc(100vw-24px))] border-l border-border-base shadow-[0_8px_28px_rgba(0,0,0,0.16)]',
      )}
      aria-label={localize('com_citation.document_preview')}
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
          {(isNarrowLayout || showDesktopDownload) && (
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
          aria-label={localize('com_citation.close_document_preview')}
        >
          <Outlined.Close className="size-4" strokeWidth={1.5} />
        </button>
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden overscroll-contain [-webkit-overflow-scrolling:touch]">
        <CitationPreviewBody state={state} renderFile={renderFile} services={services} compactMode={isNarrowLayout} />
      </div>
    </aside>
  );

  if (isFullBleedMobile) {
    return drawer;
  }

  return drawer;
}
