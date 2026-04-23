import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronRight, Loader2, X } from 'lucide-react';
import { getCitationDetail, resolveCitationDetails, type ChatCitation } from '~/api/chatApi';
import { usePrefersMobileLayout } from '~/hooks';
import { cn } from '~/utils';
import {
  buildCitationDocumentPreview,
  buildCitationReferenceItems,
  createCitationDetailMap,
  getCitationDocumentFileType,
  isRagCitation,
  normalizeCitationType,
  type CitationPreview,
  type CitationReferenceItem,
} from './citationUtils';
import CitationDocumentPreviewDrawer, { type CitationDocumentPreviewState } from './CitationDocumentPreviewDrawer';
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
};

export type CitationReferencesDesktopPayload = {
  messageId?: string;
  content: string;
  webContent?: any;
  citations?: ChatCitation[] | null;
  referenceItems: CitationReferenceItem[];
};

function SourceTypeBadge({ preview, label, type }: { preview: CitationPreview | null; label: number; type?: string }) {
  const isWeb = normalizeCitationType(preview?.type || type) === 'web';
  return (
    <div
      className={cn(
        'inline-flex h-[18px] min-w-[16px] items-center justify-center rounded-[6px] px-1 text-[12px] font-normal leading-[18px]',
        isWeb ? 'bg-[#F7F3FF] text-[#7224D9]' : 'bg-[#F5F8FF] text-[#024DE3]',
      )}
    >
      [{label}] - {isWeb ? '网页' : '文档'}
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
  isH5 = false,
}: {
  item: CitationReferenceItem;
  detail: ChatCitation | null;
  isLoading: boolean;
  hasError: boolean;
  onOpenDocumentPreview: (detail: ChatCitation) => void;
  isH5?: boolean;
}) {
  const preview = item.legacyPreview ?? buildCitationDocumentPreview(detail, item.data);
  const type = preview?.type || item.data.type;
  const isWeb = normalizeCitationType(type) === 'web';
  const title = preview?.title || '暂无标题';
  const canOpenDocument = !!detail && isRagCitation(detail, type);
  const sourceMetaText = [preview?.sourceName, preview?.sourceMeta].filter(Boolean).join(' | ');
  const { name: documentName, extension: documentExtension } = splitDocumentTitle(title, detail, preview);

  if (isH5) {
    return (
      <div className="border-b border-[#F2F3F5] py-3">
        <div className="mb-2 flex items-center justify-between gap-2 text-[13px] leading-5 text-[#86909C]">
          <div className="flex min-w-0 items-center gap-2">
            <CitationSourceIcon detail={detail} preview={preview} type={type} ragIconVariant="knowledge" />
            <span className="min-w-0 truncate">{sourceMetaText || (isWeb ? '网页来源' : '知识库')}</span>
          </div>
          <span className="inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-[#F2F3F5] text-[12px] leading-none text-[#86909C]">
            {item.data.label}
          </span>
        </div>

        <div className="min-w-0 text-[16px] font-semibold leading-6 text-[#1D2129]">
          {canOpenDocument ? (
            <button
              type="button"
              onClick={() => onOpenDocumentPreview(detail!)}
              className="min-w-0 truncate text-left hover:text-[#165DFF] hover:underline"
              title={title}
            >
              {title}
            </button>
          ) : preview?.link ? (
            <a
              href={preview.link}
              target="_blank"
              rel="noreferrer"
              className="min-w-0 truncate hover:text-[#165DFF] hover:underline"
              title={title}
            >
              {title}
            </a>
          ) : (
            <span className="min-w-0 truncate" title={title}>{title}</span>
          )}
        </div>

        <div className="mt-1 text-[13px] leading-5 text-[#86909C] line-clamp-2">
          {preview?.snippet || '暂无内容摘要'}
        </div>

        {(isLoading || hasError) && (
          <div className="mt-2 min-h-[22px] text-[13px] leading-[22px] text-[#4E5969]">
            {isLoading ? (
              <span className="inline-flex items-center gap-2 text-[#86909C]">
                <Loader2 className="size-3.5 animate-spin" />
                加载溯源详情...
              </span>
            ) : hasError ? (
              <span className="text-[#86909C]">溯源详情加载失败</span>
            ) : null}
          </div>
        )}
      </div>
    );
  }

  const titleContent = canOpenDocument ? (
    <button
      type="button"
      onClick={() => onOpenDocumentPreview(detail!)}
      className="flex min-w-0 items-center gap-1 text-left hover:text-[#165DFF]"
      title={title}
    >
      <span className="truncate">{documentName}</span>
      {documentExtension ? <span className="shrink-0">{documentExtension}</span> : null}
    </button>
  ) : preview?.link ? (
    <a
      href={preview.link}
      target="_blank"
      rel="noreferrer"
      className="block min-w-0 truncate hover:text-[#165DFF]"
      title={title}
    >
      {title}
    </a>
  ) : (
    <span className="block min-w-0 truncate" title={title}>{title}</span>
  );

  return (
    <div className="flex min-h-[92px] flex-col gap-2 rounded-[6px] bg-[#FBFBFB] p-2">
      <div className="flex items-center">
        <SourceTypeBadge preview={preview} label={item.data.label} type={item.data.type} />
      </div>

      <div className="flex min-w-0 items-center gap-1 text-[14px] font-normal leading-[22px] text-[#1D2129]">
        {!isWeb && <CitationSourceIcon detail={detail} preview={preview} type={type} />}
        <div className="min-w-0 flex-1">
          {titleContent}
        </div>
      </div>

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
}: CitationReferencesDrawerProps) {
  const isH5 = usePrefersMobileLayout();
  const [internalOpen, setInternalOpen] = useState(false);
  const [detailMap, setDetailMap] = useState<Record<string, ChatCitation>>(() => createCitationDetailMap(citations));
  const [loadingMap, setLoadingMap] = useState<Record<string, boolean>>({});
  const [errorMap, setErrorMap] = useState<Record<string, boolean>>({});
  const [documentPreview, setDocumentPreview] = useState<CitationDocumentPreviewState | null>(null);
  const detailCacheRef = useRef<Record<string, ChatCitation>>({});
  const requestCacheRef = useRef<Record<string, Promise<ChatCitation | null>>>({});
  const batchRequestKeyRef = useRef<string>('');

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

  useEffect(() => {
    const citationIds = Array.from(new Set(
      references
        .map((item) => item.data.citationId)
        .filter((citationId) => citationId && !citationId.startsWith('citation:') && !detailCacheRef.current[citationId]),
    ));

    if (!citationIds.length) {
      return;
    }

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
  }, [references]);

  const loadCitationDetail = useCallback(async (citationId: string) => {
    if (!citationId || citationId.startsWith('citation:')) {
      return null;
    }

    const cachedDetail = detailCacheRef.current[citationId];
    if (cachedDetail) {
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
  }, []);

  useEffect(() => {
    const shouldUseDesktopInlinePanel = !isH5
      && desktopMode === 'inline-panel'
      && (panelOnly || !!onDesktopOpen || typeof open === 'boolean' || !!onOpenChange);
    const shouldLoadDetails = panelOnly ? true : shouldUseDesktopInlinePanel ? !!open : internalOpen;
    if (!shouldLoadDetails) {
      return;
    }

    const citationIds = Array.from(new Set(
      references
        .map((item) => item.data.citationId)
        .filter((citationId) => citationId && !citationId.startsWith('citation:') && !detailMap[citationId]),
    ));

    citationIds.forEach((citationId) => {
      void loadCitationDetail(citationId);
    });
  }, [detailMap, desktopMode, internalOpen, isH5, loadCitationDetail, open, panelOnly, references]);

  const referenceEntryIcons = buildCitationSourceIconStackData(references, detailMap);
  const isDesktopInlinePanel = !isH5
    && desktopMode === 'inline-panel'
    && (panelOnly || !!onDesktopOpen || typeof open === 'boolean' || !!onOpenChange);
  const isOpen = panelOnly ? true : isDesktopInlinePanel ? !!open : internalOpen;
  const setOpenState = (nextOpen: boolean) => {
    if (isDesktopInlinePanel) {
      onOpenChange?.(nextOpen);
      return;
    }

    setInternalOpen(nextOpen);
  };
  const handleOpenButtonClick = () => {
    if (isDesktopInlinePanel) {
      if (isOpen && !panelOnly) {
        onOpenChange?.(false);
      } else {
        onDesktopOpen?.({
          messageId,
          content,
          webContent,
          citations,
          referenceItems: references,
        });
        onOpenChange?.(true);
      }
      return;
    }

    setOpenState(true);
  };
  const panelContent = (
    <>
      <div className={cn(
        'flex shrink-0 items-center justify-between border-b border-[#ECECEC] bg-white',
        isH5 ? 'h-14 px-4' : 'h-14 px-3',
      )}>
        <div className="flex items-center gap-2">
          <h2 className="text-[14px] font-medium leading-[22px] text-[#1D2129]">
            {isH5 ? `参考来源 ${references.length}` : '参考资料'}
          </h2>
          {!isH5 && (
            <span className="inline-flex h-4 min-w-4 items-center justify-center rounded-[6px] bg-[#F5F8FF] px-1 text-[12px] leading-[18px] text-[#024DE3]">
              {references.length}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={() => setOpenState(false)}
          className="inline-flex size-6 items-center justify-center rounded-[6px] text-[#A9AEB8] hover:bg-[#F2F3F5] hover:text-[#4E5969]"
          aria-label="关闭参考资料"
        >
          <X className="size-4" strokeWidth={1.5} />
        </button>
      </div>

      <div className={cn(
        'flex-1 overflow-y-auto',
        isH5 ? 'px-4 py-1' : 'space-y-3 px-3 py-4',
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
                isH5={isH5}
                onOpenDocumentPreview={(detail) => {
                  setDocumentPreview({
                    detail,
                    locateChunk: false,
                  });
                }}
              />
            );
          })
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-[#86909C]">
            暂无参考资料
          </div>
        )}
      </div>
      <CitationDocumentPreviewDrawer
        preview={documentPreview}
        onClose={() => setDocumentPreview(null)}
      />
    </>
  );

  if (panelOnly) {
    return (
      <section
        className={cn('flex h-full min-h-0 flex-col bg-white', !isH5 && 'w-full max-w-[360px]', panelClassName)}
        aria-label="参考资料"
      >
        {panelContent}
      </section>
    );
  }

  if (!references.length) {
    return null;
  }

  return (
    <>
      <div
        className={cn('flex h-6 items-center', actionButtons ? 'w-[196px] gap-3' : 'w-[112px]', buttonClassName)}
      >
        {actionButtons && <div className="flex items-center gap-1">{actionButtons}</div>}
        <button
          type="button"
          data-citation-references-trigger="true"
          onClick={handleOpenButtonClick}
          className={cn(
            'flex h-6 w-[112px] items-center justify-end gap-1 rounded-[6px] px-1 text-[#818181] transition-colors',
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
        <>
          <div
            className={cn('fixed inset-0 z-40', isH5 ? 'bg-black/30' : 'bg-transparent')}
            aria-hidden="true"
            onClick={() => setOpenState(false)}
          />
          <aside
            className={cn(
              'fixed z-50 flex flex-col bg-white shadow-[0_8px_24px_rgba(0,0,0,0.12)]',
              isH5
                ? 'inset-x-0 bottom-0 max-h-[78vh] rounded-t-2xl border-t border-[#E5E6EB]'
                : 'inset-y-0 right-0 w-[min(520px,calc(100vw-24px))] border-l border-[#E5E6EB]',
            )}
            aria-label="参考资料"
          >
            {panelContent}
          </aside>
        </>
      )}
    </>
  );
}
