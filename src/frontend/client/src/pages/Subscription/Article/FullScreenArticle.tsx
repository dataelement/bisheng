import { ArrowLeftIcon } from "lucide-react";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "~/components";
import { ArticleDetail } from "./ArticleDetail";
import { AiAssistantPanel } from "../AiChat/AiAssistantPanel";

const STORAGE_KEY = "ai-assistant-split-ratio";
const MIN_LEFT_WIDTH = 480;
const MIN_RIGHT_WIDTH = 360;

export default function FullScreenArticle({ article, onExit, showAiAssistant, setShowAiAssistant }) {
    const containerRef = useRef<HTMLDivElement>(null);
    const [leftWidth, setLeftWidth] = useState<number>(() => {
        const saved = localStorage.getItem(STORAGE_KEY);
        return saved ? parseInt(saved, 10) : window.innerWidth / 2;
    });
    const [isResizing, setIsResizing] = useState(false);

    // Start drag
    const startResizing = useCallback((e: React.MouseEvent) => {
        e.preventDefault();
        setIsResizing(true);
    }, []);

    // Stop drag
    const stopResizing = useCallback(() => {
        setIsResizing(false);
        localStorage.setItem(STORAGE_KEY, leftWidth.toString());
    }, [leftWidth]);

    // Dragging
    const resize = useCallback((e: MouseEvent) => {
        if (!isResizing || !containerRef.current) return;

        const containerRect = containerRef.current.getBoundingClientRect();
        const newLeftWidth = e.clientX - containerRect.left;
        const availableWidth = containerRect.width;

        // If total width is insufficient to meet left and right min width, force close AI Assistant (can be handled via CSS or resize logic, but temporarily handling as auto-boundary)
        if (availableWidth < MIN_LEFT_WIDTH + MIN_RIGHT_WIDTH) {
            setShowAiAssistant(false);
            stopResizing();
            return;
        }

        if (newLeftWidth >= MIN_LEFT_WIDTH && (availableWidth - newLeftWidth) >= MIN_RIGHT_WIDTH) {
            setLeftWidth(newLeftWidth);
        }
    }, [isResizing, setShowAiAssistant, stopResizing]);

    useEffect(() => {
        if (isResizing) {
            window.addEventListener("mousemove", resize);
            window.addEventListener("mouseup", stopResizing);
        } else {
            window.removeEventListener("mousemove", resize);
            window.removeEventListener("mouseup", stopResizing);
        }
        return () => {
            window.removeEventListener("mousemove", resize);
            window.removeEventListener("mouseup", stopResizing);
        };
    }, [isResizing, resize, stopResizing]);

    // Update width initially if out of bounds
    useEffect(() => {
        if (showAiAssistant && containerRef.current) {
            const containerRect = containerRef.current.getBoundingClientRect();
            if (containerRect.width < MIN_LEFT_WIDTH + MIN_RIGHT_WIDTH) {
                setShowAiAssistant(false);
            } else if (leftWidth > containerRect.width - MIN_RIGHT_WIDTH) {
                setLeftWidth(containerRect.width - MIN_RIGHT_WIDTH);
            }
        }
    }, [showAiAssistant, leftWidth, setShowAiAssistant]);


    if (!showAiAssistant) {
        return (
            <div className="relative h-full">
                <Button variant="outline" size="icon" className="absolute top-4 left-4 h-8 w-8 z-10" onClick={onExit}>
                    <ArrowLeftIcon className="size-4" />
                </Button>
                <div className="max-w-[1000px] mx-auto h-full relative">
                    <ArticleDetail
                        screenFull
                        aiAssistantOpen={showAiAssistant}
                        onAiAssistant={() => setShowAiAssistant(true)}
                        onFullScreen={onExit}
                        article={article}
                    />
                </div>
            </div>
        );
    }

    return (
        <div ref={containerRef} className="relative flex h-full w-full overflow-hidden bg-white">
            <Button variant="outline" size="icon" className="absolute top-4 left-4 h-8 w-8 z-10" onClick={onExit}>
                <ArrowLeftIcon className="size-4" />
            </Button>

            {/* Left article area */}
            <div
                style={{ width: `${leftWidth}px` }}
                className="h-full flex-shrink-0 relative"
            >
                {/* Wrap in content div to pad the exit button area slightly if needed, but ArticleDetail handles its own padding */}
                <ArticleDetail
                    screenFull
                    aiAssistantOpen={showAiAssistant}
                    onFullScreen={onExit}
                    onExitAiAssistant={() => setShowAiAssistant(false)}
                    article={article}
                />
            </div>

            {/* Splitter */}
            <div
                onMouseDown={startResizing}
                className="group relative w-[1px] cursor-col-resize bg-[#e5e6eb] transition-all hover:w-1 hover:bg-primary z-20"
            >
                {/* Expand click area */}
                <div className="absolute inset-y-0 -left-1.5 -right-1.5 z-10" />
            </div>

            {/* Right AI Assistant area */}
            <div className="flex-1 h-full min-w-[360px] bg-white">
                <AiAssistantPanel onClose={() => setShowAiAssistant(false)} />
            </div>
        </div >
    );
};
