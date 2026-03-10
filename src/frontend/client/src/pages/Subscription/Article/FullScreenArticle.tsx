import { ArrowLeftIcon } from "lucide-react";
import React, { useEffect, useRef } from "react";
import { Button } from "~/components";
import { ArticleDetail } from "./ArticleDetail";
import { AiAssistantPanel } from "../AiChat/AiAssistantPanel";
import { useResizablePanel } from "../hooks/useResizablePanel";

const MIN_LEFT_WIDTH = 480;
const MIN_RIGHT_WIDTH = 360;

export default function FullScreenArticle({ article, onExit, showAiAssistant, setShowAiAssistant }) {
    const containerRef = useRef<HTMLDivElement>(null);

    const { leftWidth, setLeftWidth, startResizing } = useResizablePanel({
        storageKey: "ai-assistant-split-ratio",
        defaultWidth: typeof window !== "undefined" ? window.innerWidth / 2 : 600,
        minLeftWidth: MIN_LEFT_WIDTH,
        minRightWidth: MIN_RIGHT_WIDTH,
        containerRef,
    });

    // Auto-close AI panel when container is too narrow
    useEffect(() => {
        if (showAiAssistant && containerRef.current) {
            const containerRect = containerRef.current.getBoundingClientRect();
            if (containerRect.width < MIN_LEFT_WIDTH + MIN_RIGHT_WIDTH) {
                setShowAiAssistant(false);
            } else if (leftWidth > containerRect.width - MIN_RIGHT_WIDTH) {
                setLeftWidth(containerRect.width - MIN_RIGHT_WIDTH);
            }
        }
    }, [showAiAssistant, leftWidth, setShowAiAssistant, setLeftWidth]);


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
                <AiAssistantPanel
                    features={{ tools: false, modelSelect: false, knowledgeBase: false, fileUpload: false }}
                    onClose={() => setShowAiAssistant(false)} />
            </div>
        </div >
    );
};
