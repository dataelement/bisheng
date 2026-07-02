import { useEffect, useState } from "react";
import { Copy, X } from "lucide-react";
import type { KnowledgeFile, KnowledgeSpace } from "~/api/knowledge";
import { SpaceLevel, SpaceRole, VisibilityType, getFileStatsApi } from "~/api/knowledge";
import type { PanelKey, PortalFileCategoryOption } from "../types";
import {
    BUSINESS_DOMAIN_OPTIONS,
    type EncodingDraft,
    composeFileEncoding,
    fileEncodingBusinessDomainLabel,
    fileEncodingCategoryLabel,
    normalizeEncodingCode,
    parseFileEncoding,
} from "../uploadMetadata";
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

function spaceLevelLabel(level?: SpaceLevel): string {
    const map: Record<SpaceLevel, string> = {
        [SpaceLevel.PUBLIC]: "公共知识库",
        [SpaceLevel.DEPARTMENT]: "部门知识库",
        [SpaceLevel.TEAM]: "团队知识库",
        [SpaceLevel.PERSONAL]: "个人知识库",
    };
    return level ? (map[level] ?? level) : "-";
}

function spaceRoleLabel(role?: SpaceRole): string {
    const map: Record<SpaceRole, string> = {
        [SpaceRole.CREATOR]: "创建者",
        [SpaceRole.ADMIN]: "管理员",
        [SpaceRole.MEMBER]: "成员",
    };
    return role ? (map[role] ?? role) : "-";
}

function visibilityLabel(vis?: VisibilityType): string {
    const map: Record<VisibilityType, string> = {
        [VisibilityType.PUBLIC]: "全员可见",
        [VisibilityType.PRIVATE]: "仅成员可见",
        [VisibilityType.APPROVAL]: "申请后可见",
    };
    return vis ? (map[vis] ?? vis) : "-";
}

function permissionScopeDescription(role?: SpaceRole, level?: SpaceLevel): string {
    if (role === SpaceRole.CREATOR || role === SpaceRole.ADMIN) {
        return "可查阅、上传、编辑、删除库内所有文档，并管理成员权限。";
    }
    if (level === SpaceLevel.PUBLIC) {
        return "可查阅库内所有公开文档，无上传及管理权限。";
    }
    return "可查阅库内已授权文档，无上传及管理权限。";
}

interface PortalInfoDrawerProps {
    activePanel: PanelKey | null;
    activeSpace: KnowledgeSpace | null;
    selectedFile: KnowledgeFile | null;
    documentPath: string;
    canEditEncoding?: boolean;
    fileCategoryOptions: PortalFileCategoryOption[];
    encodingPrefix: string;
    onClose: () => void;
    onCopyShareLink: () => void;
    onUpdateEncoding?: (newEncoding: string) => void | Promise<void>;
    onPanelChange: (panel: Exclude<PanelKey, "share">) => void;
}

export function PortalInfoDrawer({
    activePanel,
    activeSpace,
    selectedFile,
    canEditEncoding = false,
    fileCategoryOptions,
    encodingPrefix,
    onClose,
    onCopyShareLink,
    onUpdateEncoding,
    onPanelChange,
}: PortalInfoDrawerProps) {
    const [encodingDraft, setEncodingDraft] = useState<EncodingDraft>({});
    const [savingEncoding, setSavingEncoding] = useState(false);
    const [fileStats, setFileStats] = useState<{ views: number; downloads: number } | null>(null);

    useEffect(() => {
        setEncodingDraft({});
    }, [selectedFile?.id, selectedFile?.fileEncoding]);

    useEffect(() => {
        if (activePanel !== "usage" || !selectedFile || !activeSpace) return;
        setFileStats(null);
        getFileStatsApi(activeSpace.id, selectedFile.id)
            .then((stats) => setFileStats(stats))
            .catch(() => setFileStats({ views: 0, downloads: 0 }));
    }, [activePanel, selectedFile?.id, activeSpace?.id]);

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
    const tags = selectedFile?.tags ?? [];
    const versionText = formatVersionText(selectedFile?.version_no);
    const operatorName = selectedFile?.user_name || "-";
    const detailTabs = DETAIL_TABS;

    const renderDetailItem = (label: string, value: string | number | null | undefined) => (
        <div className={s.detailItem}>
            <span className={s.detailLabel}>{label}</span>
            <span className={s.detailValue}>{value === undefined || value === null || value === "" ? "-" : value}</span>
        </div>
    );

    const parsedEncoding = parseFileEncoding(selectedFile?.fileEncoding, encodingPrefix);
    const selectedFileCategoryCode = normalizeEncodingCode(
        encodingDraft.fileCategoryCode ?? parsedEncoding.fileCategoryCode,
    );
    const selectedBusinessDomainCode = normalizeEncodingCode(
        encodingDraft.businessDomainCode ?? parsedEncoding.businessDomainCode,
    );
    const hasCurrentCategoryOption = fileCategoryOptions.some((option) => option.code === selectedFileCategoryCode);
    const hasCurrentBusinessDomainOption = BUSINESS_DOMAIN_OPTIONS.some((option) => option.code === selectedBusinessDomainCode);
    const displayFileEncoding = selectedFileCategoryCode && selectedBusinessDomainCode
        ? composeFileEncoding(selectedFile?.fileEncoding, selectedFileCategoryCode, selectedBusinessDomainCode, encodingPrefix)
        : selectedFile?.fileEncoding;

    const handleEncodingPartChange = async (nextDraft: EncodingDraft) => {
        if (!selectedFile || !canEditEncoding) return;
        const fileCategoryCode = normalizeEncodingCode(
            nextDraft.fileCategoryCode ?? encodingDraft.fileCategoryCode ?? parsedEncoding.fileCategoryCode,
        );
        const businessDomainCode = normalizeEncodingCode(
            nextDraft.businessDomainCode ?? encodingDraft.businessDomainCode ?? parsedEncoding.businessDomainCode,
        );
        setEncodingDraft({
            fileCategoryCode,
            businessDomainCode,
        });
        if (!fileCategoryCode || !businessDomainCode) return;

        const newEncoding = composeFileEncoding(
            selectedFile.fileEncoding,
            fileCategoryCode,
            businessDomainCode,
            encodingPrefix,
        );
        if (newEncoding === selectedFile.fileEncoding?.trim()) return;

        setSavingEncoding(true);
        try {
            await onUpdateEncoding?.(newEncoding);
        } finally {
            setSavingEncoding(false);
        }
    };

    const renderFileCategoryItem = () => (
        <div className={s.detailItem}>
            <span className={s.detailLabel}>文件类型</span>
            {selectedFile && canEditEncoding ? (
                <select
                    className={s.detailSelect}
                    aria-label={`修改${selectedFile.name}文件类型 当前类型：${selectedFileCategoryCode || "未识别"}`}
                    value={selectedFileCategoryCode}
                    disabled={savingEncoding}
                    onChange={(event) => void handleEncodingPartChange({ fileCategoryCode: event.currentTarget.value })}
                >
                    <option value="">未识别</option>
                    {selectedFileCategoryCode && !hasCurrentCategoryOption ? (
                        <option value={selectedFileCategoryCode}>
                            {fileEncodingCategoryLabel(selectedFileCategoryCode, fileCategoryOptions)}
                        </option>
                    ) : null}
                    {fileCategoryOptions.map((option) => (
                        <option key={option.code} value={option.code}>
                            {option.code} / {option.label}
                        </option>
                    ))}
                </select>
            ) : (
                <span className={s.detailValue}>
                    {selectedFile ? fileEncodingCategoryLabel(selectedFileCategoryCode, fileCategoryOptions) : "-"}
                </span>
            )}
        </div>
    );

    const renderBusinessDomainItem = () => (
        <div className={s.detailItem}>
            <span className={s.detailLabel}>业务域类型</span>
            {selectedFile && canEditEncoding ? (
                <select
                    className={s.detailSelect}
                    aria-label={`修改${selectedFile.name}业务域类型 当前业务域：${selectedBusinessDomainCode || "未识别"}`}
                    value={selectedBusinessDomainCode}
                    disabled={savingEncoding}
                    onChange={(event) => void handleEncodingPartChange({ businessDomainCode: event.currentTarget.value })}
                >
                    <option value="">未识别</option>
                    {selectedBusinessDomainCode && !hasCurrentBusinessDomainOption ? (
                        <option value={selectedBusinessDomainCode}>
                            {fileEncodingBusinessDomainLabel(selectedBusinessDomainCode)}
                        </option>
                    ) : null}
                    {BUSINESS_DOMAIN_OPTIONS.map((option) => (
                        <option key={option.code} value={option.code}>
                            {option.code} / {option.name}
                        </option>
                    ))}
                </select>
            ) : (
                <span className={s.detailValue}>
                    {selectedFile ? fileEncodingBusinessDomainLabel(selectedBusinessDomainCode) : "-"}
                </span>
            )}
        </div>
    );

    const renderFileEncodingItem = () => (
        <div className={s.detailItem}>
            <span className={s.detailLabel}>文件编码</span>
            <span className={s.detailValue}>{displayFileEncoding || "-"}</span>
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
                        {detailTabs.map((tab) => (
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
                        {renderFileCategoryItem()}
                        {renderBusinessDomainItem()}
                        {renderFileEncodingItem()}
                        {renderDetailItem("编码说明", selectedFile?.fileEncoding ? "此处为中文说明占位" : "-")}
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
                        {renderDetailItem("下载次数", fileStats ? fileStats.downloads : "-")}
                        {renderDetailItem("浏览次数", fileStats ? fileStats.views : "-")}
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

                {activePanel === "permission" ? (
                    <div
                        id="portal-drawer-panel-permission"
                        role="tabpanel"
                        aria-labelledby="portal-drawer-tab-permission"
                        className={s.detailList}
                    >
                        {renderDetailItem("当前角色", spaceRoleLabel(activeSpace?.role))}
                        {renderDetailItem("知识库类型", spaceLevelLabel(activeSpace?.spaceLevel))}
                        {renderDetailItem("可见性", visibilityLabel(activeSpace?.visibility))}
                        <div className={s.detailItem}>
                            <span className={s.detailLabel}>权限范围</span>
                            <span className={`${s.detailValue} ${s.detailValueWrap}`}>
                                {permissionScopeDescription(activeSpace?.role, activeSpace?.spaceLevel)}
                            </span>
                        </div>
                        {activeSpace?.description ? (
                            <div className={s.detailItem}>
                                <span className={s.detailLabel}>说明</span>
                                <span className={`${s.detailValue} ${s.detailValueWrap}`}>{activeSpace.description}</span>
                            </div>
                        ) : null}
                    </div>
                ) : null}
            </div>
        </aside>
    );
}
