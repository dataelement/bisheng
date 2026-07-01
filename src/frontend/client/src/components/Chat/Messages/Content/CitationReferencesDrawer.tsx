import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Outlined } from 'bisheng-icons';
import { ChevronRight, Download, Loader2 } from 'lucide-react';
import { useSetRecoilState } from 'recoil';
import { getCitationDetail, resolveCitationDetails, type ChatCitation } from '~/api/chatApi';
import { useLocalize, useMediaQuery, usePrefersMobileLayout } from '~/hooks';
import store from '~/store';
import { cn } from '~/utils';
import {
  buildCitationDocumentPreview,
  buildCitationReferenceItems,
  createCitationDetailMap,
  getCitationDocumentFileType,
  getCitationDocumentName,
  getCitationDocumentUrl,
  isRagCitation,
  normalizeCitationType,
  resolveCitationDocumentUrl,
  toAbsolutePreviewUrl,
  type CitationPreview,
  type CitationReferenceItem,
} from './citationUtils';
import CitationDocumentPreviewDrawer, {
  CitationDocumentPreviewContent,
  type CitationDocumentPreviewState,
} from './CitationDocumentPreviewDrawer';
import {
  buildCitationSourceIconStackData,
  CitationSourceIcon,
  CitationSourceIconStack,
} from './CitationSourceIcon';

type CitationReferencesDrawerProps = {
  content: string;
  webContent?: any;
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
};

export type CitationReferencesDesktopPayload = {
  messageId?: string;
  content: string;
  webContent?: any;
  citations?: ChatCitation[] | null;
  referenceItems: CitationReferenceItem[];
  initialDocumentPreview?: CitationDocumentPreviewState | null;
};

type CitationDesktopView = 'list' | 'document-preview';
const CITATION_PANEL_EXPANDED_BREAKPOINT = 768;

function SourceTypeBadge({ preview, type }: { preview: CitationPreview | null; type?: string }) {
  const isWeb = normalizeCitationType(preview?.type || type) === 'web';
  return (
    <div
      className={cn(
        'inline-flex h-[18px] min-w-[16px] items-center justify-center rounded-[6px] px-1 text-[12px] font-normal leading-[18px]',
        isWeb ? 'bg-[#F7F3FF] text-[#7224D9]' : 'bg-blue-50 text-blue-600',
      )}
    >
      {isWeb ? '网页' : '文档'}
    </div>
  );
}

function splitDocumentTitle(title: string, detail: ChatCitation | null, preview: CitationPreview | null) {
  const fileType = String(getCitationDocumentFileType(detail) || preview?.sourceMeta || '')
    .toLowerCase()
    .replace(/^\./, '');

  if (!fileType) {
    return { name: title, extension: '' };
  }

  const normalizedExtension = `.${fileType}`;
  if (title.toLowerCase().endsWith(normalizedExtension)) {
    return {
      name: title.slice(0, title.length - normalizedExtension.length),
      extension: normalizedExtension,
    };
  }

  return { name: title, extension: normalizedExtension };
}

function CitationReferenceCard({
  item,
  detail,
  isLoading,
  hasError,
  onOpenDocumentPreview,
}: {
  item: CitationReferenceItem;
  detail: ChatCitation | null;
  isLoading: boolean;
  hasError: boolean;
  onOpenDocumentPreview: (item: CitationReferenceItem, detail: ChatCitation) => void;
}) {
  const preview = item.legacyPreview ?? buildCitationDocumentPreview(detail, item.data);
  const type = preview?.type || item.data.type;
  const isWeb = normalizeCitationType(type) === 'web';
  const title = preview?.title || '暂无标题';
  const canOpenDocument = !!detail && isRagCitation(detail, type);
  const { name: documentName, extension: documentExtension } = splitDocumentTitle(title, detail, preview);

  const nameRowTextClass =
    'text-[14px] font-normal leading-[22px] text-[#1D2129]';

  return (
    <div className="flex min-h-[92px] flex-col gap-2 rounded-[6px] border border-[#ECECEC] bg-white p-2">
      <div className="flex items-center">
        <SourceTypeBadge preview={preview} type={item.data.type} />
      </div>

      {canOpenDocument ? (
        <button
          type="button"
          onClick={() => onOpenDocumentPreview(item, detail!)}
          className={cn(
            'flex w-full min-w-0 items-center gap-1 rounded-[4px] text-left',
            nameRowTextClass,
            'transition-colors hover:text-blue-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/25',
          )}
          title={title}
        >
          {!isWeb && <CitationSourceIcon detail={detail} preview={preview} type={type} />}
          <div className="min-w-0 flex-1">
            <span className="inline-flex min-w-0 max-w-full items-baseline gap-0.5">
              <span className="min-w-0 flex-1 truncate text-left">{documentName}</span>
              {documentExtension ? <span className="shrink-0">{documentExtension}</span> : null}
            </span>
          </div>
        </button>
      ) : preview?.link ? (
        <a
          href={preview.link}
          target="_blank"
          rel="noreferrer"
          className={cn(
            // Web links are generic external links, not a brand action — pin the
            // hover to a fixed blue (matches the web hover arrow #1B61E6) so it
            // doesn't follow the blue⇄green brand theme.
            'flex w-full min-w-0 items-center gap-1 rounded-[4px] hover:text-[#1B61E6]',
            nameRowTextClass,
          )}
          title={title}
        >
          {!isWeb && <CitationSourceIcon detail={detail} preview={preview} type={type} />}
          <span className="min-w-0 flex-1 truncate">{title}</span>
        </a>
      ) : (
        <div className={cn('flex min-w-0 items-center gap-1', nameRowTextClass)}>
          {!isWeb && <CitationSourceIcon detail={detail} preview={preview} type={type} />}
          <span className="min-w-0 flex-1 truncate" title={title}>
            {title}
          </span>
        </div>
      )}

      {(isLoading || hasError) && <div className="min-h-[20px] text-[12px] leading-5 text-[#4E5969]">
        {isLoading ? (
          <span className="inline-flex items-center gap-2 text-[#86909C]">
            <Loader2 className="size-3.5 animate-spin" />
            加载溯源详情...
          </span>
        ) : hasError ? (
          <span className="text-[#86909C]">溯源详情加载失败</span>
        ) : (
          null
        )}
      </div>}

      <div className="flex min-w-0 items-center gap-1 text-[12px] leading-5 text-[#86909C]">
        {isWeb ? (
          <>
            <div className="flex size-4 shrink-0 items-center justify-center overflow-hidden rounded-full border border-[#ECECEC] bg-white">
              <CitationSourceIcon detail={detail} preview={preview} type={type} />
            </div>
            <span className="truncate">{preview?.sourceName || '网页'}</span>
            {preview?.sourceMeta ? <span className="shrink-0">{preview.sourceMeta}</span> : null}
          </>
        ) : (
          <>
            <CitationSourceIcon detail={detail} preview={preview} type={type} ragIconVariant="knowledge" clipAsCircle={false} />
            <span className="truncate">{preview?.sourceName || '政策文件'}</span>
          </>
        )}
      </div>
    </div>
  );
}

export default function CitationReferencesDrawer({
  content,
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
}: CitationReferencesDrawerProps) {
  const localize = useLocalize();
  // <=768: 走抽屉（不内联分栏）；<=576: 抽屉全屏覆盖
  const isNarrowLayout = usePrefersMobileLayout();
  const isPhoneViewport = useMediaQuery('(max-width: 576px)');
  const isFullBleedMobile = isPhoneViewport;
  const isMobileLikeViewport = isNarrowLayout;
  const matchesExpandedDesktopPreview = useMediaQuery(`(min-width: ${CITATION_PANEL_EXPANDED_BREAKPOINT + 1}px)`);
  const useExpandedDesktopPreview = desktopPreviewVariant === 'expanded'
    ? true
    : desktopPreviewVariant === 'standard'
      ? false
      : matchesExpandedDesktopPreview;
  const [internalOpen, setInternalOpen] = useState(false);
  const [detailMap, setDetailMap] = useState<Record<string, ChatCitation>>(() => createCitationDetailMap(citations));
  const [loadingMap, setLoadingMap] = useState<Record<string, boolean>>({});
  const [errorMap, setErrorMap] = useState<Record<string, boolean>>({});
  const [documentPreview, setDocumentPreview] = useState<CitationDocumentPreviewState | null>(null);
  const [desktopView, setDesktopView] = useState<CitationDesktopView>('list');
  const setChatMobileNavHidden = useSetRecoilState(store.chatMobileNavHiddenState);
  const detailCacheRef = useRef<Record<string, ChatCitation>>({});
  const requestCacheRef = useRef<Record<string, Promise<ChatCitation | null>>>({});
  const batchRequestKeyRef = useRef<string>('');
  const autoResolveAttemptRef = useRef<Set<string>>(new Set());
  const [citationOverlayPortalReady, setCitationOverlayPortalReady] = useState(false);

  useEffect(() => {
    setCitationOverlayPortalReady(true);
  }, []);

  const references = useMemo(
    () => (referenceItems && referenceItems.length > 0
      ? referenceItems
      : buildCitationReferenceItems({ content, webContent, citations })),
    [referenceItems, content, webContent, citations],
  );

  useEffect(() => {
    const nextMap = createCitationDetailMap(citations);
    detailCacheRef.current = {
      ...detailCacheRef.current,
      ...nextMap,
    };
    setDetailMap((current) => ({
      ...current,
      ...nextMap,
    }));
  }, [citations]);

  const shouldResolveCitationDetail = useCallback((citationId?: string, detail?: ChatCitation | null) => {
    if (!citationId || citationId.startsWith('citation:')) {
      return false;
    }
    if (!detail) {
      return true;
    }
    return isRagCitation(detail) && !getCitationDocumentUrl(detail);
  }, []);

  const shouldAutoResolveCitationDetail = useCallback((citationId?: string, detail?: ChatCitation | null) => {
    return !!citationId && !autoResolveAttemptRef.current.has(citationId) && shouldResolveCitationDetail(citationId, detail);
  }, [shouldResolveCitationDetail]);

  useEffect(() => {
    const citationIds = Array.from(new Set(
      references
        .map((item) => item.data.citationId)
        .filter((citationId) => shouldAutoResolveCitationDetail(citationId, detailCacheRef.current[citationId])),
    ));

    if (!citationIds.length) {
      return;
    }

    citationIds.forEach((citationId) => {
      autoResolveAttemptRef.current.add(citationId);
    });

    const requestKey = citationIds.sort().join('|');
    if (batchRequestKeyRef.current === requestKey) {
      return;
    }
    batchRequestKeyRef.current = requestKey;

    void resolveCitationDetails(citationIds)
      .then((items) => {
        const nextMap: Record<string, ChatCitation> = {};
        items.forEach((detail) => {
          if (detail?.citationId) {
            detailCacheRef.current[detail.citationId] = detail;
            nextMap[detail.citationId] = detail;
          }
        });

        if (Object.keys(nextMap).length) {
          setDetailMap((current) => ({
            ...current,
            ...nextMap,
          }));
        }
      })
      .catch((error) => {
        console.error('Failed to resolve citation details:', error);
        batchRequestKeyRef.current = '';
      });
  }, [references, shouldAutoResolveCitationDetail]);

  const loadCitationDetail = useCallback(async (citationId: string) => {
    if (!citationId || citationId.startsWith('citation:')) {
      return null;
    }

    const cachedDetail = detailCacheRef.current[citationId];
    if (cachedDetail && !shouldResolveCitationDetail(citationId, cachedDetail)) {
      return cachedDetail;
    }

    const pendingRequest = requestCacheRef.current[citationId];
    if (pendingRequest) {
      return pendingRequest;
    }

    setLoadingMap((current) => ({ ...current, [citationId]: true }));
    setErrorMap((current) => ({ ...current, [citationId]: false }));

    const request = getCitationDetail(citationId)
      .then((detail) => {
        if (detail?.citationId) {
          detailCacheRef.current[detail.citationId] = detail;
        }
        detailCacheRef.current[citationId] = detail;
        setDetailMap((current) => ({
          ...current,
          [citationId]: detail,
          ...(detail?.citationId ? { [detail.citationId]: detail } : {}),
        }));
        return detail;
      })
      .catch((error) => {
        console.error('Failed to load citation detail:', error);
        setErrorMap((current) => ({ ...current, [citationId]: true }));
        return null;
      })
      .finally(() => {
        delete requestCacheRef.current[citationId];
        setLoadingMap((current) => ({ ...current, [citationId]: false }));
      });

    requestCacheRef.current[citationId] = request;
    return request;
  }, [shouldResolveCitationDetail]);

  useEffect(() => {
    const shouldUseDesktopInlinePanel = !isNarrowLayout
      && desktopMode === 'inline-panel'
      && (panelOnly || !!onDesktopOpen || typeof open === 'boolean' || !!onOpenChange);
    const shouldLoadDetails = panelOnly ? true : shouldUseDesktopInlinePanel ? !!open : internalOpen;
    if (!shouldLoadDetails) {
      return;
    }

    const citationIds = Array.from(new Set(
      references
        .map((item) => item.data.citationId)
        .filter((citationId) => shouldAutoResolveCitationDetail(citationId, detailMap[citationId])),
    ));

    citationIds.forEach((citationId) => {
      autoResolveAttemptRef.current.add(citationId);
      void loadCitationDetail(citationId);
    });
  }, [detailMap, desktopMode, internalOpen, isNarrowLayout, loadCitationDetail, open, panelOnly, references, shouldAutoResolveCitationDetail]);

  const referenceEntryIcons = buildCitationSourceIconStackData(references, detailMap);
  const referenceIconCount = Math.min(referenceEntryIcons.length, 3);
  const referenceButtonWidth = referenceIconCount <= 1 ? 'w-24 min-w-24' : referenceIconCount === 2 ? 'w-[104px] min-w-[104px]' : 'w-28 min-w-28';
  const referenceIconStackWidth = referenceIconCount <= 1 ? 'w-5' : referenceIconCount === 2 ? 'w-7' : 'w-9';
  const isDesktopInlinePanel = !isNarrowLayout
    && desktopMode === 'inline-panel'
    && (panelOnly || !!onDesktopOpen || typeof open === 'boolean' || !!onOpenChange);
  const isOpen = panelOnly ? true : isDesktopInlinePanel ? !!open : internalOpen;
  const isDesktopPreviewInline = isDesktopInlinePanel && desktopView === 'document-preview' && !!documentPreview;

  // 仅全屏参考资料（≤576）隐藏 MobileNav；平板窄屏保留顶栏标题，抽屉 z-[120] 已高于 MobileNav z-[60]
  useEffect(() => {
    if (!isNarrowLayout || !isOpen || !isFullBleedMobile) {
      return;
    }

    setChatMobileNavHidden(true);
    return () => {
      setChatMobileNavHidden(false);
    };
  }, [isFullBleedMobile, isNarrowLayout, isOpen, setChatMobileNavHidden]);

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
    const latestDetail = shouldResolveCitationDetail(item.data.citationId, detail)
      ? await loadCitationDetail(item.data.citationId)
      : detail;

    if (!latestDetail) {
      return;
    }

    const nextPreview = {
      detail: latestDetail,
      locateChunk: false,
    };

    if (isDesktopInlinePanel) {
      setDocumentPreview(nextPreview);
      setDesktopView('document-preview');
      return;
    }

    setDocumentPreview(nextPreview);
  };
  const handleDownloadDocument = async () => {
    if (!documentPreview) {
      return;
    }

    const fileName = getCitationDocumentName(documentPreview.detail);
    const fileUrl = toAbsolutePreviewUrl(
      getCitationDocumentUrl(documentPreview.detail) || await resolveCitationDocumentUrl(documentPreview.detail),
    );
    if (!fileUrl) {
      return;
    }

    const link = document.createElement('a');
    link.href = fileUrl;
    link.download = fileName;
    link.target = '_blank';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };
  const documentHeaderTitle = documentPreview
    ? splitDocumentTitle(
      getCitationDocumentName(documentPreview.detail),
      documentPreview.detail,
      null,
    )
    : { name: '文档预览', extension: '' };
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
  const desktopDownloadButtonClass = 'text-[#8C8C8C] hover:bg-gray-100';
  const desktopCloseButtonClass = 'text-[#8C8C8C] hover:bg-gray-100';
  const referenceListContent = (
    <>
      <div
        className={cn(
          // Transparent so the bar sits on the panel's #FBFBFB ground (workspace look).
          'flex shrink-0 items-center justify-between',
          isMobileLikeViewport
            ? cn(
              // Mobile keeps the divider; desktop drops it to match the workspace panel.
              'border-b border-[#ECECEC] px-4',
              // 竖直：侧栏/全屏均在顶栏内垂直居中；全屏保留安全区 + 顶 16px，并加底内边距平衡
              isFullBleedMobile
                ? 'pb-3 pt-[calc(env(safe-area-inset-top,0px)+1rem)]'
                : 'py-3',
            )
            : 'h-12 px-4',
        )}
      >
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <h2 className="truncate text-sm font-medium leading-[22px] text-[#212121]">
            {localize('com_msg_source_reference')}
          </h2>
          <span className="flex h-[18px] min-w-[16px] shrink-0 items-center justify-center rounded-full bg-gray-100 px-1.5 text-[10px] text-[#666]">
            {references.length}
          </span>
        </div>
        <button
          type="button"
          onClick={() => setOpenState(false)}
          className={cn(
            'inline-flex shrink-0 items-center justify-center transition-colors',
            isMobileLikeViewport
              ? 'size-8 rounded-md hover:bg-[#F2F3F5] hover:text-[#4E5969]'
              : 'h-7 w-7 rounded-lg text-[#8C8C8C] hover:bg-gray-100',
          )}
          aria-label="关闭参考资料"
        >
          <Outlined.Close className="size-4" />
        </button>
      </div>

      <div
        className={cn(
          'scrollbar-os min-h-0 flex-1 overflow-y-auto overscroll-contain [-webkit-overflow-scrolling:touch] space-y-3',
          // 设计：标题栏与列表区间距 24px；左右与标题区对齐 16px
          // Desktop matches the workspace list body padding (px-3 pt-1 pb-4).
          isMobileLikeViewport ? 'px-4 pt-6 pb-4' : 'px-3 pt-1 pb-4',
        )}
      >
        {references.length > 0 ? (
          references.map((item) => {
            const detail = detailMap[item.data.citationId] ?? item.detail ?? null;
            return (
              <CitationReferenceCard
                key={item.key}
                item={item}
                detail={detail}
                isLoading={!!loadingMap[item.data.citationId]}
                hasError={!!errorMap[item.data.citationId]}
                onOpenDocumentPreview={handleOpenDocumentPreview}
              />
            );
          })
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-[#86909C]">
            暂无参考资料
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
          className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-[#8C8C8C] transition-colors hover:bg-gray-100"
          aria-label="返回参考资料列表"
        >
          <Outlined.ArrowLeft className="size-4" />
        </button>
        <div className="flex min-w-0 flex-1 items-center">
          <h2
            className="truncate text-sm font-medium leading-[22px] text-[#212121]"
            title={documentPreview ? getCitationDocumentName(documentPreview.detail) : ''}
          >
            {documentHeaderTitle.name}
          </h2>
          {documentHeaderTitle.extension ? (
            <span className="shrink-0 text-sm font-medium leading-[22px] text-[#212121]">
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
          aria-label="下载文档"
        >
          <Download className="size-4" strokeWidth={1.75} />
        </button>
        <button
          type="button"
          onClick={() => setOpenState(false)}
          className={cn(
            'inline-flex shrink-0 items-center justify-center transition-colors',
            desktopButtonSize,
            desktopCloseButtonClass,
          )}
          aria-label="关闭参考资料"
        >
          <Outlined.Close className={desktopButtonIconSize} />
        </button>
      </div>
      {/* preview body — fills the panel like the workspace preview */}
      <div className="flex min-h-0 w-full flex-1 flex-col overflow-hidden">
        <CitationDocumentPreviewContent preview={documentPreview} compactMode />
      </div>
    </div>
  );

  const panelContent = isDesktopPreviewInline ? documentPreviewContent : referenceListContent;

  if (panelOnly) {
    return (
      <>
        <section
          className={cn('flex h-full min-h-0 flex-col bg-[#FBFBFB]', !isNarrowLayout && `w-full ${desktopPanelMaxWidth}`, panelClassName)}
          aria-label="参考资料"
        >
          {panelContent}
        </section>
        {!isDesktopInlinePanel && (
          <CitationDocumentPreviewDrawer
            preview={documentPreview}
            onClose={() => setDocumentPreview(null)}
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
            'flex h-6 shrink-0 items-center justify-end gap-1 rounded-[6px] bg-transparent px-1 py-0.5 text-[#818181] transition-colors hover:bg-[#F7F7F7]',
            referenceButtonWidth,
          )}
        >
          <div className={cn('flex h-5 shrink-0 items-center', referenceIconStackWidth)}>
            <CitationSourceIconStack icons={referenceEntryIcons} />
          </div>
          <div className="flex h-5 w-16 shrink-0 items-center whitespace-nowrap">
            <span className="w-12 whitespace-nowrap text-[12px] font-normal leading-5 text-[#818181]">参考资料</span>
            <ChevronRight className="size-4 text-[#818181]" strokeWidth={1.5} />
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
              aria-label="参考资料"
            >
              {panelContent}
            </aside>
          ) : (
            <aside
              className={cn(
                'fixed inset-y-0 right-0 z-[130] flex min-h-0 w-[min(520px,calc(100vw-24px))] min-w-0 flex-col overflow-hidden bg-white shadow-[0_8px_24px_rgba(0,0,0,0.12)] animate-in slide-in-from-right duration-300',
                'rounded-tl-[8px]',
              )}
              aria-label="参考资料"
              onClick={(event) => event.stopPropagation()}
              onPointerDown={(event) => event.stopPropagation()}
            >
              {panelContent}
            </aside>
          ),
          document.body,
        )}
      {!isDesktopInlinePanel && (
        <CitationDocumentPreviewDrawer
          preview={documentPreview}
          onClose={() => setDocumentPreview(null)}
          manageMobileNavVisibility={false}
        />
      )}
    </>
  );
}
