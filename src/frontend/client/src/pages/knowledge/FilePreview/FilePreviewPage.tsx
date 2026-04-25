/**
 * FilePreviewPage — business page for file preview.
 * Handles: AI assistant toggle, split-pane drag, and injects AI button into FilePreview via slot.
 * This is the route-level component; FilePreview itself is a reusable, decoupled component.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { getFilePreviewApi } from "~/api/knowledge";
import { Button } from "~/components";
import { AiChatIcon } from "~/components/icons";
import { AiAssistantPanel } from "~/pages/Subscription/AiChat/AiAssistantPanel";
import { useResizablePanel } from "~/pages/Subscription/hooks/useResizablePanel";
import FilePreview from "./index";
import { useLocalize } from "~/hooks";

const AI_SPLIT_STORAGE_KEY = "file-preview-ai-split-width";
const AI_MIN_LEFT = 480;
const AI_MIN_RIGHT = 360;

/**
 * Extract file extension from a URL path, ignoring query parameters.
 * e.g. "/bisheng/preview/84296.html?X-Amz-Algorithm=..." → "html"
 */
function extractExtFromUrl(url: string, fallback: string): string {
    try {
        // Strip query string and hash
        const pathOnly = url.split('?')[0].split('#')[0];
        const lastSegment = pathOnly.split('/').pop() || '';
        const dotIndex = lastSegment.lastIndexOf('.');
        if (dotIndex >= 0 && dotIndex < lastSegment.length - 1) {
            return lastSegment.substring(dotIndex + 1).toLowerCase();
        }
    } catch {
        // Parsing failed, use fallback
    }
    return fallback;
}

export default function FilePreviewPage() {
    const localize = useLocalize();
    const { fileId } = useParams<{ fileId: string }>();
    const [searchParams] = useSearchParams();
    const fileName = searchParams.get("name") || localize("com_knowledge.unknown_file");
    const spaceId = searchParams.get("spaceId") || "";

    // Fetch real preview URL via API
    const [fileUrl, setFileUrl] = useState<string>("");
    const [fileType, setFileType] = useState<string>("pdf");
    const [loading, setLoading] = useState(true);
    const [conversionFailed, setConversionFailed] = useState(false);

    useEffect(() => {
        if (!fileId || !spaceId) { setLoading(false); return; }
        setLoading(true);
        setConversionFailed(false);
        getFilePreviewApi(spaceId, fileId)
            .then((data) => {
                // Prefer preview_url, fallback to original_url
                const chosenUrl = data.preview_url || data.original_url;
                if (!chosenUrl) {
                    setFileUrl("");
                    return;
                }

                const ext = extractExtFromUrl(chosenUrl, "pdf");

                // If backend didn't produce a preview_url and the original is ppt/pptx,
                // the raw file can't be rendered — mark as conversion failed.
                if (!data.preview_url && /^pptx?$/.test(ext)) {
                    setConversionFailed(true);
                    setFileUrl("");
                    setFileType(ext);
                    return;
                }

                setFileUrl(`${window.location.origin}${__APP_ENV__.BASE_URL}${chosenUrl}`);
                setFileType(ext);
            })
            .catch((err) => console.error("Failed to load preview URL:", err))
            .finally(() => setLoading(false));
    }, [fileId, spaceId]);

    // --- AI Assistant state ---
    const [showAiAssistant, setShowAiAssistant] = useState(false);
    const hasAutoOpenedAiAssistant = useRef(false);
    const splitContainerRef = useRef<HTMLDivElement>(null);

    const { leftWidth, isResizing, startResizing } = useResizablePanel({
        storageKey: AI_SPLIT_STORAGE_KEY,
        defaultRatio: 0.6,
        minLeftWidth: AI_MIN_LEFT,
        minRightWidth: AI_MIN_RIGHT,
        containerRef: splitContainerRef,
    });

    useEffect(() => {
        if (loading || showAiAssistant || hasAutoOpenedAiAssistant.current || !splitContainerRef.current) return;
        hasAutoOpenedAiAssistant.current = true;
        setShowAiAssistant(true);
    }, [loading, showAiAssistant]);

    // Toggle AI assistant
    const handleToggleAiAssistant = useCallback(() => {
        setShowAiAssistant((prev) => {
            if (!prev && splitContainerRef.current) {
                const w = splitContainerRef.current.getBoundingClientRect().width;
                if (w < AI_MIN_LEFT + AI_MIN_RIGHT) return false;
            }
            return !prev;
        });
    }, []);

    // AI assistant button injected into FilePreview's TopBar slot
    const aiButton = (
        <Button
            variant="ghost"
            onClick={handleToggleAiAssistant}
            className="ai-btn-border-draw h-8 px-1.5 text-sm gap-1 rounded-[6px] hover:bg-transparent"
        >
            <span className="ai-btn-shimmer-overlay" />
            <AiChatIcon className="size-4 text-[#94BFFF]" />
            <span className="text-[#000D4D] font-normal">{localize("com_knowledge.ai_assistant")}</span>
        </Button>
    );

    // Loading state while fetching preview URL
    if (loading) {
        return (
            <div className="h-screen flex items-center justify-center bg-white">
                <div className="text-[#86909c]">{localize("com_knowledge.loading")}</div>
            </div>
        );
    }

    // No URL available (skip this guard for pptx conversion failure — handled by FilePreview)
    if (!fileUrl && !conversionFailed) {
        return (
            <div className="h-screen flex items-center justify-center bg-white">
                <div className="text-[#86909c]">{localize("com_knowledge.fetch_preview_link_failed")}</div>
            </div>
        );
    }

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
                    conversionFailed={conversionFailed}
                />
            </div>

            {/* Splitter */}
            {showAiAssistant && (
                <div className="relative z-20 w-[1px] min-w-[1px] max-w-[1px] flex-none shrink-0">
                    <div
                        onMouseDown={startResizing}
                        className="group absolute inset-y-0 left-1/2 z-10 flex w-4 -translate-x-1/2 cursor-col-resize justify-center"
                    >
                        <div className="pointer-events-none w-px self-stretch bg-[#e5e6eb] transition-[width,background-color] duration-150 group-hover:w-1 group-hover:bg-primary group-active:w-1 group-active:bg-primary" />
                    </div>
                </div>
            )}

            {/* Right: AI Assistant (full height) */}
            {showAiAssistant && (
                <div className="flex-1 h-full min-w-[360px] bg-white">
                    <AiAssistantPanel
                        features={{ tools: false, modelSelect: true, knowledgeBase: false, fileUpload: false }}
                        onClose={() => setShowAiAssistant(false)}
                        noBorder
                        fileChat={spaceId && fileId ? { spaceId, fileId } : undefined}
                    />
                </div>
            )}
        </div>
    );
}
