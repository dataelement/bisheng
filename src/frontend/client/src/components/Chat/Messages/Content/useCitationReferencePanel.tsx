import { useCallback, useEffect, useMemo, useState } from 'react';
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

  useEffect(() => {
    setInlineCitationPortalReady(true);
  }, []);

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
      panelClassName="h-full w-full max-w-none bg-[#FBFBFB]"
      messageId={citationPanelPayload?.messageId}
      content={citationPanelPayload?.content ?? ''}
      webContent={citationPanelPayload?.webContent}
      citations={citationPanelPayload?.citations}
      referenceItems={citationPanelPayload?.referenceItems ?? []}
      initialDocumentPreview={citationPanelPayload?.initialDocumentPreview}
      desktopPreviewVariant="standard"
    />
  );

  const citationPanelElement = useMemo(() => {
    // ≥1024: in-flow docked panel that stays mounted, so open/close animates its
    // width + opacity + padding with the same easing as the task-mode workspace
    // docked card — instead of a hard mount/unmount with a one-way slide-in.
    // overflow-hidden clips the content while the inner box keeps a min-width, so
    // it slides/clips rather than reflowing as the panel collapses.
    const isInlineFlowPanel =
      useInlineCitationPanel && !usePortaledInlineCitationPanel && !isCitationMobile;
    if (isInlineFlowPanel) {
      const inlineOpen = citationPanelOpen && !!citationPanelPayload;
      return (
        <div
          className={cn(
            'min-h-0 shrink-0 overflow-hidden transition-[width,opacity,padding] duration-300 ease-[cubic-bezier(0.32,0.72,0,1)]',
            inlineOpen ? 'p-1 opacity-100' : 'pointer-events-none p-0 opacity-0',
          )}
          style={{ width: inlineOpen ? (useExpandedCitationPanel ? '480px' : '360px') : '0px' }}
        >
          {citationPanelPayload && (
            <div
              data-citation-popover-surface
              // min-w must stay below the p-1 content width (panel width − 8px), or
              // the inner box overflows and overflow-hidden clips the right gutter.
              className={cn('h-full', useExpandedCitationPanel ? 'min-w-[472px]' : 'min-w-[352px]')}
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
                panelClassName="h-full w-full overflow-hidden rounded-[12px] border border-[#ECECEC] bg-[#FBFBFB]"
                messageId={citationPanelPayload.messageId}
                content={citationPanelPayload.content}
                webContent={citationPanelPayload.webContent}
                citations={citationPanelPayload.citations}
                referenceItems={citationPanelPayload.referenceItems}
                initialDocumentPreview={citationPanelPayload.initialDocumentPreview}
              />
            </div>
          )}
        </div>
      );
    }

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

    // 768–1023: portaled fixed overlay (≥1024 in-flow handled above).
    if (useInlineCitationPanel) {
      if (!inlineCitationPortalReady) {
        return null;
      }
      return createPortal(
        <div
          data-citation-popover-surface
          className={cn(
            'fixed inset-y-0 right-0 z-[150] flex min-h-0 flex-col overflow-hidden border-l border-[#ECECEC] bg-white shadow-[-8px_0_28px_rgba(0,0,0,0.1)] animate-in slide-in-from-right duration-300',
            'rounded-tl-xl',
            useExpandedCitationPanel ? 'w-[min(480px,100vw)]' : 'w-[min(360px,100vw)]',
          )}
          onClick={(event) => event.stopPropagation()}
          onPointerDown={(event) => event.stopPropagation()}
        >
          {citationPanelContent}
        </div>,
        document.body,
      );
    }

    return (
      <div className="pointer-events-none fixed inset-0 z-[130] flex justify-end">
        <div
          data-citation-popover-surface
          className={cn(
            'relative z-10 flex min-h-0 min-w-0 flex-col bg-white pointer-events-auto shadow-[0_8px_24px_rgba(0,0,0,0.12)] animate-in slide-in-from-right duration-300 [height:100dvh]',
            'w-[min(520px,calc(100vw-24px))]',
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
            panelClassName="h-full w-full max-w-none bg-[#FBFBFB]"
            messageId={citationPanelPayload.messageId}
            content={citationPanelPayload.content}
            webContent={citationPanelPayload.webContent}
            citations={citationPanelPayload.citations}
            referenceItems={citationPanelPayload.referenceItems}
            initialDocumentPreview={citationPanelPayload.initialDocumentPreview}
            desktopPreviewVariant="standard"
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
