import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronRight, Loader2, X } from 'lucide-react';
import { getCitationDetail, resolveCitationDetails, type ChatCitation } from '~/api/chatApi';
import { cn } from '~/utils';
import {
  buildCitationDocumentPreview,
  buildCitationReferenceItems,
  createCitationDetailMap,
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
  buttonClassName?: string;
};

function SourceTypeBadge({ preview, label, type }: { preview: CitationPreview | null; label: number; type?: string }) {
  const isWeb = normalizeCitationType(preview?.type || type) === 'web';
  return (
    <div className={cn('text-[14px] font-medium leading-5', isWeb ? 'text-[#7C3AED]' : 'text-[#165DFF]')}>
      [{label}] - {isWeb ? '网页' : '文档'}
    </div>
  );
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
  onOpenDocumentPreview: (detail: ChatCitation) => void;
}) {
  const preview = item.legacyPreview ?? buildCitationDocumentPreview(detail, item.data);
  const type = preview?.type || item.data.type;
  const isWeb = normalizeCitationType(type) === 'web';
  const title = preview?.title || '暂无标题';
  const canOpenDocument = !!detail && isRagCitation(detail, type);

  return (
    <div className="rounded-[8px] bg-[#FAFAFA] px-4 py-3">
      <div className="mb-3">
        <SourceTypeBadge preview={preview} label={item.data.label} type={item.data.type} />
      </div>

      <div className="flex min-w-0 items-center gap-2 text-[15px] font-medium leading-6 text-[#1D2129]">
        <CitationSourceIcon detail={detail} preview={preview} type={type} />
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

      {(isLoading || hasError) && <div className="mt-2 min-h-[22px] text-[14px] leading-[22px] text-[#4E5969]">
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

      <div className="mt-3 flex min-w-0 items-center gap-2 text-[13px] leading-5 text-[#86909C]">
        <CitationSourceIcon detail={detail} preview={preview} type={type} ragIconVariant="knowledge" />
        <span className="min-w-0 truncate">{preview?.sourceName || (isWeb ? '网页' : '政策文件')}</span>
        {preview?.sourceMeta && <span className="shrink-0">{preview.sourceMeta}</span>}
      </div>
    </div>
  );
}

export default function CitationReferencesDrawer({
  content,
  webContent,
  citations,
  buttonClassName,
}: CitationReferencesDrawerProps) {
  const [open, setOpen] = useState(false);
  const [detailMap, setDetailMap] = useState<Record<string, ChatCitation>>(() => createCitationDetailMap(citations));
  const [loadingMap, setLoadingMap] = useState<Record<string, boolean>>({});
  const [errorMap, setErrorMap] = useState<Record<string, boolean>>({});
  const [documentPreview, setDocumentPreview] = useState<CitationDocumentPreviewState | null>(null);
  const detailCacheRef = useRef<Record<string, ChatCitation>>({});
  const requestCacheRef = useRef<Record<string, Promise<ChatCitation | null>>>({});
  const batchRequestKeyRef = useRef<string>('');

  const references = useMemo(
    () => buildCitationReferenceItems({ content, webContent, citations }),
    [content, webContent, citations],
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
    if (!open) {
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
  }, [detailMap, loadCitationDetail, open, references]);

  if (!references.length) {
    return null;
  }

  const referenceEntryIcons = buildCitationSourceIconStackData(references, detailMap);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cn(
          'inline-flex h-7 items-center gap-1.5 rounded-[6px] px-2 text-[13px] leading-none text-[#86909C] transition-colors hover:bg-[#F2F3F5] hover:text-[#4E5969]',
          buttonClassName,
        )}
      >
        <CitationSourceIconStack icons={referenceEntryIcons} />
        <span>参考资料</span>
        <span className="text-[#165DFF]">{references.length}</span>
        <ChevronRight className="size-4" />
      </button>

      {open && (
        <>
          <div
            className="fixed inset-0 z-40 bg-transparent"
            aria-hidden="true"
            onClick={() => setOpen(false)}
          />
          <aside
            className="fixed inset-y-0 right-0 z-50 flex w-[min(520px,calc(100vw-24px))] flex-col border-l border-[#E5E6EB] bg-white shadow-[0_8px_24px_rgba(0,0,0,0.12)]"
            aria-label="参考资料"
          >
            <div className="flex h-16 shrink-0 items-center justify-between border-b border-[#F2F3F5] px-6">
              <div className="flex items-center gap-3">
                <h2 className="text-[16px] font-semibold leading-6 text-[#1D2129]">参考资料</h2>
                <span className="text-[16px] leading-6 text-[#165DFF]">{references.length}</span>
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="inline-flex size-8 items-center justify-center rounded-[6px] text-[#86909C] hover:bg-[#F2F3F5] hover:text-[#4E5969]"
                aria-label="关闭参考资料"
              >
                <X className="size-5" />
              </button>
            </div>

            <div className="flex-1 space-y-4 overflow-y-auto px-6 py-5">
              {references.map((item) => {
                const detail = detailMap[item.data.citationId] ?? item.detail ?? null;
                return (
                  <CitationReferenceCard
                    key={item.key}
                    item={item}
                    detail={detail}
                    isLoading={!!loadingMap[item.data.citationId]}
                    hasError={!!errorMap[item.data.citationId]}
                    onOpenDocumentPreview={(detail) => {
                      setDocumentPreview({
                        detail,
                        locateChunk: false,
                      });
                    }}
                  />
                );
              })}
            </div>
          </aside>
          <CitationDocumentPreviewDrawer
            preview={documentPreview}
            onClose={() => setDocumentPreview(null)}
          />
        </>
      )}
    </>
  );
}
