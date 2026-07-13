import pLimit from "p-limit";
import type * as pdfjsLib from "pdfjs-dist";
import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react";
import { cn } from "~/utils";

const THUMBNAIL_RENDER_CONCURRENCY = 2;
const THUMBNAIL_OVERSCAN_PX = 500;
const THUMBNAIL_WIDTH = 136;
const THUMBNAIL_MAX_PIXEL_RATIO = 1.5;

interface SidebarProps {
    open: boolean;
    pdfDoc: pdfjsLib.PDFDocumentProxy | null;
    currentPage: number;
    onPageClick: (page: number) => void;
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

export function Sidebar({ open, pdfDoc, currentPage, onPageClick }: SidebarProps) {
    const containerRef = useRef<HTMLDivElement>(null);
    const renderLimit = useMemo(() => pLimit(THUMBNAIL_RENDER_CONCURRENCY), [pdfDoc]);

    useEffect(() => {
        if (!open || !containerRef.current) return;
        const activeThumb = containerRef.current.querySelector(
            `[data-page="${currentPage}"]`
        );
        activeThumb?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }, [currentPage, open]);

    useEffect(() => () => renderLimit.clearQueue(), [renderLimit]);

    if (!open) return null;

    return (
        <div
            className="w-[160px] h-full border-r border-[#e5e6eb] bg-[#f7f8fa] overflow-y-auto flex-shrink-0 py-2 px-2 flex flex-col gap-2"
            ref={containerRef}
        >
            {pdfDoc && Array.from({ length: pdfDoc.numPages }, (_, index) => {
                const pageNumber = index + 1;
                return (
                    <ThumbnailItem
                        key={pageNumber}
                        pdfDoc={pdfDoc}
                        pageNumber={pageNumber}
                        isActive={currentPage === pageNumber}
                        scrollRootRef={containerRef}
                        renderLimit={renderLimit}
                        onClick={() => onPageClick(pageNumber)}
                    />
                );
            })}
        </div>
    );
}

function ThumbnailItem({
    pdfDoc,
    pageNumber,
    isActive,
    scrollRootRef,
    renderLimit,
    onClick,
}: {
    pdfDoc: pdfjsLib.PDFDocumentProxy;
    pageNumber: number;
    isActive: boolean;
    scrollRootRef: RefObject<HTMLDivElement>;
    renderLimit: RenderLimit;
    onClick: () => void;
}) {
    const itemRef = useRef<HTMLDivElement>(null);
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const [shouldRender, setShouldRender] = useState(pageNumber <= 3);
    const [rendered, setRendered] = useState(false);
    const [itemHeight, setItemHeight] = useState(200);

    useEffect(() => {
        const element = itemRef.current;
        const root = scrollRootRef.current;
        if (!element || !root || typeof IntersectionObserver === "undefined") {
            setShouldRender(true);
            return;
        }

        const observer = new IntersectionObserver(
            ([entry]) => setShouldRender(entry?.isIntersecting ?? false),
            {
                root,
                rootMargin: `${THUMBNAIL_OVERSCAN_PX}px 0px`,
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
        if (!shouldRender) return;

        const controller = new AbortController();
        let renderTask: pdfjsLib.RenderTask | null = null;

        void renderLimit(async () => {
            if (controller.signal.aborted) return;
            const page = await pdfDoc.getPage(pageNumber);
            if (controller.signal.aborted) return;

            const viewport = page.getViewport({ scale: 1 });
            const displayScale = THUMBNAIL_WIDTH / viewport.width;
            const pixelRatio = Math.min(window.devicePixelRatio || 1, THUMBNAIL_MAX_PIXEL_RATIO);
            const renderViewport = page.getViewport({ scale: displayScale * pixelRatio });
            const displayHeight = renderViewport.height / pixelRatio;
            setItemHeight(displayHeight + 24);

            const canvas = canvasRef.current;
            const context = canvas?.getContext("2d");
            if (!canvas || !context || controller.signal.aborted) return;

            canvas.width = Math.ceil(renderViewport.width);
            canvas.height = Math.ceil(renderViewport.height);
            canvas.style.width = `${THUMBNAIL_WIDTH}px`;
            canvas.style.height = `${displayHeight}px`;

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
                console.warn(`Failed to render thumbnail for page ${pageNumber}`, error);
            }
        });

        return () => {
            controller.abort();
            renderTask?.cancel();
        };
    }, [pageNumber, pdfDoc, renderLimit, shouldRender]);

    const handleClick = useCallback(() => onClick(), [onClick]);

    return (
        <div
            ref={itemRef}
            data-page={pageNumber}
            onClick={handleClick}
            className={cn(
                "cursor-pointer rounded-md overflow-hidden border-2 transition-colors flex flex-col items-center justify-center relative shrink-0",
                isActive
                    ? "border-[#165dff] shadow-sm"
                    : "border-transparent hover:border-[#c9cdd4]"
            )}
            style={{ height: itemHeight }}
        >
            <canvas ref={canvasRef} className="w-full block shrink-0" />
            {!rendered && (
                <div className="absolute inset-0 flex items-center justify-center bg-[#f2f3f5] text-xs text-[#c9cdd4]">
                    {pageNumber}
                </div>
            )}
            {rendered && !isActive && (
                <div className="absolute inset-0 bg-black/40 pointer-events-none" />
            )}
            <span className={cn(
                "relative z-10 text-xs py-0.5",
                isActive ? "text-[#165dff] font-medium" : "text-[#86909c]"
            )}>
                {pageNumber}
            </span>
        </div>
    );
}
