import type { ReactNode } from "react";
import type { KnowledgeFile, KnowledgeSpace } from "~/api/knowledge";
import type { PanelKey, PortalFileCategoryGroupOption, PreviewState } from "../types";
import type { BusinessDomainOptionItem } from "../uploadMetadata";
import { DocumentPreview } from "./DocumentPreview";
import { PortalAiDrawer } from "./PortalAiDialog";
import { PortalInfoDrawer } from "./PortalInfoDrawer";
import { ToolRail } from "./ToolRail";
import s from "../PortalKnowledgeWorkbench.module.css";

interface PortalPreviewWorkspaceProps {
    activePanel: PanelKey | null;
    activeSpace: KnowledgeSpace | null;
    aiDrawerOpen: boolean;
    canEditEncoding: boolean;
    canEditTags: boolean;
    canManagePermission: boolean;
    canDownload: boolean;
    downloadPending: boolean;
    documentPath: string;
    encodingPrefix: string;
    fileCategoryGroups: PortalFileCategoryGroupOption[];
    businessDomainOptions: BusinessDomainOptionItem[];
    isPersonalSpace: boolean;
    preview: PreviewState;
    contentOverride?: ReactNode;
    selectedFile: KnowledgeFile;
    summaryExpanded: boolean;
    onAiDrawerOpenChange: (open: boolean) => void;
    onBackToFileList: () => void;
    onCopyShareLink: () => void;
    onDownload: () => void;
    onUpdateEncoding: (newEncoding: string, fileSubcategoryCode?: string | null) => void | Promise<void>;
    onOpenPermission: () => void;
    onOpenTags: () => void;
    onPanelChange: (panel: PanelKey | null) => void;
    onToggleSummary: () => void;
}

export function PortalPreviewWorkspace({
    activePanel,
    activeSpace,
    aiDrawerOpen,
    canEditEncoding,
    canEditTags,
    canManagePermission,
    canDownload,
    downloadPending,
    documentPath,
    encodingPrefix,
    fileCategoryGroups,
    businessDomainOptions,
    isPersonalSpace,
    preview,
    contentOverride,
    selectedFile,
    summaryExpanded,
    onAiDrawerOpenChange,
    onBackToFileList,
    onCopyShareLink,
    onDownload,
    onUpdateEncoding,
    onOpenPermission,
    onOpenTags,
    onPanelChange,
    onToggleSummary,
}: PortalPreviewWorkspaceProps) {
    return (
        <main className={s.documentArea} data-testid="portal-preview-page">
            <div className={s.previewContent}>
                <button type="button" className={s.backToListButton} onClick={onBackToFileList}>
                    返回文件列表
                </button>
                {contentOverride ?? (
                    <DocumentPreview
                        selectedFile={selectedFile}
                        documentPath={documentPath}
                        preview={preview}
                        summaryExpanded={summaryExpanded}
                        canEditTags={canEditTags}
                        onOpenTags={onOpenTags}
                        // onOpenShare={() => setActivePanel("share")}
                        onDownload={onDownload}
                        canDownload={canDownload}
                        downloadPending={downloadPending}
                        canManagePermission={canManagePermission}
                        onOpenPermission={onOpenPermission}
                        onToggleSummary={onToggleSummary}
                    />
                )}
            </div>

            {!contentOverride && !aiDrawerOpen ? (
                <PortalInfoDrawer
                    activePanel={activePanel}
                    activeSpace={activeSpace}
                    selectedFile={selectedFile}
                    documentPath={documentPath}
                    canEditEncoding={canEditEncoding}
                    fileCategoryGroups={fileCategoryGroups}
                    businessDomainOptions={businessDomainOptions}
                    encodingPrefix={encodingPrefix}
                    onClose={() => onPanelChange(null)}
                    onCopyShareLink={onCopyShareLink}
                    onUpdateEncoding={onUpdateEncoding}
                    onPanelChange={onPanelChange}
                />
            ) : null}

            {!contentOverride ? (
                <PortalAiDrawer
                    open={aiDrawerOpen}
                    activeSpace={activeSpace}
                    selectedFile={selectedFile}
                    documentPath={documentPath}
                    onOpenChange={onAiDrawerOpenChange}
                />
            ) : null}

            {!contentOverride ? (
                <ToolRail
                    activePanel={activePanel}
                    aiOpen={aiDrawerOpen}
                    onTogglePanel={() => {
                        onAiDrawerOpenChange(false);
                        onPanelChange(activePanel ? null : "properties");
                    }}
                    onOpenAi={() => {
                        onPanelChange(null);
                        onAiDrawerOpenChange(true);
                    }}
                    onOpenPanel={(panel) => {
                        onAiDrawerOpenChange(false);
                        onPanelChange(panel);
                    }}
                />
            ) : null}
        </main>
    );
}
