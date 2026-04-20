import * as pdfjsLib from "pdfjs-dist";
import { useCallback, useEffect, useRef, useState } from "react";
import { useLocalize } from "~/hooks";

interface DocumentViewerProps {
    pdfDoc: pdfjsLib.PDFDocumentProxy | null;
    zoomLevel: number;
    targetPage: number | null;        // 当 TopBar 或 Sidebar 请求跳转时触发
    onCurrentPageChange: (page: number) => void;
}

/**
 * PDF 主文档渲染区域
 * - 每页用 canvas 绘制
 * - IntersectionObserver 追踪当前可见页
 * - zoomLevel 变化时重新绘制
 */
export function DocumentViewer({
    pdfDoc,
    zoomLevel,
    targetPage,
    onCurrentPageChange,
}: DocumentViewerProps) {
    const localize = useLocalize();
  const scrollContainerRef = useRef<HTMLDivElement>(null);
    const pageRefs = useRef<Map<number, HTMLDivElement>>(new Map());
    const [loading, setLoading] = useState(true);
    // 标记 targetPage 跳转是否进行中，避免 observer 回环
    const jumpingRef = useRef(false);

    // ===== 渲染所有页面 =====
    const renderAllPages = useCallback(async () => {
        if (!pdfDoc) return;

        setLoading(true);

        // 清空旧内容
        pageRefs.current.forEach((div) => {
            const canvasInside = div.querySelector("canvas");
            if (canvasInside) canvasInside.remove();
        });

        const scale = zoomLevel / 100;
        const devicePixelRatio = window.devicePixelRatio || 1;

        for (let i = 1; i <= pdfDoc.numPages; i++) {
            const page = await pdfDoc.getPage(i);
            const viewport = page.getViewport({ scale: scale * devicePixelRatio });
            const displayViewport = page.getViewport({ scale });

            const div = pageRefs.current.get(i);
            if (!div) continue;

            div.style.width = `${displayViewport.width}px`;
            div.style.height = `${displayViewport.height}px`;

            const canvas = document.createElement("canvas");
            canvas.width = viewport.width;
            canvas.height = viewport.height;
            canvas.style.width = `${displayViewport.width}px`;
            canvas.style.height = `${displayViewport.height}px`;

            const ctx = canvas.getContext("2d");
            if (!ctx) continue;

            div.appendChild(canvas);

            // 不 await render — 允许流式渲染
            page.render({ canvasContext: ctx, viewport }).promise.catch(() => { });
        }

        setLoading(false);
    }, [pdfDoc, zoomLevel]);

    useEffect(() => {
        renderAllPages();
    }, [renderAllPages]);

    // ===== IntersectionObserver — 追踪当前可见页 =====
    useEffect(() => {
        if (!pdfDoc || !scrollContainerRef.current) return;

        const observer = new IntersectionObserver(
            (entries) => {
                if (jumpingRef.current) return;
                // 找到可见面积最大的 entry
                let maxRatio = 0;
                let visiblePage = 1;
                entries.forEach((entry) => {
                    if (entry.intersectionRatio > maxRatio) {
                        maxRatio = entry.intersectionRatio;
                        visiblePage = Number(entry.target.getAttribute("data-page"));
                    }
                });
                if (maxRatio > 0) {
                    onCurrentPageChange(visiblePage);
                }
            },
            {
                root: scrollContainerRef.current,
                threshold: Array.from({ length: 11 }, (_, i) => i / 10),
            }
        );

        pageRefs.current.forEach((div) => observer.observe(div));

        return () => observer.disconnect();
    }, [pdfDoc, onCurrentPageChange, zoomLevel]);

    // ===== 跳转到指定页 =====
    useEffect(() => {
        if (targetPage === null || !scrollContainerRef.current) return;
        const div = pageRefs.current.get(targetPage);
        if (!div) return;

        jumpingRef.current = true;
        div.scrollIntoView({ behavior: "smooth", block: "start" });
        // 留一点时间让 smooth scroll 完成
        setTimeout(() => {
            jumpingRef.current = false;
        }, 600);
    }, [targetPage]);

    if (!pdfDoc) {
        return (
            <div className="flex-1 flex items-center justify-center text-[#86909c]">
                <div className="flex flex-col items-center gap-2">
                    <div className="animate-spin size-8 border-2 border-[#165dff] border-t-transparent rounded-full" />
                    <span className="text-sm">{localize("com_knowledge.loading")}</span>
                </div>
            </div>
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
                        className="bg-white shadow-md"
                        // 初始最小尺寸，待渲染后会被 JS 设置
                        style={{ minHeight: 200 }}
                    />
                ))}
            </div>
        </div>
    );
}
