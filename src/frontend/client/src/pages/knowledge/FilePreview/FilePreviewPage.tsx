/**
 * FilePreviewPage — business page for file preview.
 * Renders the file preview with a bottom-anchored AI dock (mirrors the knowledge
 * space dock pattern). This is the route-level component; FilePreview itself is
 * a reusable, decoupled component.
 */
import { useCallback, useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { Outlined } from "bisheng-icons";
import { getFileDownloadApi, getFilePreviewApi } from "~/api/knowledge";
import type { KnowledgeFilePreview } from "~/api/knowledge";
import { canOpenPermissionDialog, checkPermission } from "~/api/permission";
import { Button, DropdownMenu, DropdownMenuTrigger } from "~/components";
import { ActionMenuContent, ActionMenuItem } from "~/components/ActionMenu";
import { PermissionDialog } from "~/components/permission";
import { FileAiDock } from "~/pages/Subscription/AiChat/FileAiDock";
import FilePreview from "./index";
import { RichKnowledgePreview } from "./RichKnowledgePreview";
import { useLocalize } from "~/hooks";

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

function resolvePreviewUrl(url: string): string {
    if (!url) return "";
    return /^https?:\/\//.test(url)
        ? url
        : `${window.location.origin}${__APP_ENV__.BASE_URL}${url}`;
}

const AUDIO_EXTENSIONS = new Set(["mp3", "wav", "m4a", "aac", "flac", "ogg"]);
const VIDEO_EXTENSIONS = new Set(["mp4", "mov", "avi", "mkv", "webm"]);

function isRichPreviewData(data: KnowledgeFilePreview | null): boolean {
    if (!data) return false;
    const ext = extractExtFromUrl(data.original_url || data.preview_url || "", "");
    return (
        data.file_source === "web_link"
        || data.file_source === "audio_transcript"
        || data.file_source === "video_transcript"
        || data.media_kind === "audio"
        || data.media_kind === "video"
        || AUDIO_EXTENSIONS.has(ext)
        || VIDEO_EXTENSIONS.has(ext)
    );
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
    const [previewData, setPreviewData] = useState<KnowledgeFilePreview | null>(null);
    const [loading, setLoading] = useState(true);
    const [conversionFailed, setConversionFailed] = useState(false);
    const [canDownload, setCanDownload] = useState(false);
    const [canManagePermission, setCanManagePermission] = useState(false);
    const [permissionDialogOpen, setPermissionDialogOpen] = useState(false);

    useEffect(() => {
        if (!fileId || !spaceId) { setLoading(false); return; }
        setLoading(true);
        setConversionFailed(false);
        setPreviewData(null);
        getFilePreviewApi(spaceId, fileId)
            .then((data) => {
                const resolvedPreview = {
                    ...data,
                    original_url: resolvePreviewUrl(data.original_url),
                    preview_url: resolvePreviewUrl(data.preview_url),
                    html_preview_url: resolvePreviewUrl(data.html_preview_url),
                };
                setPreviewData(resolvedPreview);

                if (isRichPreviewData(data)) {
                    const richUrl = resolvedPreview.preview_url || resolvedPreview.html_preview_url || resolvedPreview.original_url;
                    setFileUrl(richUrl);
                    setFileType(data.file_source === "web_link" ? "html" : extractExtFromUrl(data.original_url, "md"));
                    return;
                }

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

                setFileUrl(resolvePreviewUrl(chosenUrl));
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

    // Mobile layout (<md = 768px): keep a bare preview + floating download (no TopBar).
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

    // Extra actions injected into FilePreview's TopBar slot:
    // a single More dropdown that consolidates permission management + download.
    const showMoreMenu = canManagePermission || canDownload;
    const topBarActions = showMoreMenu ? (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <Button
                    variant="outline"
                    className="h-8 w-8 p-2"
                    aria-label={localize("com_knowledge.more")}
                >
                    <Outlined.MoreCircle className="size-4 text-[#4e5969]" />
                </Button>
            </DropdownMenuTrigger>
            <ActionMenuContent align="end">
                {canManagePermission && (
                    <ActionMenuItem
                        onClick={() => setPermissionDialogOpen(true)}
                        icon={<Outlined.PeopleSafe />}
                        label={localize("com_permission.manage_permission")}
                    />
                )}
                {canDownload && (
                    <ActionMenuItem
                        onClick={handleDownloadFile}
                        icon={<Outlined.Download />}
                        label={localize("com_knowledge.download")}
                    />
                )}
            </ActionMenuContent>
        </DropdownMenu>
    ) : null;

    const renderPreview = (compactMode = false) => {
        if (previewData && isRichPreviewData(previewData)) {
            return (
                <RichKnowledgePreview
                    fileName={fileName}
                    preview={previewData}
                    actions={compactMode ? undefined : topBarActions}
                    allowDownload={canDownload}
                    onDownloadFile={handleDownloadFile}
                    compactMode={compactMode}
                />
            );
        }
        return (
            <FilePreview
                fileName={fileName}
                fileType={fileType}
                fileUrl={fileUrl}
                actions={compactMode ? undefined : topBarActions}
                conversionFailed={conversionFailed}
                allowDownload={canDownload}
                onDownloadFile={handleDownloadFile}
                hideHeader={compactMode}
                hideSidebar={compactMode}
                hideHeaderDownload={!compactMode}
            />
        );
    };

    // Loading state while fetching preview URL
    if (loading) {
        return (
            <div className="h-screen flex items-center justify-center bg-white">
                <div className="text-[#86909c]">{localize("com_knowledge.loading")}</div>
            </div>
        );
    }

    // No URL available (skip this guard for pptx conversion failure — handled by FilePreview)
    if (!fileUrl && !conversionFailed && !isRichPreviewData(previewData)) {
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
                    {renderPreview(true)}
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

    // ─── Desktop layout: TopBar + viewer with a bottom-anchored AI dock overlay.
    return (
        <div className="relative h-screen flex flex-col bg-white overflow-hidden">
            {fileId && (
                <PermissionDialog
                    open={permissionDialogOpen}
                    onOpenChange={setPermissionDialogOpen}
                    resourceType="knowledge_file"
                    resourceId={fileId}
                    resourceName={fileName}
                />
            )}

            <div className="min-h-0 flex-1">
                {renderPreview(false)}
            </div>

            {spaceId && fileId && <FileAiDock spaceId={spaceId} fileId={fileId} />}
        </div>
    );
}
