import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronRight, Loader2, X } from "lucide-react";
import { getCitationDetail, resolveCitationDetails, type ChatCitation } from "@/controllers/API";
import { cname } from "@/components/bs-ui/utils";
import {
  buildCitationDocumentPreview,
  buildCitationReferenceItems,
  createCitationDetailMap,
  getCitationDocumentFileType,
  isRagCitation,
  isRagCitationMissingPreviewUrl,
  normalizeCitationType,
  type CitationPreview,
  type CitationReferenceItem,
} from "./citationUtils";
import CitationDocumentPreviewDrawer, { type CitationDocumentPreviewState } from "./CitationDocumentPreviewDrawer";
import {
  buildCitationSourceIconStackData,
  CitationSourceIcon,
  CitationSourceIconStack,
} from "./CitationSourceIcon";

type CitationReferencesDrawerProps = {
  content: string;
  webContent?: any;
  citations?: ChatCitation[] | null;
  buttonClassName?: string;
  allowRemoteCitationResolve?: boolean;
};

function SourceTypeBadge({ preview, type }: { preview: CitationPreview | null; type?: string }) {
  const isWeb = normalizeCitationType(preview?.type || type) === "web";
  return (
    <div
      className={cname(
        "inline-flex h-[18px] min-w-[16px] items-center justify-center rounded-[6px] px-1 text-[12px] font-normal leading-[18px]",
        isWeb ? "bg-[#F7F3FF] text-[#7224D9]" : "bg-[#F5F8FF] text-[#024DE3]",
      )}
    >
      {isWeb ? "网页" : "文档"}
    </div>
  );
}

function splitDocumentTitle(title: string, detail: ChatCitation | null, preview: CitationPreview | null) {
  const fileType = String(getCitationDocumentFileType(detail) || preview?.sourceMeta || "")
    .toLowerCase()
    .replace(/^\./, "");

  if (!fileType) {
    return { name: title, extension: "" };
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
  onOpenDocumentPreview: (detail: ChatCitation) => void;
}) {
  const preview = item.legacyPreview ?? buildCitationDocumentPreview(detail, item.data);
  const type = preview?.type || item.data.type;
  const isWeb = normalizeCitationType(type) === "web";
  const title = preview?.title || "暂无标题";
  const canOpenDocument = !!detail && isRagCitation(detail, type);
  const { name: documentName, extension: documentExtension } = splitDocumentTitle(title, detail, preview);

  const nameRowTextClass = "text-[14px] font-normal leading-[22px] text-[#1D2129]";

  return (
    <div className="flex min-h-[92px] flex-col gap-2 rounded-[6px] bg-[#FBFBFB] p-2">
      <div className="flex items-center">
        <SourceTypeBadge preview={preview} type={item.data.type} />
      </div>

      {canOpenDocument ? (
        <button
          type="button"
          onClick={() => onOpenDocumentPreview(detail!)}
          className={cname(
            "flex w-full min-w-0 items-center gap-1 rounded-[4px] text-left",
            nameRowTextClass,
            "transition-colors hover:text-[#165DFF] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#165DFF]/25",
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
          className={cname(
            "flex w-full min-w-0 items-center gap-1 rounded-[4px] hover:text-[#165DFF]",
            nameRowTextClass,
          )}
          title={title}
        >
          {!isWeb && <CitationSourceIcon detail={detail} preview={preview} type={type} />}
          <span className="min-w-0 flex-1 truncate">{title}</span>
        </a>
      ) : (
        <div className={cname("flex min-w-0 items-center gap-1", nameRowTextClass)}>
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
            <span className="truncate">{preview?.sourceName || "网页"}</span>
            {preview?.sourceMeta ? <span className="shrink-0">{preview.sourceMeta}</span> : null}
          </>
        ) : (
          <>
            <CitationSourceIcon detail={detail} preview={preview} type={type} ragIconVariant="knowledge" />
            <span className="truncate">{preview?.sourceName || "政策文件"}</span>
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
  buttonClassName,
  allowRemoteCitationResolve = true,
}: CitationReferencesDrawerProps) {
  const [open, setOpen] = useState(false);
  const [detailMap, setDetailMap] = useState<Record<string, ChatCitation>>(() => createCitationDetailMap(citations));
  const [loadingMap, setLoadingMap] = useState<Record<string, boolean>>({});
  const [errorMap, setErrorMap] = useState<Record<string, boolean>>({});
  const [documentPreview, setDocumentPreview] = useState<CitationDocumentPreviewState | null>(null);
  const detailCacheRef = useRef<Record<string, ChatCitation>>({});
  const requestCacheRef = useRef<Record<string, Promise<ChatCitation | null>>>({});
  const batchRequestKeyRef = useRef<string>("");
  const resolvedIdsRef = useRef<Set<string>>(new Set());

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
    if (!allowRemoteCitationResolve) {
      return;
    }

    const citationIds = Array.from(new Set(
      references
        .map((item) => item.data.citationId)
        .filter((citationId) => {
          if (!citationId || citationId.startsWith("citation:")) return false;
          if (resolvedIdsRef.current.has(citationId)) return false;
          const cached = detailCacheRef.current[citationId];
          return !cached || isRagCitationMissingPreviewUrl(cached);
        }),
    ));

    if (!citationIds.length) {
      return;
    }

    const requestKey = citationIds.sort().join("|");
    if (batchRequestKeyRef.current === requestKey) {
      return;
    }
    batchRequestKeyRef.current = requestKey;

    void resolveCitationDetails(citationIds)
      .then((items) => {
        const nextMap: Record<string, ChatCitation> = {};
        items.forEach((detail) => {
          if (detail?.citationId) {
            resolvedIdsRef.current.add(detail.citationId);
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
        console.error("Failed to resolve citation details:", error);
        batchRequestKeyRef.current = "";
      });
  }, [allowRemoteCitationResolve, references]);

  const loadCitationDetail = useCallback(async (citationId: string) => {
    if (!citationId || citationId.startsWith("citation:")) {
      return null;
    }

    const cachedDetail = detailCacheRef.current[citationId];
    if (cachedDetail) {
      return cachedDetail;
    }

    if (!allowRemoteCitationResolve) {
      return null;
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
        console.error("Failed to load citation detail:", error);
        setErrorMap((current) => ({ ...current, [citationId]: true }));
        return null;
      })
      .finally(() => {
        delete requestCacheRef.current[citationId];
        setLoadingMap((current) => ({ ...current, [citationId]: false }));
      });

    requestCacheRef.current[citationId] = request;
    return request;
  }, [allowRemoteCitationResolve]);

  useEffect(() => {
    if (!open || !allowRemoteCitationResolve) {
      return;
    }

    const citationIds = Array.from(new Set(
      references
        .map((item) => item.data.citationId)
        .filter((citationId) => {
          if (!citationId || citationId.startsWith("citation:")) return false;
          if (resolvedIdsRef.current.has(citationId)) return false;
          const cached = detailMap[citationId];
          return !cached || isRagCitationMissingPreviewUrl(cached);
        }),
    ));

    citationIds.forEach((citationId) => {
      void loadCitationDetail(citationId).then((detail) => {
        if (detail?.citationId) {
          resolvedIdsRef.current.add(detail.citationId);
        }
      });
    });
  }, [allowRemoteCitationResolve, detailMap, loadCitationDetail, open, references]);

  if (!references.length) {
    return null;
  }

  const referenceEntryIcons = buildCitationSourceIconStackData(references, detailMap);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cname(
          "inline-flex h-6 items-center justify-end gap-1 rounded-[6px] px-1 text-[#818181] transition-colors hover:bg-[#F7F7F7]",
          buttonClassName,
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
            <div className="flex h-14 shrink-0 items-center justify-between border-b border-[#ECECEC] bg-white px-3">
              <div className="flex items-center gap-2">
                <h2 className="text-[14px] font-medium leading-[22px] text-[#1D2129]">参考资料</h2>
                <span className="inline-flex h-4 min-w-4 items-center justify-center rounded-[6px] bg-[#F5F8FF] px-1 text-[12px] leading-[18px] text-[#024DE3]">
                  {references.length}
                </span>
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="inline-flex size-6 items-center justify-center rounded-[6px] text-[#A9AEB8] hover:bg-[#F2F3F5] hover:text-[#4E5969]"
                aria-label="关闭参考资料"
              >
                <X className="size-4" strokeWidth={1.5} />
              </button>
            </div>

            <div className="flex-1 space-y-3 overflow-y-auto px-3 py-4">
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
