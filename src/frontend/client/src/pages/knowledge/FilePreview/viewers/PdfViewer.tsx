import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type * as pdfjsLib from "pdfjs-dist";
import { useLocalize } from "~/hooks";
import type { CitationPdfBBox } from "~/components/Chat/Messages/Content/citationUtils";

interface PdfViewerProps {
    pdfDoc: pdfjsLib.PDFDocumentProxy | null;
    zoomLevel: number;
    targetPage: number | null;
    highlightBboxes?: CitationPdfBBox[];
    targetBBox?: CitationPdfBBox | null;
    onCurrentPageChange: (page: number) => void;
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
    const canvasRefs = useRef<Map<number, HTMLCanvasElement>>(new Map());
    const renderingPages = useRef<Set<number>>(new Set());
    const [pageSizes, setPageSizes] = useState<Record<number, { width: number; height: number; originalWidth: number }>>({});

    const getPageNumber = useCallback((page: number) => {
        if (!pdfDoc) return Math.max(1, page);
        // Citation bbox metadata follows the existing PreviewFile convention: page is zero-based.
        if (page >= 0 && page + 1 <= pdfDoc.numPages) return page + 1;
        return Math.min(Math.max(1, page), pdfDoc.numPages);
    }, [pdfDoc]);

    const highlightsByPage = useMemo(() => {
        return highlightBboxes.reduce<Record<number, CitationPdfBBox[]>>((acc, item) => {
            const pageNum = getPageNumber(item.page);
            if (!acc[pageNum]) {
                acc[pageNum] = [];
            }
            acc[pageNum].push(item);
            return acc;
        }, {});
    }, [getPageNumber, highlightBboxes]);

    // Render a single PDF page to canvas
    const renderPage = useCallback(
        async (pageNum: number) => {
            if (!pdfDoc || renderingPages.current.has(pageNum)) return;
            const canvas = canvasRefs.current.get(pageNum);
            if (!canvas) return;

            renderingPages.current.add(pageNum);
            try {
                const page = await pdfDoc.getPage(pageNum);
                const scale = zoomLevel / 100;
                const viewport = page.getViewport({ scale: scale * 1.5 });
                const baseViewport = page.getViewport({ scale: 1 });

                canvas.width = viewport.width;
                canvas.height = viewport.height;
                canvas.style.width = `${viewport.width / 1.5}px`;
                canvas.style.height = `${viewport.height / 1.5}px`;
                setPageSizes((current) => ({
                    ...current,
                    [pageNum]: {
                        width: viewport.width / 1.5,
                        height: viewport.height / 1.5,
                        originalWidth: baseViewport.width,
                    },
                }));

                const ctx = canvas.getContext("2d");
                if (ctx) {
                    await page.render({ canvasContext: ctx, viewport }).promise;
                }
            } finally {
                renderingPages.current.delete(pageNum);
            }
        },
        [pdfDoc, zoomLevel]
    );

    // Re-render all visible pages on zoom change
    useEffect(() => {
        if (!pdfDoc) return;
        for (let i = 1; i <= pdfDoc.numPages; i++) {
            renderPage(i);
        }
    }, [pdfDoc, zoomLevel, renderPage]);

    // Scroll to target page
    useEffect(() => {
        if (targetPage && pageRefs.current.has(targetPage)) {
            pageRefs.current.get(targetPage)?.scrollIntoView({ behavior: "smooth", block: "start" });
        }
    }, [targetPage]);

    // Scroll to the requested citation bbox after the page dimensions are known.
    useEffect(() => {
        if (!targetBBox || !scrollContainerRef.current) return;

        const pageNum = getPageNumber(targetBBox.page);
        const pageEl = pageRefs.current.get(pageNum);
        const pageSize = pageSizes[pageNum];
        if (!pageEl || !pageSize) return;

        const scale = pageSize.width / pageSize.originalWidth;
        const top = pageEl.offsetTop + targetBBox.bbox[1] * scale - 80;
        scrollContainerRef.current.scrollTo({
            top: Math.max(0, top),
            behavior: "smooth",
        });
    }, [getPageNumber, pageSizes, targetBBox]);

    // IntersectionObserver to track current visible page
    useEffect(() => {
        if (!pdfDoc || !scrollContainerRef.current) return;

        const observer = new IntersectionObserver(
            (entries) => {
                let mostVisiblePage = 1;
                let maxRatio = 0;
                entries.forEach((entry) => {
                    const pageNum = Number(entry.target.getAttribute("data-page"));
                    if (entry.intersectionRatio > maxRatio) {
                        maxRatio = entry.intersectionRatio;
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
            <div className="flex-1 flex items-center justify-center text-[#86909c]">
                {localize("com_knowledge.loading")}</div>
        );
    }

    return (
        <div
            ref={scrollContainerRef}
            className="flex-1 overflow-auto bg-[#fbfbfb]"
        >
            <div className="flex flex-col items-center py-4 gap-3">
                {Array.from({ length: pdfDoc.numPages }, (_, i) => (
                    <div
                        key={i + 1}
                        data-page={i + 1}
                        ref={(el) => {
                            if (el) pageRefs.current.set(i + 1, el);
                        }}
                        className="relative shadow-md bg-white"
                    >
                        <canvas
                            ref={(el) => {
                                if (el) canvasRefs.current.set(i + 1, el);
                            }}
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
