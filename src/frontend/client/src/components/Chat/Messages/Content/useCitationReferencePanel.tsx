import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import useMediaQuery from '~/hooks/useMediaQuery';
import usePrefersMobileLayout from '~/hooks/usePrefersMobileLayout';
import { cn } from '~/utils';
import CitationDocumentPreviewDrawer from './CitationDocumentPreviewDrawer';
import CitationReferencesDrawer, { type CitationReferencesDesktopPayload } from './CitationReferencesDrawer';

const CITATION_BROWSER_SMALL_BREAKPOINT = 768;

type UseCitationReferencePanelOptions = {
  hasMessages: boolean;
};

export function useCitationReferencePanel({ hasMessages }: UseCitationReferencePanelOptions) {
  const isH5 = usePrefersMobileLayout();
  const isCitationMobile = isH5;
  const isPhoneViewport = useMediaQuery('(max-width: 576px)');
  // 与 768px 断点对齐：避免恰好 768 宽仍走 fixed 全屏遮罩层叠在内容标题上
  const useInlineCitationPanel = useMediaQuery(`(min-width: ${CITATION_BROWSER_SMALL_BREAKPOINT}px)`);
  /** 768–1023：flex 内联会与 HeaderTitle / 主布局层叠上下文交错，标题被挡；改为挂 body 的 fixed 抽屉 */
  const usePortaledInlineCitationPanel = useMediaQuery('(max-width: 1023px)');
  const useExpandedCitationPanel = useInlineCitationPanel;
  const [citationPanelPayload, setCitationPanelPayload] = useState<CitationReferencesDesktopPayload | null>(null);
  const [citationPanelOpen, setCitationPanelOpen] = useState(false);
  const [inlineCitationPortalReady, setInlineCitationPortalReady] = useState(false);
  // Tracks the active view inside CitationReferencesDrawer so we can widen the
  // outer container when the user opens a document preview inside the panel.
  const [panelView, setPanelView] = useState<'list' | 'document-preview'>('list');
  const isDocumentPreview = panelView === 'document-preview';
  const widthTransitionClass = 'transition-[width] duration-200 ease-out';
  const citationPanelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setInlineCitationPortalReady(true);
  }, []);

  useEffect(() => {
    if (!citationPanelOpen) {
      setPanelView('list');
    }
  }, [citationPanelOpen]);

  useEffect(() => {
    setPanelView('list');
  }, [citationPanelPayload?.messageId]);

  const handleCloseCitationPanel = useCallback(() => {
    setCitationPanelOpen(false);
  }, []);

  const handleOpenCitationPanel = useCallback((payload: CitationReferencesDesktopPayload) => {
    if (isCitationMobile) {
      return;
    }

    setCitationPanelPayload(payload);
    setCitationPanelOpen(true);
  }, [isCitationMobile]);

  useEffect(() => {
    if (!hasMessages) {
      setCitationPanelOpen(false);
    }
  }, [hasMessages]);

  useEffect(() => {
    if (!citationPanelOpen || (isH5 && isPhoneViewport)) {
      return;
    }

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as HTMLElement | null;
      if (!target) {
        return;
      }

      if (citationPanelRef.current?.contains(target)) {
        return;
      }

      if (target.closest('[data-citation-popover-surface]')) {
        return;
      }

      if (target.closest('[data-citation-references-trigger="true"]')) {
        return;
      }

      if (target.closest('[data-citation-trigger="true"]')) {
        return;
      }

      handleCloseCitationPanel();
    };

    document.addEventListener('pointerdown', handlePointerDown);
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown);
    };
  }, [citationPanelOpen, handleCloseCitationPanel, isH5, isPhoneViewport]);

  const citationPanelContent = (
    <CitationReferencesDrawer
      panelOnly
      desktopMode="inline-panel"
      open={citationPanelOpen}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) {
          handleCloseCitationPanel();
        }
      }}
      panelClassName="h-full w-full max-w-none bg-white"
      messageId={citationPanelPayload?.messageId}
      content={citationPanelPayload?.content ?? ''}
      webContent={citationPanelPayload?.webContent}
      citations={citationPanelPayload?.citations}
      referenceItems={citationPanelPayload?.referenceItems ?? []}
      initialDocumentPreview={citationPanelPayload?.initialDocumentPreview}
      desktopPreviewVariant="standard"
      onDesktopViewChange={setPanelView}
    />
  );

  const citationPanelElement = useMemo(() => {
    if (!citationPanelOpen || !citationPanelPayload) {
      return null;
    }

    if (isCitationMobile) {
      if (citationPanelPayload.initialDocumentPreview) {
        return (
          <CitationDocumentPreviewDrawer
            preview={citationPanelPayload.initialDocumentPreview}
            onClose={handleCloseCitationPanel}
          />
        );
      }

      if (isPhoneViewport) {
        return (
          <div className="fixed inset-0 z-[120] flex h-[100dvh] min-h-0 flex-col overflow-hidden overscroll-contain bg-white">
            {citationPanelContent}
          </div>
        );
      }

      // 固定贴视口右侧全高，z 高于 MobileNav(z-60)，盖住顶栏与圆角卡片上沿（与全屏抽屉视觉一致，不占 flex 宽度）
      return (
        <div
          ref={citationPanelRef}
          data-citation-popover-surface
          className={cn(
            'fixed inset-y-0 right-0 z-[130] flex min-h-0 flex-col overflow-hidden border-l border-[#ECECEC] bg-white shadow-[-8px_0_28px_rgba(0,0,0,0.08)] animate-in slide-in-from-right duration-300',
            'rounded-tl-xl',
            'min-w-[260px] w-[min(520px,42vw)] max-[580px]:min-w-[240px] max-[580px]:w-[min(360px,calc(100vw-40px))]',
          )}
          onClick={(event) => event.stopPropagation()}
          onPointerDown={(event) => event.stopPropagation()}
        >
          {citationPanelContent}
        </div>
      );
    }

    if (useInlineCitationPanel) {
      if (usePortaledInlineCitationPanel && inlineCitationPortalReady) {
        return createPortal(
          <div
            ref={citationPanelRef}
            data-citation-popover-surface
            className={cn(
              'fixed inset-y-0 right-0 z-[150] flex min-h-0 flex-col overflow-hidden border-l border-[#ECECEC] bg-white shadow-[-8px_0_28px_rgba(0,0,0,0.1)] animate-in slide-in-from-right duration-300',
              'rounded-tl-xl',
              widthTransitionClass,
              isDocumentPreview
                ? 'w-[min(640px,calc(100vw-24px))]'
                : useExpandedCitationPanel ? 'w-[min(480px,100vw)]' : 'w-[min(360px,100vw)]',
            )}
            onClick={(event) => event.stopPropagation()}
            onPointerDown={(event) => event.stopPropagation()}
          >
            {citationPanelContent}
          </div>,
          document.body,
        );
      }

      if (usePortaledInlineCitationPanel && !inlineCitationPortalReady) {
        return null;
      }

      return (
        <div
          ref={citationPanelRef}
          data-citation-popover-surface
          className={cn(
            'flex h-full min-w-0 shrink-0 border-l border-[#ECECEC] bg-white animate-in slide-in-from-right duration-300',
            widthTransitionClass,
            // Preview mode: wide for readability, leave ~560px for chat column on smaller screens
            isDocumentPreview
              ? 'w-[clamp(480px,calc(100vw-560px),640px)]'
              : useExpandedCitationPanel ? 'w-[480px]' : 'w-[360px]',
          )}
        >
          <CitationReferencesDrawer
            panelOnly
            desktopMode="inline-panel"
            open={citationPanelOpen}
            onOpenChange={(nextOpen) => {
              if (!nextOpen) {
                handleCloseCitationPanel();
              }
            }}
            panelClassName="w-full"
            messageId={citationPanelPayload.messageId}
            content={citationPanelPayload.content}
            webContent={citationPanelPayload.webContent}
            citations={citationPanelPayload.citations}
            referenceItems={citationPanelPayload.referenceItems}
            initialDocumentPreview={citationPanelPayload.initialDocumentPreview}
            onDesktopViewChange={setPanelView}
          />
        </div>
      );
    }

    return (
      <div className="pointer-events-none fixed inset-0 z-[130] flex justify-end">
        <button
          type="button"
          aria-label="关闭参考资料浮层"
          className="absolute inset-0 z-0 pointer-events-auto bg-transparent"
          onClick={handleCloseCitationPanel}
        />
        <div
          ref={citationPanelRef}
          data-citation-popover-surface
          className={cn(
            'relative z-10 flex min-h-0 min-w-0 flex-col bg-white pointer-events-auto shadow-[0_8px_24px_rgba(0,0,0,0.12)] animate-in slide-in-from-right duration-300 [height:100dvh]',
            widthTransitionClass,
            isDocumentPreview
              ? 'w-[min(640px,calc(100vw-24px))]'
              : 'w-[min(520px,calc(100vw-24px))]',
          )}
          onClick={(event) => event.stopPropagation()}
          onPointerDown={(event) => event.stopPropagation()}
        >
          <CitationReferencesDrawer
            panelOnly
            desktopMode="inline-panel"
            open={citationPanelOpen}
            onOpenChange={(nextOpen) => {
              if (!nextOpen) {
                handleCloseCitationPanel();
              }
            }}
            panelClassName="h-full w-full max-w-none bg-white"
            messageId={citationPanelPayload.messageId}
            content={citationPanelPayload.content}
            webContent={citationPanelPayload.webContent}
            citations={citationPanelPayload.citations}
            referenceItems={citationPanelPayload.referenceItems}
            initialDocumentPreview={citationPanelPayload.initialDocumentPreview}
            desktopPreviewVariant="standard"
            onDesktopViewChange={setPanelView}
          />
        </div>
      </div>
    );
  }, [
    citationPanelOpen,
    citationPanelPayload,
    handleCloseCitationPanel,
    inlineCitationPortalReady,
    isCitationMobile,
    isDocumentPreview,
    isPhoneViewport,
    useExpandedCitationPanel,
    useInlineCitationPanel,
    usePortaledInlineCitationPanel,
  ]);

  return {
    activeCitationMessageId: citationPanelOpen ? citationPanelPayload?.messageId ?? null : null,
    citationPanelElement,
    onOpenCitationPanel: handleOpenCitationPanel,
  };
}
