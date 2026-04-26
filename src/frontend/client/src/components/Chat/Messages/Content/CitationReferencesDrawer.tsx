import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, Download, Loader2, X } from 'lucide-react';
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
        isWeb ? 'bg-[#F7F3FF] text-[#7224D9]' : 'bg-[#F5F8FF] text-[#024DE3]',
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
    <div className="flex min-h-[92px] flex-col gap-2 rounded-[6px] bg-[#FBFBFB] p-2">
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
            'transition-colors hover:text-[#165DFF] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#165DFF]/25',
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
            'flex w-full min-w-0 items-center gap-1 rounded-[4px] hover:text-[#165DFF]',
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
            <CitationSourceIcon detail={detail} preview={preview} type={type} ragIconVariant="knowledge" />
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
  const isDesktopInlinePanel = !isNarrowLayout
    && desktopMode === 'inline-panel'
    && (panelOnly || !!onDesktopOpen || typeof open === 'boolean' || !!onOpenChange);
  const isOpen = panelOnly ? true : isDesktopInlinePanel ? !!open : internalOpen;
  const isDesktopPreviewInline = isDesktopInlinePanel && desktopView === 'document-preview' && !!documentPreview;

  useEffect(() => {
    if (!isNarrowLayout || !isOpen) {
      return;
    }

    setChatMobileNavHidden(true);
    return () => {
      setChatMobileNavHidden(false);
    };
  }, [isNarrowLayout, isOpen, setChatMobileNavHidden]);

  useEffect(() => {
    if (!isOpen && !panelOnly) {
      setDesktopView('list');
      setDocumentPreview(null);
    }
  }, [isOpen, panelOnly]);

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
  // 非 expanded：侧栏内预览区横向铺满，避免 max-w + items-center 在侧栏中留出左右大空白
  const desktopPanelMaxWidth = useExpandedDesktopPreview ? 'max-w-[480px]' : 'max-w-full';
  const desktopHeaderPadding = 'px-3';
  const desktopHeaderHeight = 'h-14';
  const desktopHeaderGap = 'gap-2';
  const desktopButtonSize = 'size-6 rounded-[6px]';
  const desktopButtonIconSize = 'size-4';
  const desktopDownloadButtonClass = useExpandedDesktopPreview
    ? 'text-[#024DE3] hover:bg-[#F2F7FF]'
    : 'text-[#024DE3] hover:bg-[#F2F7FF]';
  const desktopCloseButtonClass = useExpandedDesktopPreview
    ? 'text-[#333333] hover:bg-[#F7F8FA]'
    : 'text-[#A9AEB8] hover:bg-[#F7F8FA]';
  const desktopContentOuterClass = useExpandedDesktopPreview
    ? 'items-center justify-between gap-6 p-2'
    : 'w-full min-w-0 items-stretch gap-0';
  const desktopBodyWrapperClass = useExpandedDesktopPreview
    ? 'max-w-[464px] rounded-[12px] bg-[#F7F8FA]'
    : 'w-full min-w-0 max-w-full overflow-hidden bg-[#F7F8FA]';
  const desktopBodyClass = useExpandedDesktopPreview
    ? 'min-h-0 flex-1 w-full bg-[#F7F8FA]'
    : 'min-h-0 w-full flex-1 bg-[#fbfbfb]';
  const referenceListContent = (
    <>
      <div className={cn(
        'flex shrink-0 items-center justify-between border-b border-[#ECECEC] bg-white',
        isMobileLikeViewport ? 'h-11 px-2' : 'h-14 px-3',
      )}>
        <div className="flex items-center gap-2">
          <h2 className="text-[14px] font-medium leading-[22px] text-[#1D2129]">
            {localize('com_msg_source_reference')}
          </h2>
          <span className="inline-flex h-4 w-4 items-center justify-center gap-2 rounded-[6px] bg-[#F5F8FF] px-1 text-[12px] font-medium leading-4 text-[#165DFF]">
            {references.length}
          </span>
        </div>
        <button
          type="button"
          onClick={() => setOpenState(false)}
          className={cn(
            'inline-flex items-center justify-center hover:bg-[#F2F3F5] hover:text-[#4E5969]',
            isMobileLikeViewport ? 'size-8 rounded-md' : 'size-6 rounded-[6px]',
          )}
          aria-label="关闭参考资料"
        >
          <X className="size-4" strokeWidth={1.5} />
        </button>
      </div>

      <div className={cn(
        'flex-1 overflow-y-auto',
        'space-y-3 px-3 py-4',
      )}>
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
    <div className={cn('flex min-h-0 flex-1 flex-col bg-white', desktopContentOuterClass)}>
      <div
        className={cn(
          'flex shrink-0 flex-col',
          useExpandedDesktopPreview ? 'w-full max-w-[464px] gap-4' : 'w-full max-w-full gap-0',
        )}
      >
        <div
          className={cn(
            'flex w-full min-w-0 shrink-0 items-center border-b border-[#ECECEC] bg-white',
            desktopHeaderHeight,
            desktopHeaderGap,
            desktopHeaderPadding,
          )}
        >
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <button
              type="button"
              onClick={() => {
                setDesktopView('list');
                setDocumentPreview(null);
              }}
              className="inline-flex size-6 shrink-0 items-center justify-center rounded-[6px] text-[#4E5969] hover:bg-[#F2F3F5]"
              aria-label="返回参考资料列表"
            >
              <ChevronLeft className="size-4" strokeWidth={1.75} />
            </button>
            <div className="flex min-w-0 items-center">
              <h2
                className="truncate text-[14px] font-medium leading-[22px] text-[#1D2129]"
                title={documentPreview ? getCitationDocumentName(documentPreview.detail) : ''}
              >
                {documentHeaderTitle.name}
              </h2>
              {documentHeaderTitle.extension ? (
                <span className="shrink-0 text-[14px] font-medium leading-[22px] text-[#1D2129]">
                  {documentHeaderTitle.extension}
                </span>
              ) : null}
            </div>
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
            <Download className={useExpandedDesktopPreview ? 'size-4' : 'size-4'} strokeWidth={1.75} />
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
            <X className={desktopButtonIconSize} strokeWidth={useExpandedDesktopPreview ? 1.75 : 1.5} />
          </button>
        </div>
      </div>
      <div className={cn('flex min-h-0 w-full flex-1 flex-col overflow-hidden', desktopBodyWrapperClass)}>
        <CitationDocumentPreviewContent
          preview={documentPreview}
          compactMode
          className={desktopBodyClass}
        />
      </div>
    </div>
  );

  const panelContent = isDesktopPreviewInline ? documentPreviewContent : referenceListContent;

  if (panelOnly) {
    return (
      <>
        <section
          className={cn('flex h-full min-h-0 flex-col bg-white', !isNarrowLayout && `w-full ${desktopPanelMaxWidth}`, panelClassName)}
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
            'flex h-6 w-[112px] min-w-[112px] shrink-0 items-center justify-end gap-1 rounded-[6px] px-1 text-[#818181] transition-colors',
            isOpen ? 'bg-[#F2F3F5]' : 'bg-transparent hover:bg-[#F7F7F7]',
          )}
        >
          <div className="flex h-5 w-11 shrink-0 items-center overflow-hidden">
            <CitationSourceIconStack icons={referenceEntryIcons} />
          </div>
          <div className="flex h-5 shrink-0 items-center gap-1 whitespace-nowrap">
            <span className="whitespace-nowrap text-[12px] font-normal leading-5 text-[#818181]">参考资料</span>
            <ChevronRight className="size-4 text-[#818181]" strokeWidth={1.5} />
          </div>
        </button>
      </div>

      {!isDesktopInlinePanel && isOpen && (
        isFullBleedMobile ? (
          <aside
            className="fixed inset-0 z-[120] flex flex-col overflow-hidden overscroll-contain bg-white touch-pan-y"
            aria-label="参考资料"
          >
            {panelContent}
          </aside>
        ) : (
          <div className="pointer-events-none fixed inset-0 z-[120] flex justify-end">
            <button
              type="button"
              aria-label="关闭参考资料"
              className="absolute inset-0 z-0 pointer-events-auto bg-transparent"
              onClick={() => setOpenState(false)}
            />
            <aside
              className="relative z-10 flex h-full w-[min(520px,calc(100vw-24px))] min-w-0 flex-col bg-white pointer-events-auto shadow-[0_8px_24px_rgba(0,0,0,0.12)] animate-in slide-in-from-right duration-300"
              aria-label="参考资料"
              onClick={(event) => event.stopPropagation()}
              onPointerDown={(event) => event.stopPropagation()}
            >
              {panelContent}
            </aside>
          </div>
        )
      )}
      {!isDesktopInlinePanel && (
        <CitationDocumentPreviewDrawer
          preview={documentPreview}
          onClose={() => setDocumentPreview(null)}
        />
      )}
    </>
  );
}
