import type { KnowledgeFile, KnowledgeSpace } from "~/api/knowledge";
import type { PanelKey, PreviewState } from "../types";
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
    canManagePermission: boolean;
    documentPath: string;
    isPersonalSpace: boolean;
    preview: PreviewState;
    selectedFile: KnowledgeFile;
    summaryExpanded: boolean;
    onAiDrawerOpenChange: (open: boolean) => void;
    onBackToFileList: () => void;
    onCopyEncoding: () => void;
    onCopyShareLink: () => void;
    onDownload: () => void;
    onEditEncoding: () => void;
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
    canManagePermission,
    documentPath,
    isPersonalSpace,
    preview,
    selectedFile,
    summaryExpanded,
    onAiDrawerOpenChange,
    onBackToFileList,
    onCopyEncoding,
    onCopyShareLink,
    onDownload,
    onEditEncoding,
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
                <DocumentPreview
                    selectedFile={selectedFile}
                    documentPath={documentPath}
                    preview={preview}
                    summaryExpanded={summaryExpanded}
                    onOpenTags={onOpenTags}
                    // onOpenShare={() => setActivePanel("share")}
                    onDownload={onDownload}
                    canManagePermission={canManagePermission}
                    onOpenPermission={onOpenPermission}
                    onCopyEncoding={onCopyEncoding}
                    onToggleSummary={onToggleSummary}
                />
            </div>

            {!aiDrawerOpen ? (
                <PortalInfoDrawer
                    activePanel={activePanel}
                    activeSpace={activeSpace}
                    selectedFile={selectedFile}
                    documentPath={documentPath}
                    showPermissionPanel={!isPersonalSpace}
                    canEditEncoding={canEditEncoding}
                    onClose={() => onPanelChange(null)}
                    onCopyShareLink={onCopyShareLink}
                    onEditEncoding={onEditEncoding}
                    onPanelChange={onPanelChange}
                />
            ) : null}

            <PortalAiDrawer
                open={aiDrawerOpen}
                activeSpace={activeSpace}
                selectedFile={selectedFile}
                documentPath={documentPath}
                onOpenChange={onAiDrawerOpenChange}
            />

            <ToolRail
                activePanel={activePanel}
                aiOpen={aiDrawerOpen}
                showPermissionPanel={!isPersonalSpace}
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
        </main>
    );
}
