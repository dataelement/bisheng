/**
 * FilePreviewPage — business page for file preview.
 * Handles: AI assistant toggle, split-pane drag, and injects AI button into FilePreview via slot.
 * This is the route-level component; FilePreview itself is a reusable, decoupled component.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { Shield } from "lucide-react";
import { Outlined } from "bisheng-icons";
import { getFileDownloadApi, getFilePreviewApi } from "~/api/knowledge";
import { canOpenPermissionDialog, checkPermission } from "~/api/permission";
import { Button } from "~/components";
import { AiChatIcon } from "~/components/icons";
import { PermissionDialog } from "~/components/permission";
import { AiAssistantPanel } from "~/pages/Subscription/AiChat/AiAssistantPanel";
import { FileAiDock } from "~/pages/Subscription/AiChat/FileAiDock";
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
    const [canDownload, setCanDownload] = useState(false);
    const [canManagePermission, setCanManagePermission] = useState(false);
    const [permissionDialogOpen, setPermissionDialogOpen] = useState(false);

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

                const resolvedUrl = /^https?:\/\//.test(chosenUrl)
                    ? chosenUrl
                    : `${window.location.origin}${__APP_ENV__.BASE_URL}${chosenUrl}`;
                setFileUrl(resolvedUrl);
                setFileType(ext);
            })
            .catch((err) => console.error("Failed to load preview URL:", err))
            .finally(() => setLoading(false));
    }, [fileId, spaceId]);

    useEffect(() => {
        if (!fileId) {
            setCanDownload(false);
            return;
        }

        let cancelled = false;
        const controller = new AbortController();
        checkPermission("knowledge_file", fileId, "can_read", "download_file", {
            signal: controller.signal,
        })
            .then((result) => {
                if (!cancelled) setCanDownload(Boolean(result.allowed));
            })
            .catch(() => {
                if (!cancelled) setCanDownload(false);
            });

        return () => {
            cancelled = true;
            controller.abort();
        };
    }, [fileId]);

    useEffect(() => {
        if (!fileId) {
            setCanManagePermission(false);
            return;
        }

        let cancelled = false;
        const controller = new AbortController();
        canOpenPermissionDialog("knowledge_file", fileId, {
            signal: controller.signal,
        })
            .then((allowed) => {
                if (!cancelled) setCanManagePermission(Boolean(allowed));
            })
            .catch(() => {
                if (!cancelled) setCanManagePermission(false);
            });

        return () => {
            cancelled = true;
            controller.abort();
        };
    }, [fileId]);

    const handleDownloadFile = useCallback(async () => {
        if (!fileId || !spaceId || !canDownload) return;
        try {
            const downloadData = await getFileDownloadApi(spaceId, fileId);
            const downloadUrl = downloadData.original_url || downloadData.preview_url;
            if (!downloadUrl) return;

            const link = document.createElement("a");
            link.href = downloadUrl;
            link.download = fileName;
            link.target = "_blank";
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
        } catch (err) {
            console.error("Failed to download file:", err);
        }
    }, [canDownload, fileId, fileName, spaceId]);

    // --- AI Assistant state ---
    const [showAiAssistant, setShowAiAssistant] = useState(false);
    const hasAutoOpenedAiAssistant = useRef(false);
    const splitContainerRef = useRef<HTMLDivElement>(null);

    // Mobile layout (<md = 768px): AI assistant renders as full-screen overlay instead of split-pane.
    const [isMobile, setIsMobile] = useState(false);
    useEffect(() => {
        const mq = window.matchMedia("(max-width: 767px)");
        const update = () => setIsMobile(mq.matches);
        update();
        mq.addEventListener("change", update);
        return () => mq.removeEventListener("change", update);
    }, []);

    // Mobile only: drive the browser tab title to the file name, restoring the
    // previous title on unmount so navigating back doesn't leave it stuck.
    // (Desktop keeps FilePreview/index's own title sync.)
    useEffect(() => {
        if (!isMobile) return;
        const previousTitle = document.title;
        document.title = fileName;
        return () => {
            document.title = previousTitle;
        };
    }, [isMobile, fileName]);

    const { leftWidth, isResizing, startResizing } = useResizablePanel({
        storageKey: AI_SPLIT_STORAGE_KEY,
        defaultRatio: 0.6,
        minLeftWidth: AI_MIN_LEFT,
        minRightWidth: AI_MIN_RIGHT,
        containerRef: splitContainerRef,
    });

    useEffect(() => {
        if (loading || isMobile || showAiAssistant || hasAutoOpenedAiAssistant.current || !splitContainerRef.current) return;
        const w = splitContainerRef.current.getBoundingClientRect().width;
        if (w < AI_MIN_LEFT + AI_MIN_RIGHT) return;
        hasAutoOpenedAiAssistant.current = true;
        setShowAiAssistant(true);
    }, [loading, showAiAssistant, isMobile]);

    // Toggle AI assistant
    const handleToggleAiAssistant = useCallback(() => {
        setShowAiAssistant((prev) => {
            if (!prev && !isMobile && splitContainerRef.current) {
                const w = splitContainerRef.current.getBoundingClientRect().width;
                if (w < AI_MIN_LEFT + AI_MIN_RIGHT) return false;
            }
            return !prev;
        });
    }, [isMobile]);

    // Extra actions injected into FilePreview's TopBar slot.
    const topBarActions = (
        <>
            {canManagePermission && (
                <Button
                    variant="outline"
                    onClick={() => setPermissionDialogOpen(true)}
                    className="hidden h-8 gap-1 rounded-[6px] px-2 text-sm md:inline-flex"
                >
                    <Shield className="size-4 text-[#4e5969]" />
                    <span className="font-normal">{localize("com_permission.manage_permission")}</span>
                </Button>
            )}
            <Button
                variant="ghost"
                onClick={handleToggleAiAssistant}
                className="ai-btn-border-draw h-8 px-1.5 text-sm gap-1 rounded-[6px] hover:bg-transparent"
            >
                <span className="ai-btn-shimmer-overlay" />
                <AiChatIcon className="size-4 text-[#94BFFF]" />
                <span className="text-[#000D4D] font-normal">{localize("com_knowledge.ai_assistant")}</span>
            </Button>
        </>
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

    // === Mobile: bare preview + floating download button + bottom AI dock ===
    // Mirrors the channel ArticlePage H5 layout. No TopBar/header; the preview fills
    // the screen, controls float, and the file-chat dock pins to the bottom.
    if (isMobile) {
        return (
            <div className="relative h-screen w-screen overflow-hidden bg-white">
                {fileId && (
                    <PermissionDialog
                        open={permissionDialogOpen}
                        onOpenChange={setPermissionDialogOpen}
                        resourceType="knowledge_file"
                        resourceId={fileId}
                        resourceName={fileName}
                    />
                )}

                {/* Bare preview — header hidden, viewer fills the container. */}
                <div className="absolute inset-0">
                    <FilePreview
                        fileName={fileName}
                        fileType={fileType}
                        fileUrl={fileUrl}
                        conversionFailed={conversionFailed}
                        allowDownload={canDownload}
                        onDownloadFile={handleDownloadFile}
                        hideHeader
                    />
                </div>

                {/* Floating top-right download button — styled like ArticlePage's menu button. */}
                {canDownload && (
                    <button
                        type="button"
                        onClick={handleDownloadFile}
                        aria-label={localize("com_knowledge.download_file")}
                        className="fixed right-4 top-[calc(env(safe-area-inset-top,0px)+12px)] z-10 inline-flex size-9 items-center justify-center rounded-xl border border-black/5 bg-white/70 text-[#212121] shadow-[0_2px_8px_rgba(0,0,0,0.06)] backdrop-blur-md transition-colors hover:bg-white/85"
                    >
                        <Outlined.Download className="size-5" />
                    </button>
                )}

                {/* Bottom AI dock — file-scoped chat (absolute inset-x-0 bottom-0). */}
                {spaceId && fileId && <FileAiDock spaceId={spaceId} fileId={fileId} />}
            </div>
        );
    }

    return (
        <div ref={splitContainerRef} className="h-screen flex bg-white overflow-hidden">
            {fileId && (
                <PermissionDialog
                    open={permissionDialogOpen}
                    onOpenChange={setPermissionDialogOpen}
                    resourceType="knowledge_file"
                    resourceId={fileId}
                    resourceName={fileName}
                />
            )}

            {/* Transparent overlay during drag — prevents iframe/children from stealing mouse events */}
            {isResizing && (
                <div className="fixed inset-0 z-50 cursor-col-resize" />
            )}

            {/* Left: FilePreview (pure component) */}
            <div
                style={{ width: showAiAssistant && !isMobile ? `${leftWidth}px` : "100%" }}
                className="h-full flex-shrink-0 overflow-hidden"
            >
                <FilePreview
                    fileName={fileName}
                    fileType={fileType}
                    fileUrl={fileUrl}
                    actions={topBarActions}
                    conversionFailed={conversionFailed}
                    allowDownload={canDownload}
                    onDownloadFile={handleDownloadFile}
                />
            </div>

            {/* Splitter (desktop only) */}
            {showAiAssistant && !isMobile && (
                <div className="relative z-20 w-[1px] min-w-[1px] max-w-[1px] flex-none shrink-0">
                    <div
                        onMouseDown={startResizing}
                        className="group absolute inset-y-0 left-1/2 z-10 flex w-4 -translate-x-1/2 cursor-col-resize justify-center"
                    >
                        <div className="pointer-events-none w-px self-stretch bg-[#e5e6eb] transition-[width,background-color] duration-150 group-hover:w-1 group-hover:bg-primary group-active:w-1 group-active:bg-primary" />
                    </div>
                </div>
            )}

            {/* Right: AI Assistant — desktop: split column; mobile: full-screen overlay */}
            {showAiAssistant && (
                <div
                    className={
                        isMobile
                            ? "fixed inset-0 z-[60] flex h-full flex-col overflow-hidden bg-white"
                            : "flex h-full min-w-0 flex-1 flex-col overflow-hidden bg-white"
                    }
                >
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
