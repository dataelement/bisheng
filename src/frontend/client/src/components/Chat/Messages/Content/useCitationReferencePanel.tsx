import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
  const useInlineCitationPanel = useMediaQuery(`(min-width: ${CITATION_BROWSER_SMALL_BREAKPOINT + 1}px)`);
  const useExpandedCitationPanel = useInlineCitationPanel;
  const [citationPanelPayload, setCitationPanelPayload] = useState<CitationReferencesDesktopPayload | null>(null);
  const [citationPanelOpen, setCitationPanelOpen] = useState(false);
  const citationPanelRef = useRef<HTMLDivElement>(null);

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

      return (
        <div
          ref={citationPanelRef}
          data-citation-popover-surface
          className="fixed inset-y-0 right-0 z-[120] flex h-full min-h-0 w-[min(520px,calc(100vw-24px))] min-w-0 flex-col bg-white shadow-[0_8px_24px_rgba(0,0,0,0.12)] animate-in slide-in-from-right duration-300"
          onClick={(event) => event.stopPropagation()}
          onPointerDown={(event) => event.stopPropagation()}
        >
          {citationPanelContent}
        </div>
      );
    }

    if (useInlineCitationPanel) {
      return (
        <div
          ref={citationPanelRef}
          data-citation-popover-surface
          className={cn(
            'flex h-full min-w-0 shrink-0 border-l border-[#ECECEC] bg-white animate-in slide-in-from-right duration-300',
            useExpandedCitationPanel ? 'w-[480px]' : 'w-[360px]',
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
          />
        </div>
      );
    }

    return (
      <div className="pointer-events-none fixed inset-0 z-30 flex justify-end">
        <button
          type="button"
          aria-label="关闭参考资料浮层"
          className="absolute inset-0 z-0 pointer-events-auto bg-transparent"
          onClick={handleCloseCitationPanel}
        />
        <div
          ref={citationPanelRef}
          data-citation-popover-surface
          className="relative z-10 flex h-full w-[min(520px,calc(100vw-24px))] min-w-0 flex-col bg-white pointer-events-auto shadow-[0_8px_24px_rgba(0,0,0,0.12)] animate-in slide-in-from-right duration-300"
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
          />
        </div>
      </div>
    );
  }, [
    citationPanelOpen,
    citationPanelPayload,
    handleCloseCitationPanel,
    isCitationMobile,
    isPhoneViewport,
    useExpandedCitationPanel,
    useInlineCitationPanel,
  ]);

  return {
    activeCitationMessageId: citationPanelOpen ? citationPanelPayload?.messageId ?? null : null,
    citationPanelElement,
    onOpenCitationPanel: handleOpenCitationPanel,
  };
}
