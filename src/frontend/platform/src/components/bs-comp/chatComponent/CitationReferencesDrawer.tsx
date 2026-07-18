import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Download, Loader2, X } from "lucide-react";
import { getCitationDetail, resolveCitationDetails, type ChatCitation } from "@/controllers/API";
import { cname } from "@/components/bs-ui/utils";
import {
  buildCitationDocumentPreview,
  buildCitationReferenceItems,
  createCitationDetailMap,
  getCitationDocumentDownloadUrl,
  getCitationDocumentFileType,
  getCitationDocumentName,
  isRagCitation,
  isRagCitationMissingPreviewUrl,
  normalizeCitationType,
  toAbsolutePreviewUrl,
  type CitationPreview,
  type CitationReferenceItem,
} from "./citationUtils";
import CitationDocumentPreviewDrawer, {
  CitationDocumentPreviewContent,
  type CitationDocumentPreviewState,
} from "./CitationDocumentPreviewDrawer";
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

type CitationPanelView = "list" | "document-preview";

function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(() => {
    if (typeof window === "undefined") {
      return false;
    }
    return window.matchMedia(query).matches;
  });

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const mediaQuery = window.matchMedia(query);
    const handleChange = () => setMatches(mediaQuery.matches);
    handleChange();
    mediaQuery.addEventListener("change", handleChange);
    return () => {
      mediaQuery.removeEventListener("change", handleChange);
    };
  }, [query]);

  return matches;
}

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
  onOpenDocumentPreview: (item: CitationReferenceItem, detail: ChatCitation) => void;
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
          onClick={() => onOpenDocumentPreview(item, detail!)}
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
  const drawerRef = useRef<HTMLElement>(null);
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

  const isPhoneViewport = useMediaQuery("(max-width: 576px)");
  const isNarrowLayout = useMediaQuery("(max-width: 768px)");
  const isFullBleedMobile = isPhoneViewport;
  const [panelView, setPanelView] = useState<CitationPanelView>("list");

  useEffect(() => {
    if (!open) {
      setPanelView("list");
      setDocumentPreview(null);
    }
  }, [open]);

  useEffect(() => {
    if (!open || !isFullBleedMobile) {
      return;
    }

    const originalBodyOverflow = document.body.style.overflow;
    const originalHtmlOverflow = document.documentElement.style.overflow;
    document.body.style.overflow = "hidden";
    document.documentElement.style.overflow = "hidden";

    return () => {
      document.body.style.overflow = originalBodyOverflow;
      document.documentElement.style.overflow = originalHtmlOverflow;
    };
  }, [isFullBleedMobile, open]);

  useEffect(() => {
    if (!open || isFullBleedMobile) {
      return;
    }

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as HTMLElement | null;
      if (!target || drawerRef.current?.contains(target)) return;
      if (target.closest('[data-citation-references-trigger="true"]')) return;
      if (target.closest('[data-citation-trigger="true"]')) return;
      setPanelView("list");
      setDocumentPreview(null);
      setOpen(false);
    };

    document.addEventListener("pointerdown", handlePointerDown, true);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown, true);
    };
  }, [isFullBleedMobile, open]);

  if (!references.length) {
    return null;
  }

  const referenceEntryIcons = buildCitationSourceIconStackData(references, detailMap);
  const referenceIconCount = Math.min(referenceEntryIcons.length, 3);
  const referenceButtonWidth = referenceIconCount <= 1 ? "w-24 min-w-24" : referenceIconCount === 2 ? "w-[104px] min-w-[104px]" : "w-28 min-w-28";
  const referenceIconStackWidth = referenceIconCount <= 1 ? "w-5" : referenceIconCount === 2 ? "w-7" : "w-9";

  const handleClosePanel = () => {
    setOpen(false);
  };

  const handleOpenDocumentPreview = (item: CitationReferenceItem, detail: ChatCitation) => {
    setDocumentPreview({
      detail,
      itemId: item.data.itemId,
      locateChunk: false,
    });
    setPanelView("document-preview");
  };

  const handleDownloadDocument = () => {
    if (!documentPreview) {
      return;
    }

    const fileName = getCitationDocumentName(documentPreview.detail);
    const fileUrl = toAbsolutePreviewUrl(getCitationDocumentDownloadUrl(documentPreview.detail));
    if (!fileUrl) {
      return;
    }

    const link = document.createElement("a");
    link.href = fileUrl;
    link.download = fileName;
    link.target = "_blank";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const documentHeaderTitle = documentPreview
    ? splitDocumentTitle(getCitationDocumentName(documentPreview.detail), documentPreview.detail, null)
    : { name: "文档预览", extension: "" };

  const referenceListContent = (
    <>
      <div className={cname(
        "flex shrink-0 items-center justify-between border-b border-[#ECECEC] bg-white",
        isNarrowLayout ? "h-11 px-2" : "h-14 px-3",
      )}>
        <div className="flex items-center gap-2">
          <h2 className="text-[14px] font-medium leading-[22px] text-[#1D2129]">参考资料</h2>
          <span className="inline-flex h-4 w-4 items-center justify-center gap-2 rounded-[6px] bg-[#F5F8FF] px-1 text-[12px] font-medium leading-4 text-[#165DFF]">
            {references.length}
          </span>
        </div>
        <button
          type="button"
          onClick={handleClosePanel}
          className={cname(
            "inline-flex items-center justify-center text-[#A9AEB8] hover:bg-[#F2F3F5] hover:text-[#4E5969]",
            isNarrowLayout ? "size-8 rounded-md" : "size-6 rounded-[6px]",
          )}
          aria-label="关闭参考资料"
        >
          <X className="size-4" strokeWidth={1.5} />
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto overscroll-contain px-3 py-4 [-webkit-overflow-scrolling:touch]">
        {references.map((item) => {
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
        })}
      </div>
    </>
  );

  const documentPreviewContent = (
    <div className="flex min-h-0 flex-1 flex-col bg-white">
      <div className="flex h-14 w-full min-w-0 shrink-0 items-center gap-2 border-b border-[#ECECEC] bg-white px-3">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <button
            type="button"
            onClick={() => {
              setPanelView("list");
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
              title={documentPreview ? getCitationDocumentName(documentPreview.detail) : ""}
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
          className="inline-flex size-6 shrink-0 items-center justify-center rounded-[6px] text-[#024DE3] transition-colors hover:bg-[#F2F7FF]"
          aria-label="下载文档"
        >
          <Download className="size-4" strokeWidth={1.75} />
        </button>
        <button
          type="button"
          onClick={handleClosePanel}
          className="inline-flex size-6 shrink-0 items-center justify-center rounded-[6px] text-[#A9AEB8] transition-colors hover:bg-[#F7F8FA]"
          aria-label="关闭参考资料"
        >
          <X className="size-4" strokeWidth={1.5} />
        </button>
      </div>
      <div className="flex min-h-0 w-full flex-1 flex-col overflow-hidden bg-[#fbfbfb]">
        <CitationDocumentPreviewContent
          preview={documentPreview}
          compactMode
          className="min-h-0 w-full flex-1 bg-[#fbfbfb]"
        />
      </div>
    </div>
  );

  const panelContent = panelView === "document-preview" && documentPreview ? documentPreviewContent : referenceListContent;

  return (
    <>
      <button
        type="button"
        data-citation-references-trigger="true"
        onClick={() => setOpen(true)}
        className={cname(
          "flex h-6 shrink-0 items-center justify-end gap-1 rounded-[6px] bg-transparent px-1 py-0.5 text-[#818181] transition-colors hover:bg-[#F7F7F7]",
          referenceButtonWidth,
          buttonClassName,
        )}
      >
        <div className={cname("flex h-5 shrink-0 items-center", referenceIconStackWidth)}>
          <CitationSourceIconStack icons={referenceEntryIcons} />
        </div>
        <div className="flex h-5 w-16 shrink-0 items-center whitespace-nowrap">
          <span className="w-12 whitespace-nowrap text-[12px] font-normal leading-5 text-[#818181]">参考资料</span>
          <ChevronRight className="size-4 text-[#818181]" strokeWidth={1.5} />
        </div>
      </button>

      {open && (
        isFullBleedMobile ? (
          <aside
            className="fixed inset-0 z-[120] flex h-[100dvh] min-h-0 flex-col overflow-hidden overscroll-contain bg-white"
            aria-label="参考资料"
          >
            {panelContent}
          </aside>
        ) : (
          <aside
            ref={drawerRef}
            className="fixed inset-y-0 right-0 z-[120] flex h-full min-h-0 w-[min(520px,calc(100vw-24px))] min-w-0 flex-col bg-white shadow-[0_8px_24px_rgba(0,0,0,0.12)]"
            aria-label="参考资料"
            onClick={(event) => event.stopPropagation()}
            onPointerDown={(event) => event.stopPropagation()}
          >
            {panelContent}
          </aside>
        )
      )}
      {panelView !== "document-preview" && (
        <CitationDocumentPreviewDrawer
          preview={documentPreview}
          onClose={() => setDocumentPreview(null)}
        />
      )}
    </>
  );
}
