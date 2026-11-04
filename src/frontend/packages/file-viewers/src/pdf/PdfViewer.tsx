import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PdfPage } from './PdfPage';
import { pageIndexFromMetadata } from './coordinates';
import type * as pdfjsLib from "pdfjs-dist";

import type { PreviewPdfBBox as CitationPdfBBox } from '../types';

export interface PdfViewerProps {
    loadingText: string;
    onRenderError?: (error: unknown) => void;
    pdfDoc: pdfjsLib.PDFDocumentProxy | null;
    zoomLevel: number;
    targetPage: number | null;
    highlightBboxes?: CitationPdfBBox[];
    targetBBox?: CitationPdfBBox | null;
    onCurrentPageChange: (page: number) => void;
}

export function PdfViewer({
    pdfDoc,
    loadingText,
    onRenderError,
    zoomLevel,
    targetPage,
    highlightBboxes = [],
    targetBBox = null,
    onCurrentPageChange,
}: PdfViewerProps) {
    const reportedDocumentRef = useRef<pdfjsLib.PDFDocumentProxy | null>(null);
    const currentDocumentRef = useRef(pdfDoc);
    const scrollContainerRef = useRef<HTMLDivElement>(null);
    const pageRefs = useRef<Map<number, HTMLDivElement>>(new Map());
    const lastLocation = useRef<{ doc: typeof pdfDoc; bbox: typeof targetBBox; width: number } | null>(null);
    const [pageSizes, setPageSizes] = useState<Record<number, { width: number; height: number; originalWidth: number }>>({});
    // Measured width of the scroll viewport — used to fit-to-width when a PDF
    // page is wider than the container (e.g., a 1440px page in a 640px panel).
    const [containerWidth, setContainerWidth] = useState(0);

    useEffect(() => {
        currentDocumentRef.current = pdfDoc;
        return () => { currentDocumentRef.current = null; };
    }, [pdfDoc]);

    const getPageNumber = useCallback((page: number) => {
        const index = pageIndexFromMetadata(page, 0, pdfDoc?.numPages ?? 0);
        return index === null ? null : index + 1;
    }, [pdfDoc]);

    const highlightsByPage = useMemo(() => {
        return highlightBboxes.reduce<Record<number, CitationPdfBBox[]>>((acc, item) => {
            const pageNum = getPageNumber(item.page);
            if (pageNum === null) return acc;
            if (!acc[pageNum]) {
                acc[pageNum] = [];
            }
            acc[pageNum].push(item);
            return acc;
        }, {});
    }, [getPageNumber, highlightBboxes]);
    /** Latest intersection ratio per page — observer only reports changed targets per callback */
    const pageVisibilityRef = useRef<Map<number, number>>(new Map());
    const isProgrammaticScrollRef = useRef(false);
    const unlockScrollTimerRef = useRef<number | null>(null);

    // Track scroll viewport width — drives fit-to-width when the panel resizes
    // (e.g., AI assistant toggled, citation panel switches list/preview view).
    // Depends on pdfDoc so the observer attaches once the loading placeholder
    // is replaced by the real scroll container (the ref is null while loading).
    useEffect(() => {
        if (!pdfDoc) return;
        const el = scrollContainerRef.current;
        if (!el) return;
        setContainerWidth(el.clientWidth);
        if (typeof ResizeObserver === "undefined") return;
        const observer = new ResizeObserver((entries) => {
            for (const entry of entries) {
                setContainerWidth(entry.contentRect.width);
            }
        });
        observer.observe(el);
        return () => observer.disconnect();
    }, [pdfDoc]);

    const handleRenderError = useCallback((error: unknown) => {
        if (!pdfDoc || currentDocumentRef.current !== pdfDoc || reportedDocumentRef.current === pdfDoc) return;
        reportedDocumentRef.current = pdfDoc;
        onRenderError?.(error);
    }, [pdfDoc, onRenderError]);

    // Scroll to target page
    useEffect(() => {
        if (targetPage && pageRefs.current.has(targetPage)) {
            isProgrammaticScrollRef.current = true;
            if (unlockScrollTimerRef.current !== null) {
                window.clearTimeout(unlockScrollTimerRef.current);
            }
            pageRefs.current.get(targetPage)?.scrollIntoView({ behavior: "smooth", block: "start" });
            unlockScrollTimerRef.current = window.setTimeout(() => {
                isProgrammaticScrollRef.current = false;
            }, 700);
        }
    }, [targetPage]);

    // Scroll to the requested citation bbox after the page dimensions are known.
    useEffect(() => {
        if (!targetBBox || !scrollContainerRef.current) return;

        const pageNum = getPageNumber(targetBBox.page);
        if (pageNum === null) return;
        const pageEl = pageRefs.current.get(pageNum);
        const pageSize = pageSizes[pageNum];
        if (!pageEl || !pageSize) return;

        const previous = lastLocation.current;
        if (previous?.doc === pdfDoc && previous.bbox === targetBBox && previous.width === pageSize.width) return;
        lastLocation.current = { doc: pdfDoc, bbox: targetBBox, width: pageSize.width };
        const scale = pageSize.width / pageSize.originalWidth;
        const top = pageEl.offsetTop + targetBBox.bbox[1] * scale - 80;
        scrollContainerRef.current.scrollTo({
            top: Math.max(0, top),
            behavior: "smooth",
        });
    }, [getPageNumber, pageSizes, targetBBox, pdfDoc]);

    useEffect(() => {
        return () => {
            if (unlockScrollTimerRef.current !== null) {
                window.clearTimeout(unlockScrollTimerRef.current);
            }
        };
    }, []);

    // IntersectionObserver to track current visible page
    useEffect(() => {
        if (!pdfDoc || !scrollContainerRef.current) return;

        pageVisibilityRef.current.clear();

        const observer = new IntersectionObserver(
            (entries) => {
                if (isProgrammaticScrollRef.current) return;
                for (const entry of entries) {
                    const pageNum = Number(entry.target.getAttribute("data-page"));
                    if (!Number.isFinite(pageNum)) continue;
                    pageVisibilityRef.current.set(pageNum, entry.intersectionRatio);
                }
                let mostVisiblePage = 1;
                let maxRatio = 0;
                pageVisibilityRef.current.forEach((ratio, pageNum) => {
                    if (ratio > maxRatio) {
                        maxRatio = ratio;
                        mostVisiblePage = pageNum;
                    }
                });
                if (maxRatio > 0) {
                    onCurrentPageChange(mostVisiblePage);
                }
            },
            {
                root: scrollContainerRef.current,
                threshold: [0, 0.25, 0.5, 0.75, 1],
            }
        );

        pageRefs.current.forEach((el) => observer.observe(el));
        return () => observer.disconnect();
    }, [pdfDoc, onCurrentPageChange]);

    if (!pdfDoc) {
        return (
            <div className="flex-1 flex items-center justify-center text-text-3">
                {loadingText}</div>
        );
    }

    return (
        <div
            ref={scrollContainerRef}
            className="scrollbar-os flex-1 overflow-auto bg-fill-1"
        >
            <div className="flex flex-col items-center py-4 gap-3">
                {Array.from({ length: pdfDoc.numPages }, (_, i) => (
                    <div
                        key={i + 1}
                        data-page={i + 1}
                        data-document-canvas
                        ref={(el) => {
                            if (el) pageRefs.current.set(i + 1, el);
                        }}
                        className="relative shadow-md bg-white document-canvas"
                    >
                        <PdfPage pdfDoc={pdfDoc} pageIndex={i} width={containerWidth} zoomLevel={zoomLevel}
                            onError={handleRenderError}
                            onMetrics={metrics => setPageSizes(current => ({ ...current, [i + 1]: { width: metrics.width, height: metrics.height, originalWidth: metrics.originalWidth } }))}
                        />
                        {pageSizes[i + 1] && !!highlightsByPage[i + 1]?.length && (
                            <svg
                                className="pointer-events-none absolute inset-0 z-10"
                                width={pageSizes[i + 1].width}
                                height={pageSizes[i + 1].height}
                            >
                                {highlightsByPage[i + 1].map((item, index) => {
                                    const scale = pageSizes[i + 1].width / pageSizes[i + 1].originalWidth;
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
                    </div>
                ))}
            </div>
        </div>
    );
}
