import { useEffect,useRef,useState } from 'react';
import { createPortal } from 'react-dom';
import { Outlined } from 'bisheng-icons';
import { Badge } from '@bisheng/ui';
import cn from '@bisheng/ui/cn';
import type { ChatCitation, CitationReferenceItem, CitationDocumentPreviewState, CitationReferencesDesktopPayload } from './types';
import type { CitationViewProps } from './viewTypes';
import { createCitationUtilities } from './preview';
import { CitationReferenceCard,splitDocumentTitle } from './CitationReferenceCard';
import { CitationDocumentPreviewDrawer } from './CitationDocumentPreviewDrawer';
import { CitationDocumentPreview } from './CitationDocumentPreview';
import { CitationSourceIconStack,createCitationIconUtilities } from './CitationSourceIcon';
import { useCitationReferences } from './useCitationReferences';
import { useCitationPreview } from './useCitationPreview';
import { useCitationMediaQuery } from './useCitationMediaQuery';
export interface CitationReferencesProps extends CitationViewProps {
  content: string;
  allowRemoteResolve?:boolean;
  webContent?: unknown;
  citations?: ChatCitation[] | null;
  referenceItems?: CitationReferenceItem[];
  buttonClassName?: string;
  actionButtons?: React.ReactNode;
  messageId?: string;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  desktopMode?: 'inline-panel' | 'overlay';
  onDesktopOpen?: (payload: CitationReferencesDesktopPayload) => void;
  panelOnly?: boolean;
  panelClassName?: string;
  initialDocumentPreview?: CitationDocumentPreviewState | null;
  desktopPreviewVariant?: 'auto' | 'standard' | 'expanded';
  /** Notifies parent of inline-panel view changes so the outer container can resize for document preview. */
  onDesktopViewChange?: (view: CitationDesktopView) => void;
}

export type { CitationReferencesDesktopPayload } from './types';
type CitationDesktopView = 'list' | 'document-preview';
const CITATION_PANEL_EXPANDED_BREAKPOINT=768;
export function CitationReferences({
  content,
  services,renderFile,isNarrowLayout=false,onMobileNavVisibility,onUnavailable,allowRemoteResolve=true,
  webContent,
  citations,
  referenceItems,
  buttonClassName,
  actionButtons,
  messageId,
  open,
  onOpenChange,
  desktopMode = 'overlay',
  onDesktopOpen,
  panelOnly = false,
  panelClassName,
  initialDocumentPreview,
  desktopPreviewVariant = 'auto',
  onDesktopViewChange,
}: CitationReferencesProps) {
  const localize=(key:string,options?:Record<string,unknown>)=>services.localize(key.startsWith('shared:')?key:'shared:citations.'+key,options);
  const {getCitationDocumentName}=createCitationUtilities(localize);
  // <=768: use the drawer (no inline split); <=576: drawer covers full screen
  const isPhoneViewport = useCitationMediaQuery('(max-width: 576px)');
  const isFullBleedMobile = isPhoneViewport;
  const isMobileLikeViewport = isNarrowLayout;
  const matchesExpandedDesktopPreview = useCitationMediaQuery(`(min-width: ${CITATION_PANEL_EXPANDED_BREAKPOINT + 1}px)`);
  const useExpandedDesktopPreview = desktopPreviewVariant === 'expanded'
    ? true
    : desktopPreviewVariant === 'standard'
      ? false
      : matchesExpandedDesktopPreview;
  const [internalOpen, setInternalOpen] = useState(false);
  const [documentPreview, setDocumentPreview] = useState<CitationDocumentPreviewState | null>(null);
  const [desktopView, setDesktopView] = useState<CitationDesktopView>('list');
  const [citationOverlayPortalReady, setCitationOverlayPortalReady] = useState(false);

  useEffect(() => {
    setCitationOverlayPortalReady(true);
  }, []);

  const {references,detailMap,loadingMap,errorMap,loadCitationDetail}=useCitationReferences({content,webContent,citations,referenceItems,services,allowRemoteResolve});
  const selectedDocument=useCitationPreview(documentPreview,services);
  const openTicket=useRef(0);
  const live=useRef({scope:services.scopeKey,mounted:true});live.current.scope=services.scopeKey;
  useEffect(()=>{const identity=live.current;const counter=openTicket;identity.mounted=true;return()=>{identity.mounted=false;counter.current++;};},[]);
  const selectionIdentity=JSON.stringify([services.scopeKey,messageId||content,citations?.map(item=>item.citationId)]);
  useEffect(()=>{openTicket.current++;setDocumentPreview(null);setDesktopView('list');},[selectionIdentity]);
  const referenceEntryIcons = createCitationIconUtilities(localize).buildCitationSourceIconStackData(references, detailMap);
  const referenceIconCount = Math.min(referenceEntryIcons.length, 3);
  const referenceButtonWidth = referenceIconCount <= 1 ? 'w-24 min-w-24' : referenceIconCount === 2 ? 'w-[104px] min-w-[104px]' : 'w-28 min-w-28';
  const referenceIconStackWidth = referenceIconCount <= 1 ? 'w-5' : referenceIconCount === 2 ? 'w-7' : 'w-9';
  const isDesktopInlinePanel = !isNarrowLayout
    && desktopMode === 'inline-panel'
    && (panelOnly || !!onDesktopOpen || typeof open === 'boolean' || !!onOpenChange);
  const isOpen = panelOnly ? true : isDesktopInlinePanel ? !!open : internalOpen;
  const isDesktopPreviewInline = isDesktopInlinePanel && desktopView === 'document-preview' && !!documentPreview;

  // Only the full-screen references view (<=576) hides MobileNav; the tablet-width
  // drawer keeps the top bar title, and its z-[120] already sits above MobileNav z-[60].
  useEffect(() => {
    if (!isNarrowLayout || !isOpen || !isFullBleedMobile) {
      return;
    }

    onMobileNavVisibility?.(true);
    return () => {
      onMobileNavVisibility?.(false);
    };
  }, [isFullBleedMobile, isNarrowLayout, isOpen, onMobileNavVisibility]);

  useEffect(() => {
    if (!isOpen && !panelOnly) {
      setDesktopView('list');
      setDocumentPreview(null);
    }
  }, [isOpen, panelOnly]);

  useEffect(() => {
    if (!isDesktopInlinePanel) return;
    onDesktopViewChange?.(desktopView);
  }, [desktopView, isDesktopInlinePanel, onDesktopViewChange]);

  useEffect(() => {
    if (!isDesktopInlinePanel || !isOpen) {
      return;
    }

    if (initialDocumentPreview?.detail) {
      setDocumentPreview(initialDocumentPreview);
      setDesktopView('document-preview');
      return;
    }

    setDesktopView('list');
    setDocumentPreview(null);
  }, [initialDocumentPreview, isDesktopInlinePanel, isOpen]);

  const setOpenState = (nextOpen: boolean) => {
    if (!nextOpen) {
      openTicket.current++;
      setDesktopView('list');
      setDocumentPreview(null);
    }
    if (isDesktopInlinePanel) {
      onOpenChange?.(nextOpen);
      return;
    }

    setInternalOpen(nextOpen);
  };
  const handleOpenButtonClick = () => {
    if (isDesktopInlinePanel) {
      onDesktopOpen?.({
        messageId,
        content,
        webContent,
        citations,
        referenceItems: references,
      });
      onOpenChange?.(true);
      return;
    }

    setOpenState(true);
  };
  const handleOpenDocumentPreview = async (item: CitationReferenceItem, detail: ChatCitation) => {
    const ticket=++openTicket.current;
    const scope=services.scopeKey;
    let latestDetail:ChatCitation|null=detail;
    try { latestDetail = allowRemoteResolve ? await loadCitationDetail(item.data.citationId) : detail; } catch { onUnavailable?.(localize('com_message.source_load_failed')); return; }
    if(ticket!==openTicket.current||!live.current.mounted||live.current.scope!==scope)return;
    if (!latestDetail) {
      return;
    }

    const nextPreview = {
      detail: latestDetail,
      itemId: item.data.itemId,
      itemIds: item.itemIds?.length ? item.itemIds : item.data.itemId ? [item.data.itemId] : undefined,
      locateChunk: true,
    };

    if (isDesktopInlinePanel) {
      setDocumentPreview(nextPreview);
      setDesktopView('document-preview');
      return;
    }

    setDocumentPreview(nextPreview);
  };
  const handleDownloadDocument = async () => {
    if(!selectedDocument.originalUrl){onUnavailable?.(localize('com_citation.no_download_url'));return;}
    try{await selectedDocument.download();}catch{onUnavailable?.(localize('com_citation.no_download_url'));}
  };
  const documentHeaderTitle = documentPreview
    ? splitDocumentTitle(
      getCitationDocumentName(documentPreview.detail),
      documentPreview.detail,
      null,
    )
    : { name: localize('com_message.document_preview'), extension: '' };
  // The "centered reading card" layout (max-w-[464/480]) only makes sense for the
  // citation list. When previewing a document, both header and body fill the
  // panel so they line up flush — capping the header alone leaves the body
  // sticking out wider than the title bar.
  const useReadingCardLayout = useExpandedDesktopPreview && !isDesktopPreviewInline;
  const desktopPanelMaxWidth = useReadingCardLayout ? 'max-w-[480px]' : 'max-w-full';
  // Align the toolbar chrome with the task-mode workspace panel: h-12 bar and
  // 28px (h-7 w-7) gray icon buttons (rounded-lg, hover:bg-gray-100).
  const desktopHeaderHeight = 'h-12';
  const desktopButtonSize = 'h-7 w-7 rounded-lg';
  const desktopButtonIconSize = 'size-4';
  const desktopDownloadButtonClass = 'text-text-3 hover:bg-gray-100';
  const desktopCloseButtonClass = 'text-text-3 hover:bg-gray-100';
  const referenceListContent = (
    <>
      <div
        className={cn(
          // Transparent so the bar sits on the panel's #FBFBFB ground (workspace look).
          'flex shrink-0 items-center justify-between',
          isMobileLikeViewport
            ? cn(
              // Mobile keeps the divider; desktop drops it to match the workspace panel.
              'border-b border-border-base px-4',
              // Vertical: centered in the top bar for both side panel and full screen;
              // full screen keeps the safe area + 16px top, balanced by bottom padding.
              isFullBleedMobile
                ? 'pb-3 pt-[calc(env(safe-area-inset-top,0px)+1rem)]'
                : 'py-3',
            )
            : 'h-12 px-4',
        )}
      >
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <h2 className="truncate text-sm font-medium leading-[22px] text-text-1">
            {localize('com_msg_source_reference')}
          </h2>
          {/* 组件-Badge徽标.md §2 — the standalone number. Neutral panel, so it
              passes its own ink fill instead of Badge's brand default. */}
          <Badge count={references.length} className="shrink-0 bg-text-1/5 text-text-1" />
        </div>
        <button
          type="button"
          onClick={() => setOpenState(false)}
          className={cn(
            'inline-flex shrink-0 items-center justify-center transition-colors',
            isMobileLikeViewport
              ? 'size-8 rounded-md hover:bg-fill-2 hover:text-text-2'
              : 'h-7 w-7 rounded-lg text-text-3 hover:bg-gray-100',
          )}
          aria-label={localize('com_message.source_panel_close')}
        >
          <Outlined.Close className="size-4" />
        </button>
      </div>

      <div
        className={cn(
          'scrollbar-os min-h-0 flex-1 overflow-y-auto overscroll-contain [-webkit-overflow-scrolling:touch] space-y-3',
          // Design: 24px between title bar and list; 16px sides, aligned with the title.
          // Desktop matches the workspace list body padding (px-3 pt-1 pb-4).
          isMobileLikeViewport ? 'px-4 pt-6 pb-4' : 'px-3 pt-1 pb-4',
        )}
      >
        {references.length > 0 ? (
          references.map((item) => {
            const detail = errorMap[item.data.citationId] ? null : detailMap[item.data.citationId] ?? item.detail ?? null;
            return (
              <CitationReferenceCard
                key={item.key}
                localize={localize}
                onOpenArticle={services.openArticle}
                item={item}
                detail={detail}
                isLoading={!!loadingMap[item.data.citationId]}
                hasError={!!errorMap[item.data.citationId]}
                onOpenDocumentPreview={handleOpenDocumentPreview}
              />
            );
          })
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-text-3">
            {localize('com_message.source_empty')}
          </div>
        )}
      </div>
    </>
  );

  const documentPreviewContent = (
    <div className="flex min-h-0 w-full flex-1 flex-col overflow-hidden bg-[#FBFBFB]">
      {/* preview toolbar — mirrors the task-mode workspace file-detail toolbar
          (h-12, px-3, gray icon buttons). FilePreview remains the body so PDF
          citations keep their chunk-locating highlight. */}
      <div className={cn('flex w-full min-w-0 shrink-0 items-center gap-2 px-4', desktopHeaderHeight)}>
        <button
          type="button"
          onClick={() => {
            setDesktopView('list');
            setDocumentPreview(null);
          }}
          className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-text-3 transition-colors hover:bg-gray-100"
          aria-label={localize('com_message.source_panel_back')}
        >
          <Outlined.ArrowLeft className="size-4" />
        </button>
        <div className="flex min-w-0 flex-1 items-center">
          <h2
            className="truncate text-sm font-medium leading-[22px] text-text-1"
            title={documentPreview ? getCitationDocumentName(documentPreview.detail) : ''}
          >
            {documentHeaderTitle.name}
          </h2>
          {documentHeaderTitle.extension ? (
            <span className="shrink-0 text-sm font-medium leading-[22px] text-text-1">
              {documentHeaderTitle.extension}
            </span>
          ) : null}
        </div>
        <button
          type="button"
          onClick={handleDownloadDocument}
          className={cn(
            'inline-flex shrink-0 items-center justify-center transition-colors',
            desktopButtonSize,
            desktopDownloadButtonClass,
          )}
          aria-label={localize('com_message.source_panel_download')}
        >
          <Outlined.Download className="size-4" strokeWidth={1.75} />
        </button>
        <button
          type="button"
          onClick={() => setOpenState(false)}
          className={cn(
            'inline-flex shrink-0 items-center justify-center transition-colors',
            desktopButtonSize,
            desktopCloseButtonClass,
          )}
          aria-label={localize('com_message.source_panel_close')}
        >
          <Outlined.Close className={desktopButtonIconSize} />
        </button>
      </div>
      {/* preview body — fills the panel like the workspace preview */}
      <div className="flex min-h-0 w-full flex-1 flex-col overflow-hidden">
        <CitationDocumentPreview preview={documentPreview} services={services} renderFile={renderFile} compactMode />
      </div>
    </div>
  );

  const panelContent = isDesktopPreviewInline ? documentPreviewContent : referenceListContent;

  if (panelOnly) {
    return (
      <>
        <section
          className={cn('flex h-full min-h-0 flex-col bg-[#FBFBFB]', !isNarrowLayout && `w-full ${desktopPanelMaxWidth}`, panelClassName)}
          aria-label={localize('com_message.source_panel_label')}
        >
          {panelContent}
        </section>
        {!isDesktopInlinePanel && (
          <CitationDocumentPreviewDrawer services={services} renderFile={renderFile} isNarrowLayout={isNarrowLayout} onMobileNavVisibility={onMobileNavVisibility}
            preview={documentPreview}
            onClose={() => {openTicket.current++;setDocumentPreview(null);}}
          />
        )}
      </>
    );
  }

  if (!references.length) {
    if (actionButtons) {
      return (
        <div className={cn('flex h-6 items-center gap-1', buttonClassName)}>
          {actionButtons}
        </div>
      );
    }
    return null;
  }

  return (
    <>
      <div
        className={cn('flex h-6 shrink-0 items-center', actionButtons ? 'w-[196px] gap-3' : 'w-[112px]', buttonClassName)}
      >
        {actionButtons && <div className="flex items-center gap-1">{actionButtons}</div>}
        <button
          type="button"
          data-citation-references-trigger="true"
          onClick={handleOpenButtonClick}
          className={cn(
            'flex h-6 shrink-0 items-center justify-end gap-1 rounded-md bg-transparent px-1 py-0.5 text-text-3 transition-colors hover:bg-[#F7F7F7]',
            referenceButtonWidth,
          )}
        >
          <div className={cn('flex h-5 shrink-0 items-center', referenceIconStackWidth)}>
            <CitationSourceIconStack icons={referenceEntryIcons} />
          </div>
          <div className="flex h-5 w-16 shrink-0 items-center whitespace-nowrap">
            <span className="w-12 whitespace-nowrap text-[12px] font-normal leading-5 text-text-3">{localize('com_message.source_panel_label')}</span>
            <Outlined.Right className="size-4 text-text-3" strokeWidth={1.5} />
          </div>
        </button>
      </div>

      {citationOverlayPortalReady &&
        !isDesktopInlinePanel &&
        isOpen &&
        createPortal(
          isFullBleedMobile ? (
            <aside
              className="fixed inset-0 z-[130] flex min-h-0 flex-col overflow-hidden overscroll-contain bg-white [height:100dvh]"
              aria-label={localize('com_message.source_panel_label')}
            >
              {panelContent}
            </aside>
          ) : (
            <aside
              className={cn(
                'fixed inset-y-0 right-0 z-[130] flex min-h-0 w-[min(520px,calc(100vw-24px))] min-w-0 flex-col overflow-hidden bg-white shadow-[0_8px_24px_rgba(0,0,0,0.12)] animate-in slide-in-from-right duration-300',
                'rounded-tl-lg',
              )}
              aria-label={localize('com_message.source_panel_label')}
              onClick={(event) => event.stopPropagation()}
              onPointerDown={(event) => event.stopPropagation()}
            >
              {panelContent}
            </aside>
          ),
          document.body,
        )}
      {!isDesktopInlinePanel && (
        <CitationDocumentPreviewDrawer services={services} renderFile={renderFile} isNarrowLayout={isNarrowLayout} onMobileNavVisibility={onMobileNavVisibility}
          preview={documentPreview}
          onClose={() => {openTicket.current++;setDocumentPreview(null);}}
          manageMobileNavVisibility={false}
        />
      )}
    </>
  );
}
