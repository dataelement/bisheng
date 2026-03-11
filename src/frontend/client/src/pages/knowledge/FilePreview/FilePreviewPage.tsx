/**
 * FilePreviewPage — business page for file preview.
 * Handles: AI assistant toggle, split-pane drag, and injects AI button into FilePreview via slot.
 * This is the route-level component; FilePreview itself is a reusable, decoupled component.
 */
import React, { useCallback, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { Button } from "~/components";
import { AiChatIcon } from "~/components/icons";
import { AiAssistantPanel } from "~/pages/Subscription/AiChat/AiAssistantPanel";
import { useResizablePanel } from "~/pages/Subscription/hooks/useResizablePanel";
import FilePreview from "./index";

const AI_SPLIT_STORAGE_KEY = "file-preview-ai-split-width";
const AI_MIN_LEFT = 480;
const AI_MIN_RIGHT = 360;

// 临时测试 URL map, 后续用 API 替换
const TEST_URLS: Record<string, string> = {
    pdf: "http://192.168.106.120:3002/bisheng/original/83735.pdf?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=minioadmin/20260309/us-east-1/s3/aws4_request&X-Amz-Date=20260309T101132Z&X-Amz-Expires=604800&X-Amz-SignedHeaders=host&X-Amz-Signature=11d2b51590a5483a17a4c55a23d40569bf0fa511dfed687534abd142fa55eefe",
    html: "http://192.168.106.120:3002/bisheng/original/83739.html?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=minioadmin%2F20260309%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Date=20260309T133231Z&X-Amz-Expires=604800&X-Amz-SignedHeaders=host&X-Amz-Signature=57435c890ab318d9af17e315934547bfedd36e4e276c5cd42d0e503cffd64abb",
    xlsx: "http://192.168.106.120:3002/bisheng/original/83355.xlsx?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=minioadmin%2F20260309%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Date=20260309T125433Z&X-Amz-Expires=604800&X-Amz-SignedHeaders=host&X-Amz-Signature=712f5f4a7973f16f077cf58da53182ec3e0fc5b17fbb2ba1c6bd2a79e78fdbe8",
    md: "http://192.168.106.120:3002/bisheng/original/83740.md?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=minioadmin%2F20260309%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Date=20260309T125708Z&X-Amz-Expires=604800&X-Amz-SignedHeaders=host&X-Amz-Signature=2dbf51c67b2a209ba0169c5c8191ab1f184bb8c6c63849349e57030f733189b0",
    txt: "http://192.168.106.120:3002/bisheng/original/83740.md?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=minioadmin%2F20260309%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Date=20260309T125708Z&X-Amz-Expires=604800&X-Amz-SignedHeaders=host&X-Amz-Signature=2dbf51c67b2a209ba0169c5c8191ab1f184bb8c6c63849349e57030f733189b0",
};

export default function FilePreviewPage() {
    const { fileId } = useParams<{ fileId: string }>();
    const [searchParams] = useSearchParams();
    const fileName = searchParams.get("name") || "未知文件";
    const fileType = searchParams.get("type") || "pdf";

    // TODO: 接口就绪后通过 fileId 获取真实 URL
    const fileUrl = TEST_URLS[fileType.toLowerCase()] || TEST_URLS.pdf;

    // --- AI Assistant state ---
    const [showAiAssistant, setShowAiAssistant] = useState(false);
    const splitContainerRef = useRef<HTMLDivElement>(null);

    const { leftWidth, setLeftWidth, isResizing, startResizing } = useResizablePanel({
        storageKey: AI_SPLIT_STORAGE_KEY,
        defaultWidth: 0,
        minLeftWidth: AI_MIN_LEFT,
        minRightWidth: AI_MIN_RIGHT,
        containerRef: splitContainerRef,
    });

    // Toggle AI assistant
    const handleToggleAiAssistant = useCallback(() => {
        setShowAiAssistant((prev) => {
            if (!prev && splitContainerRef.current) {
                const w = splitContainerRef.current.getBoundingClientRect().width;
                if (w < AI_MIN_LEFT + AI_MIN_RIGHT) return false;
                if (!leftWidth || leftWidth <= 0) {
                    setLeftWidth(Math.floor(w * 0.6));
                }
            }
            return !prev;
        });
    }, [leftWidth, setLeftWidth]);

    // AI assistant button injected into FilePreview's TopBar slot
    const aiButton = (
        <Button
            variant="ghost"
            onClick={handleToggleAiAssistant}
            className="h-8 px-1.5 text-sm gap-1 bg-gradient-to-br from-[#335CFF] to-[#7433FF] bg-clip-text text-transparent hover:text-transparent"
        >
            <AiChatIcon className="size-3.5" />
            AI 助手
        </Button>
    );

    return (
        <div ref={splitContainerRef} className="h-screen flex bg-white overflow-hidden">
            {/* Transparent overlay during drag — prevents iframe/children from stealing mouse events */}
            {isResizing && (
                <div className="fixed inset-0 z-50 cursor-col-resize" />
            )}

            {/* Left: FilePreview (pure component) */}
            <div
                style={{ width: showAiAssistant ? `${leftWidth}px` : "100%" }}
                className="h-full flex-shrink-0 overflow-hidden"
            >
                <FilePreview
                    fileName={fileName}
                    fileType={fileType}
                    fileUrl={fileUrl}
                    actions={aiButton}
                />
            </div>

            {/* Splitter */}
            {showAiAssistant && (
                <div
                    onMouseDown={startResizing}
                    className="group relative w-[1px] cursor-col-resize bg-[#e5e6eb] transition-all hover:w-1 hover:bg-primary active:w-1 active:bg-primary z-20 shrink-0"
                >
                    <div className="absolute inset-y-0 -left-1.5 -right-1.5 z-10" />
                </div>
            )}

            {/* Right: AI Assistant (full height) */}
            {showAiAssistant && (
                <div className="flex-1 h-full min-w-[360px] bg-white">
                    <AiAssistantPanel
                        features={{ tools: false, modelSelect: false, knowledgeBase: false, fileUpload: false }}
                        onClose={() => setShowAiAssistant(false)}
                        noBorder
                    />
                </div>
            )}
        </div>
    );
}
