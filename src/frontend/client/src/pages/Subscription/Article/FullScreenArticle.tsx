import { ArrowLeftIcon } from "lucide-react";
import React, { useEffect, useRef } from "react";
import { Button } from "~/components";
import { usePrefersMobileLayout } from "~/hooks";
import { ArticleDetail } from "./ArticleDetail";
import { AiAssistantPanel } from "../AiChat/AiAssistantPanel";
import { useResizablePanel } from "../hooks/useResizablePanel";

const MIN_LEFT_WIDTH = 480;
const MIN_RIGHT_WIDTH = 360;

export default function FullScreenArticle({ article, onExit, showFullScreenBtn = true, onSwitchToFullScreen, showAiAssistant, setShowAiAssistant, onCloseAiAssistant }) {
    const containerRef = useRef<HTMLDivElement>(null);
    const isH5 = usePrefersMobileLayout();

    const { leftWidth, isResizing, startResizing } = useResizablePanel({
        storageKey: "ai-assistant-split-ratio",
        defaultRatio: 0.5,
        minLeftWidth: MIN_LEFT_WIDTH,
        minRightWidth: MIN_RIGHT_WIDTH,
        containerRef,
    });

    // Auto-close AI panel when container is too narrow
    useEffect(() => {
        if (isH5) return;
        if (showAiAssistant && containerRef.current) {
            const containerRect = containerRef.current.getBoundingClientRect();
            if (containerRect.width < MIN_LEFT_WIDTH + MIN_RIGHT_WIDTH) {
                setShowAiAssistant(false);
            }
        }
    }, [showAiAssistant, setShowAiAssistant, isH5]);

    const showMobileAiOnly = isH5 && showAiAssistant;

    return (
        <div ref={containerRef} className="relative flex h-full w-full overflow-hidden bg-white">
            {/* Transparent overlay during drag — prevents children from stealing mouse events */}
            {isResizing && (
                <div className="fixed inset-0 z-50 cursor-col-resize" />
            )}

            {!isH5 && (
                <Button
                    variant="outline"
                    size="icon"
                    className="absolute left-4 top-4 z-10 h-8 w-8"
                    onClick={onExit}
                >
                    <ArrowLeftIcon className="size-4" />
                </Button>
            )}

            {/* Left article area */}
            {!showMobileAiOnly && (
                <div
                    style={{ width: showAiAssistant ? `${leftWidth}px` : '100%' }}
                    className="h-full flex-shrink-0 relative"
                >
                    <div className={showAiAssistant ? 'h-full' : 'max-w-[1000px] mx-auto h-full'}>
                        <ArticleDetail
                            screenFull
                            aiAssistantOpen={showAiAssistant}
                            onBack={isH5 ? onExit : undefined}
                            onAiAssistant={() => setShowAiAssistant(true)}
                            showFullScreenBtn={showFullScreenBtn}
                            onFullScreen={onExit}
                            onExitAiAssistant={showFullScreenBtn ? onSwitchToFullScreen : onCloseAiAssistant}
                            article={article}
                        />
                    </div>
                </div>
            )}

            {/* Splitter — only when AI panel is open */}
            {showAiAssistant && !isH5 && (
                <div className="relative z-20 w-[1px] min-w-[1px] max-w-[1px] flex-none shrink-0">
                    <div
                        onMouseDown={startResizing}
                        className="group absolute inset-y-0 left-1/2 z-10 flex w-4 -translate-x-1/2 cursor-col-resize justify-center"
                    >
                        <div className="pointer-events-none w-px self-stretch bg-[#e5e6eb] transition-[width,background-color] duration-150 group-hover:w-1 group-hover:bg-primary group-active:w-1 group-active:bg-primary" />
                    </div>
                </div>
            )}

            {/* Right AI Assistant area */}
            {showAiAssistant && !isH5 && (
                <div className="flex-1 h-full min-w-[360px] bg-white">
                    <AiAssistantPanel
                        features={{ tools: false, knowledgeBase: false, fileUpload: false }}
                        articleDocId={article?.id}
                        onClose={onCloseAiAssistant} />
                </div>
            )}

            {showMobileAiOnly && (
                <div className="h-full w-full bg-white">
                    <AiAssistantPanel
                        features={{ tools: false, modelSelect: false, knowledgeBase: false, fileUpload: false }}
                        articleDocId={article?.id}
                        onClose={onCloseAiAssistant}
                    />
                </div>
            )}
        </div>
    );
};
