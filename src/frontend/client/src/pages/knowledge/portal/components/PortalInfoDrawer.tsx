import { Copy, X } from "lucide-react";
import type { KnowledgeFile, KnowledgeSpace } from "~/api/knowledge";
import type { PanelKey } from "../types";
import { formatFileSize } from "../utils";
import { formatTime } from "../../knowledgeUtils";
import s from "../PortalKnowledgeWorkbench.module.css";

interface PortalInfoDrawerProps {
    activePanel: PanelKey | null;
    activeSpace: KnowledgeSpace | null;
    selectedFile: KnowledgeFile | null;
    documentPath: string;
    onClose: () => void;
    onCopyShareLink: () => void;
}

export function PortalInfoDrawer({
    activePanel,
    activeSpace,
    selectedFile,
    documentPath,
    onClose,
    onCopyShareLink,
}: PortalInfoDrawerProps) {
    if (!activePanel) return null;

    const panelTitleMap: Record<PanelKey, string> = {
        properties: "属性",
        time: "时间",
        source: "来源",
        usage: "使用",
        share: "分享",
    };
    const placeholderTextMap: Partial<Record<PanelKey, string>> = {
        time: "文件时间线暂未开放",
        source: "文件来源信息暂未开放",
        usage: "文件使用统计暂未开放",
    };

    return (
        <aside className={s.drawer} data-testid="portal-info-drawer">
            <div className={s.drawerHeader}>
                <div className={s.drawerTitle}>{panelTitleMap[activePanel]}</div>
                <button type="button" className={s.toolbarButton} onClick={onClose} aria-label="关闭">
                    <X size={14} />
                </button>
            </div>
            <div className={s.drawerBody}>
                {activePanel === "properties" ? (
                    <div className={s.detailList}>
                        <div className={s.detailItem}>
                            <span className={s.detailLabel}>知识库</span>
                            <span className={s.detailValue}>{activeSpace?.name || "-"}</span>
                        </div>
                        <div className={s.detailItem}>
                            <span className={s.detailLabel}>文件名称</span>
                            <span className={s.detailValue}>{selectedFile?.name || "未选择文件"}</span>
                        </div>
                        <div className={s.detailItem}>
                            <span className={s.detailLabel}>文件大小</span>
                            <span className={s.detailValue}>{selectedFile ? formatFileSize(selectedFile.size) : "-"}</span>
                        </div>
                        <div className={s.detailItem}>
                            <span className={s.detailLabel}>更新时间</span>
                            <span className={s.detailValue}>{selectedFile?.updatedAt ? formatTime(selectedFile.updatedAt) : "-"}</span>
                        </div>
                        <div className={s.detailItem}>
                            <span className={s.detailLabel}>路径</span>
                            <span className={s.detailValue}>{documentPath || "-"}</span>
                        </div>
                    </div>
                ) : null}

                {activePanel === "time" || activePanel === "source" || activePanel === "usage" ? (
                    <div className={s.detailList}>
                        <div className={s.detailItem}>
                            <span className={s.detailLabel}>状态</span>
                            <span className={s.detailValue}>暂未开放</span>
                        </div>
                        <div className={s.detailItem}>
                            <span className={s.detailLabel}>说明</span>
                            <span className={s.detailValue}>{placeholderTextMap[activePanel]}</span>
                        </div>
                    </div>
                ) : null}

                {activePanel === "share" ? (
                    <div className={s.detailList}>
                        <div className={s.detailItem}>
                            <span className={s.detailLabel}>分享范围</span>
                            <span className={s.detailValue}>当前知识库：{activeSpace?.name || "-"}</span>
                        </div>
                        <div className={s.buttonStack}>
                            <button type="button" className={s.primaryButton} disabled={!activeSpace} onClick={onCopyShareLink}>
                                <Copy size={14} />
                                复制分享链接
                            </button>
                        </div>
                    </div>
                ) : null}
            </div>
        </aside>
    );
}
