import pLimit from "p-limit";
import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react";
import type * as pdfjsLib from "pdfjs-dist";
import type { CitationPdfBBox } from "~/components/Chat/Messages/Content/citationUtils";
import { useLocalize } from "~/hooks";
import KnowledgePreviewWatermark from "../KnowledgePreviewWatermark";

const PDF_RENDER_CONCURRENCY = 2;
const PDF_RENDER_OVERSCAN_PX = 1200;
const PDF_PAGE_PLACEHOLDER_HEIGHT = 900;
const PDF_MAX_PIXEL_RATIO = 1.5;

interface PdfViewerProps {
    pdfDoc: pdfjsLib.PDFDocumentProxy | null;
    zoomLevel: number;
    targetPage: number | null;
    highlightBboxes?: CitationPdfBBox[];
    targetBBox?: CitationPdfBBox | null;
    onCurrentPageChange: (page: number) => void;
}

interface PageSize {
    width: number;
    height: number;
    originalWidth: number;
}

type RenderLimit = ReturnType<typeof pLimit>;

function releaseCanvas(canvas: HTMLCanvasElement | null) {
    if (!canvas) return;
    canvas.width = 0;
    canvas.height = 0;
    canvas.removeAttribute("style");
}

function isCancelledRender(error: unknown, signal: AbortSignal) {
    if (signal.aborted) return true;
    return error instanceof Error && (
        error.name === "RenderingCancelledException" || error.name === "AbortError"
    );
}

function PdfPage({
    pdfDoc,
    pageNumber,
    zoomLevel,
    containerWidth,
    scrollRootRef,
    renderLimit,
    pageSize,
    highlights,
    onPageElement,
    onPageSize,
}: {
    pdfDoc: pdfjsLib.PDFDocumentProxy;
    pageNumber: number;
    zoomLevel: number;
    containerWidth: number;
    scrollRootRef: RefObject<HTMLDivElement>;
    renderLimit: RenderLimit;
    pageSize?: PageSize;
    highlights: CitationPdfBBox[];
    onPageElement: (pageNumber: number, element: HTMLDivElement | null) => void;
    onPageSize: (pageNumber: number, size: PageSize) => void;
}) {
    const pageRef = useRef<HTMLDivElement | null>(null);
    const canvasRef = useRef<HTMLCanvasElement | null>(null);
    const [shouldRender, setShouldRender] = useState(pageNumber <= 2);
    const [rendered, setRendered] = useState(false);

    const handlePageRef = useCallback((element: HTMLDivElement | null) => {
        pageRef.current = element;
        onPageElement(pageNumber, element);
    }, [onPageElement, pageNumber]);

    useEffect(() => {
        const element = pageRef.current;
        const root = scrollRootRef.current;
        if (!element || !root || typeof IntersectionObserver === "undefined") {
            setShouldRender(true);
            return;
        }

        const observer = new IntersectionObserver(
            ([entry]) => setShouldRender(entry?.isIntersecting ?? false),
            {
                root,
                rootMargin: `${PDF_RENDER_OVERSCAN_PX}px 0px`,
                threshold: 0,
            }
        );
        observer.observe(element);
        return () => observer.disconnect();
    }, [scrollRootRef]);

    useEffect(() => {
        if (shouldRender) return;
        releaseCanvas(canvasRef.current);
        setRendered(false);
    }, [shouldRender]);

    useEffect(() => {
        if (!shouldRender || containerWidth <= 0) return;

        const controller = new AbortController();
        let renderTask: pdfjsLib.RenderTask | null = null;

        void renderLimit(async () => {
            if (controller.signal.aborted) return;
            const page = await pdfDoc.getPage(pageNumber);
            if (controller.signal.aborted) return;

            const baseViewport = page.getViewport({ scale: 1 });
            const availableWidth = Math.max(containerWidth - 32, 240);
            const displayScale = (availableWidth / baseViewport.width) * (zoomLevel / 100);
            const pixelRatio = Math.min(window.devicePixelRatio || 1, PDF_MAX_PIXEL_RATIO);
            const renderViewport = page.getViewport({ scale: displayScale * pixelRatio });
            const displaySize = {
                width: renderViewport.width / pixelRatio,
                height: renderViewport.height / pixelRatio,
                originalWidth: baseViewport.width,
            };
            onPageSize(pageNumber, displaySize);

            const canvas = canvasRef.current;
            const context = canvas?.getContext("2d");
            if (!canvas || !context || controller.signal.aborted) return;

            canvas.width = Math.ceil(renderViewport.width);
            canvas.height = Math.ceil(renderViewport.height);
            canvas.style.width = `${displaySize.width}px`;
            canvas.style.height = `${displaySize.height}px`;

            renderTask = page.render({ canvasContext: context, viewport: renderViewport });
            const cancelRender = () => renderTask?.cancel();
            controller.signal.addEventListener("abort", cancelRender, { once: true });
            try {
                await renderTask.promise;
                if (!controller.signal.aborted) setRendered(true);
            } finally {
                controller.signal.removeEventListener("abort", cancelRender);
            }
        }).catch((error: unknown) => {
            if (!isCancelledRender(error, controller.signal)) {
                console.warn(`Failed to render PDF page ${pageNumber}`, error);
            }
        });

        return () => {
            controller.abort();
            renderTask?.cancel();
        };
    }, [containerWidth, onPageSize, pageNumber, pdfDoc, renderLimit, shouldRender, zoomLevel]);

    const wrapperHeight = pageSize?.height ?? PDF_PAGE_PLACEHOLDER_HEIGHT;
    const wrapperWidth = pageSize?.width ?? Math.max(containerWidth - 32, 240);

    return (
        <div
            ref={handlePageRef}
            data-page={pageNumber}
            data-preview-watermark-surface
            className="relative overflow-hidden shadow-md bg-white flex items-start justify-center"
            style={{ minHeight: wrapperHeight, width: wrapperWidth }}
        >
            <canvas ref={canvasRef} />
            {!rendered && (
                <div className="absolute inset-0 flex items-center justify-center text-xs text-[#c9cdd4]">
                    {pageNumber}
                </div>
            )}
            {rendered && pageSize && highlights.length > 0 && (
                <svg
                    className="pointer-events-none absolute inset-0 z-10"
                    width={pageSize.width}
                    height={pageSize.height}
                >
                    {highlights.map((item, index) => {
                        const scale = pageSize.width / pageSize.originalWidth;
                        const [x1, y1, x2, y2] = item.bbox;
                        return (
                            <rect
                                key={`${item.page}-${index}-${x1}-${y1}`}
                                x={x1 * scale}
                                y={y1 * scale}
                                width={(x2 - x1) * scale}
                                height={(y2 - y1) * scale}
                                fill="rgba(255, 236, 61, 0.28)"
                                stroke="#F7BA1E"
                                strokeWidth={1}
                            />
                        );
                    })}
                </svg>
            )}
            {rendered ? <KnowledgePreviewWatermark /> : null}
        </div>
    );
}

export function PdfViewer({
    pdfDoc,
    zoomLevel,
    targetPage,
    highlightBboxes = [],
    targetBBox = null,
    onCurrentPageChange,
}: PdfViewerProps) {
    const localize = useLocalize();
    const scrollContainerRef = useRef<HTMLDivElement>(null);
    const pageRefs = useRef<Map<number, HTMLDivElement>>(new Map());
    const [pageSizes, setPageSizes] = useState<Record<number, PageSize>>({});
    const [containerWidth, setContainerWidth] = useState(0);
    const renderLimit = useMemo(() => pLimit(PDF_RENDER_CONCURRENCY), [pdfDoc]);
    const pageVisibilityRef = useRef<Map<number, number>>(new Map());
    const isProgrammaticScrollRef = useRef(false);
    const unlockScrollTimerRef = useRef<number | null>(null);
    const bboxInitialScrollKeyRef = useRef("");

    const getPageNumber = useCallback((page: number) => {
        if (!pdfDoc) return Math.max(1, page);
        if (page >= 0 && page + 1 <= pdfDoc.numPages) return page + 1;
        return Math.min(Math.max(1, page), pdfDoc.numPages);
    }, [pdfDoc]);

    const highlightsByPage = useMemo(() => {
        return highlightBboxes.reduce<Record<number, CitationPdfBBox[]>>((acc, item) => {
            const pageNum = getPageNumber(item.page);
            if (!acc[pageNum]) acc[pageNum] = [];
            acc[pageNum].push(item);
            return acc;
        }, {});
    }, [getPageNumber, highlightBboxes]);
    const targetBBoxPageNumber = targetBBox ? getPageNumber(targetBBox.page) : null;
    const targetBBoxPageSize = targetBBoxPageNumber ? pageSizes[targetBBoxPageNumber] : undefined;

    const handlePageElement = useCallback((pageNumber: number, element: HTMLDivElement | null) => {
        if (element) pageRefs.current.set(pageNumber, element);
        else pageRefs.current.delete(pageNumber);
    }, []);

    const handlePageSize = useCallback((pageNumber: number, size: PageSize) => {
        setPageSizes((current) => {
            const previous = current[pageNumber];
            if (
                previous
                && previous.width === size.width
                && previous.height === size.height
                && previous.originalWidth === size.originalWidth
            ) {
                return current;
            }
            return { ...current, [pageNumber]: size };
        });
    }, []);

    const lockProgrammaticScroll = useCallback(() => {
        isProgrammaticScrollRef.current = true;
        if (unlockScrollTimerRef.current !== null) {
            window.clearTimeout(unlockScrollTimerRef.current);
        }
        unlockScrollTimerRef.current = window.setTimeout(() => {
            isProgrammaticScrollRef.current = false;
        }, 700);
    }, []);

    useEffect(() => {
        if (!pdfDoc) return;
        const element = scrollContainerRef.current;
        if (!element) return;
        setContainerWidth(element.clientWidth);
        if (typeof ResizeObserver === "undefined") return;
        const observer = new ResizeObserver(([entry]) => {
            if (entry) setContainerWidth(entry.contentRect.width);
        });
        observer.observe(element);
        return () => observer.disconnect();
    }, [pdfDoc]);

    useEffect(() => {
        if (!targetPage) return;
        const pageElement = pageRefs.current.get(targetPage);
        if (!pageElement) return;
        lockProgrammaticScroll();
        pageElement.scrollIntoView({ behavior: "smooth", block: "start" });
    }, [lockProgrammaticScroll, targetPage]);

    useEffect(() => {
        if (!targetBBox) {
            bboxInitialScrollKeyRef.current = "";
            return;
        }
        const pageNumber = targetBBoxPageNumber;
        if (!pageNumber) return;
        const scrollKey = `${pageNumber}:${targetBBox.bbox.join(",")}`;
        if (bboxInitialScrollKeyRef.current === scrollKey) return;
        const pageElement = pageRefs.current.get(pageNumber);
        if (!pageElement) return;
        bboxInitialScrollKeyRef.current = scrollKey;
        lockProgrammaticScroll();
        pageElement.scrollIntoView({ behavior: "auto", block: "start" });
    }, [lockProgrammaticScroll, targetBBox, targetBBoxPageNumber]);

    useEffect(() => {
        if (!targetBBox || !scrollContainerRef.current) return;
        const pageNumber = targetBBoxPageNumber;
        if (!pageNumber) return;
        const pageElement = pageRefs.current.get(pageNumber);
        const pageSize = targetBBoxPageSize;
        if (!pageElement || !pageSize) return;

        const scale = pageSize.width / pageSize.originalWidth;
        const top = pageElement.offsetTop + targetBBox.bbox[1] * scale - 80;
        lockProgrammaticScroll();
        scrollContainerRef.current.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
    }, [lockProgrammaticScroll, targetBBox, targetBBoxPageNumber, targetBBoxPageSize]);

    useEffect(() => {
        return () => {
            renderLimit.clearQueue();
            if (unlockScrollTimerRef.current !== null) {
                window.clearTimeout(unlockScrollTimerRef.current);
            }
        };
    }, [renderLimit]);

    useEffect(() => {
        if (!pdfDoc || !scrollContainerRef.current) return;
        pageVisibilityRef.current.clear();

        const observer = new IntersectionObserver(
            (entries) => {
                if (isProgrammaticScrollRef.current) return;
                for (const entry of entries) {
                    const pageNumber = Number(entry.target.getAttribute("data-page"));
                    if (Number.isFinite(pageNumber)) {
                        pageVisibilityRef.current.set(pageNumber, entry.intersectionRatio);
                    }
                }
                let mostVisiblePage = 1;
                let maxRatio = 0;
                pageVisibilityRef.current.forEach((ratio, pageNumber) => {
                    if (ratio > maxRatio) {
                        maxRatio = ratio;
                        mostVisiblePage = pageNumber;
                    }
                });
                if (maxRatio > 0) onCurrentPageChange(mostVisiblePage);
            },
            {
                root: scrollContainerRef.current,
                threshold: [0, 0.25, 0.5, 0.75, 1],
            }
        );

        pageRefs.current.forEach((element) => observer.observe(element));
        return () => observer.disconnect();
    }, [pdfDoc, onCurrentPageChange]);

    if (!pdfDoc) {
        return (
            <div className="flex-1 flex items-center justify-center text-[#86909c]">
                {localize("com_knowledge.loading")}
            </div>
        );
    }

    return (
        <div ref={scrollContainerRef} className="flex-1 overflow-auto bg-[#fbfbfb]">
            <div className="flex flex-col items-center py-4 gap-3">
                {Array.from({ length: pdfDoc.numPages }, (_, index) => {
                    const pageNumber = index + 1;
                    return (
                        <PdfPage
                            key={pageNumber}
                            pdfDoc={pdfDoc}
                            pageNumber={pageNumber}
                            zoomLevel={zoomLevel}
                            containerWidth={containerWidth}
                            scrollRootRef={scrollContainerRef}
                            renderLimit={renderLimit}
                            pageSize={pageSizes[pageNumber]}
                            highlights={highlightsByPage[pageNumber] ?? []}
                            onPageElement={handlePageElement}
                            onPageSize={handlePageSize}
                        />
                    );
                })}
            </div>
        </div>
    );
}
