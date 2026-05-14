import { useCallback, useEffect, useRef } from "react";
import type * as pdfjsLib from "pdfjs-dist";
import { useLocalize } from "~/hooks";

interface PdfViewerProps {
    pdfDoc: pdfjsLib.PDFDocumentProxy | null;
    zoomLevel: number;
    targetPage: number | null;
    onCurrentPageChange: (page: number) => void;
}

export function PdfViewer({
    pdfDoc,
    zoomLevel,
    targetPage,
    onCurrentPageChange,
}: PdfViewerProps) {
    const localize = useLocalize();
    const scrollContainerRef = useRef<HTMLDivElement>(null);
    const pageRefs = useRef<Map<number, HTMLDivElement>>(new Map());
    const canvasRefs = useRef<Map<number, HTMLCanvasElement>>(new Map());
    const renderingPages = useRef<Set<number>>(new Set());
    /** Latest intersection ratio per page — observer only reports changed targets per callback */
    const pageVisibilityRef = useRef<Map<number, number>>(new Map());
    const isProgrammaticScrollRef = useRef(false);
    const unlockScrollTimerRef = useRef<number | null>(null);

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

                canvas.width = viewport.width;
                canvas.height = viewport.height;
                canvas.style.width = `${viewport.width / 1.5}px`;
                canvas.style.height = `${viewport.height / 1.5}px`;

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
                        className="shadow-md bg-white"
                    >
                        <canvas
                            ref={(el) => {
                                if (el) canvasRefs.current.set(i + 1, el);
                            }}
                        />
                    </div>
                ))}
            </div>
        </div>
    );
}
