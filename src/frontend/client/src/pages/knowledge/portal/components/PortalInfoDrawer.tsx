import { Copy, X } from "lucide-react";
import type { KnowledgeFile, KnowledgeSpace } from "~/api/knowledge";
import type { PanelKey } from "../types";
import { formatFileSize } from "../utils";
import s from "../PortalKnowledgeWorkbench.module.css";

const DETAIL_TABS: Array<{ key: Exclude<PanelKey, "share">; label: string }> = [
    { key: "properties", label: "属性" },
    { key: "time", label: "时间" },
    { key: "source", label: "来源" },
    { key: "usage", label: "使用" },
    { key: "permission", label: "权限" },
];

const DEFAULT_DEPARTMENT_NAME = "产品研发中心-数智组";
const USAGE_STATS = {
    downloads: 652,
    views: 1216,
    shares: 1000,
};

function formatDrawerDateTime(dateString?: string | null) {
    if (!dateString) return "-";
    const date = new Date(dateString);
    if (Number.isNaN(date.getTime())) return dateString;
    const yyyy = date.getFullYear();
    const mm = String(date.getMonth() + 1).padStart(2, "0");
    const dd = String(date.getDate()).padStart(2, "0");
    const HH = String(date.getHours()).padStart(2, "0");
    const min = String(date.getMinutes()).padStart(2, "0");
    const sec = String(date.getSeconds()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd} ${HH}:${min}:${sec}`;
}

function getDisplayFileName(file?: KnowledgeFile | null) {
    if (!file) return "未选择文件";
    const dotIndex = file.name.lastIndexOf(".");
    return dotIndex > 0 ? file.name.slice(0, dotIndex) : file.name;
}

function getStorageFormat(file?: KnowledgeFile | null) {
    if (!file) return "-";
    const ext = file.name.split(".").pop()?.toLowerCase();
    return ext && ext !== file.name.toLowerCase() ? ext : String(file.type || "-");
}

function formatVersionText(versionNo?: number) {
    return versionNo ? `1.${versionNo}.0` : "-";
}

interface PortalInfoDrawerProps {
    activePanel: PanelKey | null;
    activeSpace: KnowledgeSpace | null;
    selectedFile: KnowledgeFile | null;
    documentPath: string;
    onClose: () => void;
    onCopyShareLink: () => void;
    onPanelChange: (panel: Exclude<PanelKey, "share">) => void;
}

export function PortalInfoDrawer({
    activePanel,
    activeSpace,
    selectedFile,
    onClose,
    onCopyShareLink,
    onPanelChange,
}: PortalInfoDrawerProps) {
    if (!activePanel) return null;

    const panelTitleMap: Record<PanelKey, string> = {
        properties: "属性",
        time: "时间",
        source: "来源",
        usage: "使用",
        permission: "权限",
        share: "分享",
    };
    const visiblePanel = activePanel === "share" ? "share" : activePanel;
    const fileFormat = getStorageFormat(selectedFile);
    const fileTypeText = selectedFile ? "文档" : "-";
    const tags = selectedFile?.tags ?? [];
    const versionText = formatVersionText(selectedFile?.version_no);
    const operatorName = selectedFile?.user_name || "-";

    const renderDetailItem = (label: string, value: string | number | null | undefined) => (
        <div className={s.detailItem}>
            <span className={s.detailLabel}>{label}</span>
            <span className={s.detailValue}>{value === undefined || value === null || value === "" ? "-" : value}</span>
        </div>
    );

    return (
        <aside className={s.drawer} data-testid="portal-info-drawer">
            {visiblePanel === "share" ? (
                <div className={s.drawerHeader}>
                    <div className={s.drawerTitle}>{panelTitleMap[activePanel]}</div>
                    <button type="button" className={s.toolbarButton} onClick={onClose} aria-label="关闭">
                        <X size={14} />
                    </button>
                </div>
            ) : (
                <div className={s.drawerTabsHeader}>
                    <div className={s.drawerTabs} role="tablist" aria-label="文件详情">
                        {DETAIL_TABS.map((tab) => (
                            <button
                                type="button"
                                key={tab.key}
                                id={`portal-drawer-tab-${tab.key}`}
                                role="tab"
                                aria-controls={`portal-drawer-panel-${tab.key}`}
                                aria-selected={activePanel === tab.key}
                                className={`${s.drawerTab} ${activePanel === tab.key ? s.drawerTabActive : ""}`}
                                onClick={() => onPanelChange(tab.key)}
                            >
                                {tab.label}
                            </button>
                        ))}
                    </div>
                    <button type="button" className={s.toolbarButton} onClick={onClose} aria-label="关闭">
                        <X size={14} />
                    </button>
                </div>
            )}
            <div className={s.drawerBody}>
                {activePanel === "properties" ? (
                    <div
                        id="portal-drawer-panel-properties"
                        role="tabpanel"
                        aria-labelledby="portal-drawer-tab-properties"
                        className={s.detailList}
                    >
                        {renderDetailItem("文件名", getDisplayFileName(selectedFile))}
                        {renderDetailItem("文件编码", selectedFile?.fileEncoding)}
                        {renderDetailItem("编码说明", selectedFile?.fileEncoding ? "此处为中文说明占位" : "-")}
                        {renderDetailItem("文件类型", fileTypeText)}
                        {renderDetailItem("大小", selectedFile ? formatFileSize(selectedFile.size) : "-")}
                        {renderDetailItem("存储格式", fileFormat)}
                        <div className={s.detailItem}>
                            <span className={s.detailLabel}>标签</span>
                            {tags.length ? (
                                <span className={s.tagList}>
                                    {tags.map((tag) => (
                                        <span key={tag.id} className={s.tagChip}>{tag.name}</span>
                                    ))}
                                </span>
                            ) : (
                                <span className={s.detailValue}>-</span>
                            )}
                        </div>
                        {renderDetailItem("版本号", versionText)}
                    </div>
                ) : null}

                {activePanel === "time" ? (
                    <div
                        id="portal-drawer-panel-time"
                        role="tabpanel"
                        aria-labelledby="portal-drawer-tab-time"
                        className={s.detailList}
                    >
                        {renderDetailItem("创建时间", formatDrawerDateTime(selectedFile?.createdAt))}
                        {renderDetailItem("最后修改时间", formatDrawerDateTime(selectedFile?.updatedAt))}
                    </div>
                ) : null}

                {activePanel === "source" ? (
                    <div
                        id="portal-drawer-panel-source"
                        role="tabpanel"
                        aria-labelledby="portal-drawer-tab-source"
                        className={s.detailList}
                    >
                        {renderDetailItem("创建人", operatorName)}
                        {renderDetailItem("最后修改人", operatorName)}
                        {renderDetailItem("部门", selectedFile ? DEFAULT_DEPARTMENT_NAME : "-")}
                    </div>
                ) : null}

                {activePanel === "usage" ? (
                    <div
                        id="portal-drawer-panel-usage"
                        role="tabpanel"
                        aria-labelledby="portal-drawer-tab-usage"
                        className={s.detailList}
                    >
                        {renderDetailItem("下载次数", USAGE_STATS.downloads)}
                        {renderDetailItem("浏览次数", USAGE_STATS.views)}
                        {renderDetailItem("分享次数", USAGE_STATS.shares)}
                    </div>
                ) : null}

                {activePanel === "permission" ? (
                    <div
                        id="portal-drawer-panel-permission"
                        role="tabpanel"
                        aria-labelledby="portal-drawer-tab-permission"
                        className={s.detailList}
                    >
                        {renderDetailItem("当前用户角色", activeSpace?.role)}
                        {renderDetailItem("知识库可见性", activeSpace?.visibility)}
                        {renderDetailItem("权限范围", "继承当前知识库权限")}
                        {renderDetailItem("说明", "细粒度权限管理请在知识空间成员与权限设置中维护。")}
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
