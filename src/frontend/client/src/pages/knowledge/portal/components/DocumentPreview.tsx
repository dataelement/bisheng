import { Bot, ChevronDown, Copy, Download, FileText, ShieldCheck, SquarePen } from "lucide-react";
// import { Share2 } from "lucide-react";
import type { KnowledgeFile } from "~/api/knowledge";
import FilePreview from "../../FilePreview";
import type { PreviewState } from "../types";
import s from "../PortalKnowledgeWorkbench.module.css";

interface DocumentPreviewProps {
    selectedFile: KnowledgeFile | null;
    documentPath: string;
    preview: PreviewState;
    summaryExpanded: boolean;
    onOpenAi: () => void;
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
    onOpenAi,
    onOpenTags,
    // onOpenShare,
    onDownload,
    canManagePermission,
    onOpenPermission,
    onCopyEncoding,
    onToggleSummary,
}: DocumentPreviewProps) {
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
                            <button type="button" className={s.iconAction} title="AI 对话" aria-label="AI 对话" onClick={onOpenAi}>
                                <Bot size={16} />
                            </button>
                            <button type="button" className={s.iconAction} title="编辑标签" aria-label="编辑标签" onClick={onOpenTags}>
                                <SquarePen size={16} />
                            </button>
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
                        className={s.summaryBar}
                        aria-label="查看文档摘要"
                        aria-expanded={summaryExpanded}
                        aria-controls="portal-summary-detail"
                        onClick={onToggleSummary}
                    >
                        <div className={s.summaryTitle}>
                            <FileText size={16} />
                            文档摘要
                        </div>
                        <div className={s.summaryText}>{selectedFile.summary || "暂无摘要"}</div>
                        <ChevronDown size={14} />
                    </button>
                    {summaryExpanded ? (
                        <div id="portal-summary-detail" data-testid="portal-summary-detail" className={s.summaryDetail}>
                            {selectedFile.summary || "暂无摘要"}
                        </div>
                    ) : null}
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
                                <FilePreview
                                    fileName={selectedFile.name}
                                    fileType={preview.fileType}
                                    fileUrl={preview.fileUrl}
                                    compactMode
                                    allowDownload={false}
                                />
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
