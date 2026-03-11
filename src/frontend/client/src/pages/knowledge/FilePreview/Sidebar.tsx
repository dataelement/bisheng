import * as pdfjsLib from "pdfjs-dist";
import { useEffect, useRef, useCallback } from "react";
import { cn } from "~/utils";

interface SidebarProps {
    open: boolean;
    pdfDoc: pdfjsLib.PDFDocumentProxy | null;
    currentPage: number;
    onPageClick: (page: number) => void;
}

/**
 * 左侧缩略图 sidebar
 * 用 canvas 绘制每页的缩略图，高亮当前页
 */
export function Sidebar({ open, pdfDoc, currentPage, onPageClick }: SidebarProps) {
    const containerRef = useRef<HTMLDivElement>(null);

    // 当前高亮页滚动到可视区
    useEffect(() => {
        if (!open || !containerRef.current) return;
        const activeThumb = containerRef.current.querySelector(
            `[data-page="${currentPage}"]`
        );
        activeThumb?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }, [currentPage, open]);

    if (!open) return null;

    return (
        <div
            className="w-[160px] h-full border-r border-[#e5e6eb] bg-[#f7f8fa] overflow-y-auto flex-shrink-0 py-2 px-2 flex flex-col gap-2"
            ref={containerRef}
        >
            {pdfDoc &&
                Array.from({ length: pdfDoc.numPages }, (_, i) => (
                    <ThumbnailItem
                        key={i}
                        pdfDoc={pdfDoc}
                        pageNumber={i + 1}
                        isActive={currentPage === i + 1}
                        onClick={() => onPageClick(i + 1)}
                    />
                ))}
        </div>
    );
}

/**
 * 单个缩略图
 */
function ThumbnailItem({
    pdfDoc,
    pageNumber,
    isActive,
    onClick,
}: {
    pdfDoc: pdfjsLib.PDFDocumentProxy;
    pageNumber: number;
    isActive: boolean;
    onClick: () => void;
}) {
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const rendered = useRef(false);

    const render = useCallback(async () => {
        if (rendered.current || !canvasRef.current) return;
        rendered.current = true;

        try {
            const page = await pdfDoc.getPage(pageNumber);
            const viewport = page.getViewport({ scale: 1 });
            // 缩略图宽度固定 136px（160 - padding）
            const thumbWidth = 136;
            const scale = thumbWidth / viewport.width;
            const scaledViewport = page.getViewport({ scale });

            const canvas = canvasRef.current;
            canvas.width = scaledViewport.width;
            canvas.height = scaledViewport.height;
            canvas.style.width = `${thumbWidth}px`;
            canvas.style.height = `${scaledViewport.height}px`;

            const ctx = canvas.getContext("2d");
            if (!ctx) return;

            await page.render({
                canvasContext: ctx,
                viewport: scaledViewport,
            }).promise;
        } catch (e) {
            console.warn(`Failed to render thumbnail for page ${pageNumber}`, e);
        }
    }, [pdfDoc, pageNumber]);

    useEffect(() => {
        render();
    }, [render]);

    return (
        <div
            data-page={pageNumber}
            onClick={onClick}
            className={cn(
                "cursor-pointer rounded-md overflow-hidden border-2 transition-colors flex flex-col items-center",
                isActive
                    ? "border-[#165dff] shadow-sm"
                    : "border-transparent hover:border-[#c9cdd4]"
            )}
            style={{ minHeight: '200px' }}
        >
            <canvas ref={canvasRef} className="w-full block" />
            <span className={cn(
                "text-xs py-0.5",
                isActive ? "text-[#165dff] font-medium" : "text-[#86909c]"
            )}>
                {pageNumber}
            </span>
        </div>
    );
}
