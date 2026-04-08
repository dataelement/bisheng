import React, { useState, useEffect, useRef, useCallback } from "react";
import { Article, Channel } from "~/api/channels";
import { ArticleList } from "./ArticleList/ArticleList";
import { ArticleDetail } from "./Article/ArticleDetail";

interface ChannelLayoutProps {
    channel: Channel;
    onFullScreen?: (article: Article, aiAssistant?: boolean) => void;
}

const STORAGE_KEY = "article-split-ratio";
const MIN_LEFT_WIDTH = 480;
const MIN_RIGHT_WIDTH = 480;

export function ChannelLayout({ channel, onFullScreen }: ChannelLayoutProps) {
    const [selectedArticle, setSelectedArticle] = useState<Article | null>(null);
    // Initial width ratio, default to half if no record exists
    const [leftWidth, setLeftWidth] = useState<number>(() => {
        const saved = localStorage.getItem(STORAGE_KEY);
        return saved ? parseInt(saved, 10) : 600; // default value
    });
    const [isResizing, setIsResizing] = useState(false);
    const containerRef = useRef<HTMLDivElement>(null);

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

        // Restrict minimum width
        if (newLeftWidth >= MIN_LEFT_WIDTH && (containerRect.width - newLeftWidth) >= MIN_RIGHT_WIDTH) {
            setLeftWidth(newLeftWidth);
        }
    }, [isResizing]);

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

    return (
        <div ref={containerRef} className="flex h-full w-full overflow-hidden bg-white">
            {/* Left list area */}
            <div
                style={{ width: selectedArticle ? `${leftWidth}px` : '100%' }}
                className="h-full flex-shrink-0"
            >
                <ArticleList
                    channel={channel}
                    onArticleSelect={setSelectedArticle}
                    selectedArticleId={selectedArticle?.id}
                />
            </div>

            {/* Splitter - only shown when an article is selected */}
            {selectedArticle && (
                <div
                    onMouseDown={startResizing}
                    className={`group relative w-[1px] cursor-col-resize bg-[#f2f3f5] transition-all hover:w-1 hover:bg-primary active:w-1 active:bg-primary`}
                >
                    {/* Expand click area */}
                    <div className="absolute inset-y-0 -left-1 -right-1 z-10" />
                </div>
            )}

            {/* Right detail area */}
            {selectedArticle && (
                <div className="flex-1 h-full min-w-[480px] bg-white">
                    <ArticleDetail
                        article={selectedArticle}
                        onFullScreen={() => onFullScreen?.(selectedArticle, false)}
                        onAiAssistant={() => onFullScreen?.(selectedArticle, true)}
                    />
                </div>
            )}
        </div>
    );
}