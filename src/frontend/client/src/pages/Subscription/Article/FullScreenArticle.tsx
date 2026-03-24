import { ArrowLeftIcon } from "lucide-react";
import React, { useEffect, useRef } from "react";
import { Button } from "~/components";
import { ArticleDetail } from "./ArticleDetail";
import { AiAssistantPanel } from "../AiChat/AiAssistantPanel";
import { useResizablePanel } from "../hooks/useResizablePanel";

const MIN_LEFT_WIDTH = 480;
const MIN_RIGHT_WIDTH = 360;

export default function FullScreenArticle({ article, onExit, showFullScreenBtn = true, onSwitchToFullScreen, showAiAssistant, setShowAiAssistant, onCloseAiAssistant }) {
    const containerRef = useRef<HTMLDivElement>(null);

    const { leftWidth, isResizing, startResizing } = useResizablePanel({
        storageKey: "ai-assistant-split-ratio",
        defaultRatio: 0.5,
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
            }
        }
    }, [showAiAssistant, setShowAiAssistant]);

    return (
        <div ref={containerRef} className="relative flex h-full w-full overflow-hidden bg-white">
            {/* Transparent overlay during drag — prevents children from stealing mouse events */}
            {isResizing && (
                <div className="fixed inset-0 z-50 cursor-col-resize" />
            )}

            <Button variant="outline" size="icon" className="absolute top-4 left-4 h-8 w-8 z-10" onClick={onExit}>
                <ArrowLeftIcon className="size-4" />
            </Button>

            {/* Left article area */}
            <div
                style={{ width: showAiAssistant ? `${leftWidth}px` : '100%' }}
                className="h-full flex-shrink-0 relative"
            >
                <div className={showAiAssistant ? 'h-full' : 'max-w-[1000px] mx-auto h-full'}>
                    <ArticleDetail
                        screenFull
                        aiAssistantOpen={showAiAssistant}
                        onAiAssistant={() => setShowAiAssistant(true)}
                        showFullScreenBtn={showFullScreenBtn}
                        onFullScreen={onExit}
                        onExitAiAssistant={showFullScreenBtn ? onSwitchToFullScreen : onCloseAiAssistant}
                        article={article}
                    />
                </div>
            </div>

            {/* Splitter — only when AI panel is open */}
            {showAiAssistant && (
                <div
                    onMouseDown={startResizing}
                    className="group relative w-[1px] cursor-col-resize bg-[#e5e6eb] transition-all hover:w-1 hover:bg-primary z-20"
                >
                    {/* Expand click area */}
                    <div className="absolute inset-y-0 -left-1.5 -right-1.5 z-10" />
                </div>
            )}

            {/* Right AI Assistant area */}
            {showAiAssistant && (
                <div className="flex-1 h-full min-w-[360px] bg-white">
                    <AiAssistantPanel
                        features={{ tools: false, modelSelect: false, knowledgeBase: false, fileUpload: false }}
                        articleDocId={article?.id}
                        onClose={onCloseAiAssistant} />
                </div>
            )}
        </div>
    );
};

