import { ChevronDown, ChevronUp, Copy, Download, FileText, ShieldCheck, SquarePen } from "lucide-react";
// import { Share2 } from "lucide-react";
import type { KnowledgeFile } from "~/api/knowledge";
import FilePreview from "../../FilePreview";
import { RichKnowledgePreview } from "../../FilePreview/RichKnowledgePreview";
import type { PreviewState } from "../types";
import s from "../PortalKnowledgeWorkbench.module.css";

const AUDIO_EXTENSIONS = new Set(["mp3", "wav", "m4a", "aac", "flac", "ogg"]);
const VIDEO_EXTENSIONS = new Set(["mp4", "mov", "avi", "mkv", "webm"]);

function getExtensionFromUrl(url?: string): string {
    if (!url) return "";
    const path = url.split("?")[0].split("#")[0];
    const filename = path.split("/").pop() || "";
    const dotIndex = filename.lastIndexOf(".");
    return dotIndex >= 0 ? filename.slice(dotIndex + 1).toLowerCase() : "";
}

function isRichPreviewData(previewData: PreviewState["previewData"]): boolean {
    if (!previewData) return false;
    const ext = getExtensionFromUrl(previewData.original_url || previewData.preview_url);
    return (
        previewData.file_source === "web_link"
        || previewData.file_source === "audio_transcript"
        || previewData.file_source === "video_transcript"
        || previewData.media_kind === "audio"
        || previewData.media_kind === "video"
        || AUDIO_EXTENSIONS.has(ext)
        || VIDEO_EXTENSIONS.has(ext)
    );
}

interface DocumentPreviewProps {
    selectedFile: KnowledgeFile | null;
    documentPath: string;
    preview: PreviewState;
    summaryExpanded: boolean;
    canEditTags: boolean;
    onOpenTags: () => void;
    // onOpenShare: () => void;
    onDownload: () => void;
    canManagePermission: boolean;
    onOpenPermission: () => void;
    onCopyEncoding: () => void;
    onToggleSummary: () => void;
}

export function DocumentPreview({
    selectedFile,
    documentPath,
    preview,
    summaryExpanded,
    canEditTags,
    onOpenTags,
    // onOpenShare,
    onDownload,
    canManagePermission,
    onOpenPermission,
    onCopyEncoding,
    onToggleSummary,
}: DocumentPreviewProps) {
    const isRichPreview = isRichPreviewData(preview.previewData);

    return (
        <section className={s.documentShell}>
            {selectedFile ? (
                <>
                    <div className={s.documentHeader}>
                        <div className={s.docIcon}>
                            <FileText size={30} />
                        </div>
                        <div className={s.docTitleBlock}>
                            <h1 className={s.docTitle}>{selectedFile.name}</h1>
                            <div className={s.docPath}>{documentPath}</div>
                        </div>
                        <div className={s.docActions} data-testid="portal-document-actions">
                            {canEditTags ? (
                                <button type="button" className={s.iconAction} title="编辑标签" aria-label="编辑标签" onClick={onOpenTags}>
                                    <SquarePen size={16} />
                                </button>
                            ) : null}
                            {/* <button type="button" className={s.iconAction} title="分享" aria-label="分享" onClick={onOpenShare}>
                                <Share2 size={16} />
                            </button> */}
                            <button type="button" className={s.iconAction} title="下载" aria-label="下载" onClick={onDownload}>
                                <Download size={16} />
                            </button>
                            {canManagePermission ? (
                                <button type="button" className={s.iconAction} title="权限管理" aria-label="权限管理" onClick={onOpenPermission}>
                                    <ShieldCheck size={16} />
                                </button>
                            ) : null}
                            <button type="button" className={s.iconAction} title="复制" aria-label="复制" onClick={onCopyEncoding}>
                                <Copy size={16} />
                            </button>
                        </div>
                    </div>
                    <div className={s.divider} />
                    <button
                        type="button"
                        className={`${s.summaryBar} ${summaryExpanded ? s.summaryBarExpanded : ""}`}
                        aria-label={summaryExpanded ? "收起文档摘要" : "查看文档摘要"}
                        aria-expanded={summaryExpanded}
                        aria-controls="portal-summary-content"
                        onClick={onToggleSummary}
                    >
                        <div className={s.summaryHeader} data-testid="portal-summary-header">
                            <span className={s.summaryIcon}>
                                <FileText size={16} />
                            </span>
                            <span className={s.summaryLabel}>
                                文档摘要
                            </span>
                            <span className={s.summaryToggleIcon}>
                                {summaryExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                            </span>
                        </div>
                        <div id="portal-summary-content" data-testid="portal-summary-content" className={s.summaryText}>
                            {selectedFile.summary || "暂无摘要"}
                        </div>
                    </button>
                    <div className={s.previewHost}>
                        {preview.loading ? (
                            <div className={s.stateBox}>正在加载预览...</div>
                        ) : preview.error ? (
                            <div className={s.stateBox}>
                                <div className={s.stateTitle}>无法预览</div>
                                <div>{preview.error}</div>
                            </div>
                        ) : preview.fileUrl ? (
                            <div className={s.previewFrame}>
                                {isRichPreview && preview.previewData ? (
                                    <RichKnowledgePreview
                                        fileName={selectedFile.name}
                                        preview={preview.previewData}
                                        compactMode
                                        allowDownload={false}
                                    />
                                ) : (
                                    <FilePreview
                                        fileName={selectedFile.name}
                                        fileType={preview.fileType}
                                        fileUrl={preview.fileUrl}
                                        compactMode
                                        allowDownload={false}
                                    />
                                )}
                            </div>
                        ) : (
                            <div className={s.previewCard}>
                                <h2 className={s.docContentTitle}>{selectedFile.name.replace(/\.[^.]+$/, "")}</h2>
                                <h3 className={s.docSectionTitle}>文档概述</h3>
                                <p>当前文档已选中，正在等待预览内容。</p>
                            </div>
                        )}
                    </div>
                </>
            ) : (
                <div className={`${s.stateBox} ${s.documentEmptyState}`}>
                    <FileText size={42} />
                    <div className={s.stateTitle}>请选择一个文件</div>
                    <div>点击左侧文件后，将在这里展示摘要、预览和操作入口。</div>
                </div>
            )}
        </section>
    );
}
