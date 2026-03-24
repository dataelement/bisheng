import { useCallback, useEffect, useRef, useState } from "react";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";

const AI_MIN_LEFT = 480;
const AI_MIN_RIGHT = 360;

/**
 * Manages the AI assistant split-pane state: toggle, resize, and persistence.
 * Extracted from the root Knowledge component.
 */
export function useAiSplitPane() {
    const [showAiAssistant, setShowAiAssistant] = useState(false);
    const [aiSplitWidth, setAiSplitWidth] = useState<number>(() => {
        const saved = localStorage.getItem("knowledge-ai-split-ratio");
        return saved ? parseInt(saved, 10) : 0;
    });
    const [isResizingSplit, setIsResizingSplit] = useState(false);
    const splitContainerRef = useRef<HTMLDivElement>(null);
    const { showToast } = useToastContext();

    // ─── Toggle AI assistant panel ───────────────────────────────────────
    const handleToggleAiAssistant = useCallback(() => {
        setShowAiAssistant(prev => {
            if (!prev && splitContainerRef.current) {
                const containerWidth = splitContainerRef.current.getBoundingClientRect().width;
                if (containerWidth < AI_MIN_LEFT + AI_MIN_RIGHT) {
                    showToast({ message: "窗口宽度不足，无法打开 AI 助手", severity: NotificationSeverity.WARNING } as any);
                    return false;
                }
                if (!aiSplitWidth || aiSplitWidth <= 0) {
                    setAiSplitWidth(Math.floor(containerWidth * 0.6));
                }
            }
            return !prev;
        });
    }, [aiSplitWidth, showToast]);

    // ─── ResizeObserver: auto-close if container too narrow ──────────────
    useEffect(() => {
        if (!showAiAssistant || !splitContainerRef.current) return;
        const el = splitContainerRef.current;
        const ro = new ResizeObserver((entries) => {
            for (const entry of entries) {
                const w = entry.contentRect.width;
                if (w < AI_MIN_LEFT + AI_MIN_RIGHT) setShowAiAssistant(false);
                if (w - aiSplitWidth < AI_MIN_RIGHT) setAiSplitWidth(Math.max(AI_MIN_LEFT, w - AI_MIN_RIGHT));
            }
        });
        ro.observe(el);
        return () => ro.disconnect();
    }, [showAiAssistant, aiSplitWidth]);

    // ─── Splitter drag handlers ─────────────────────────────────────────
    const startSplitResize = useCallback((e: React.MouseEvent) => {
        e.preventDefault();
        setIsResizingSplit(true);
    }, []);

    const stopSplitResize = useCallback(() => {
        setIsResizingSplit(false);
        if (aiSplitWidth > 0) localStorage.setItem("knowledge-ai-split-ratio", aiSplitWidth.toString());
    }, [aiSplitWidth]);

    const resizeSplit = useCallback((e: MouseEvent) => {
        if (!isResizingSplit || !splitContainerRef.current) return;
        const rect = splitContainerRef.current.getBoundingClientRect();
        const newLeft = e.clientX - rect.left;
        if (newLeft >= AI_MIN_LEFT && (rect.width - newLeft) >= AI_MIN_RIGHT) setAiSplitWidth(newLeft);
    }, [isResizingSplit]);

    // Global mouse events for split resize
    useEffect(() => {
        if (isResizingSplit) {
            window.addEventListener("mousemove", resizeSplit);
            window.addEventListener("mouseup", stopSplitResize);
        } else {
            window.removeEventListener("mousemove", resizeSplit);
            window.removeEventListener("mouseup", stopSplitResize);
        }
        return () => {
            window.removeEventListener("mousemove", resizeSplit);
            window.removeEventListener("mouseup", stopSplitResize);
        };
    }, [isResizingSplit, resizeSplit, stopSplitResize]);

    return {
        showAiAssistant,
        setShowAiAssistant,
        aiSplitWidth,
        splitContainerRef,
        handleToggleAiAssistant,
        startSplitResize,
    };
}
