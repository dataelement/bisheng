import { X } from "lucide-react";
import type { KnowledgeFile, KnowledgeSpace } from "~/api/knowledge";
import { AiAssistantPanel } from "~/pages/Subscription/AiChat/AiAssistantPanel";
import s from "../PortalKnowledgeWorkbench.module.css";

interface PortalAiDialogProps {
    open: boolean;
    activeSpace: KnowledgeSpace | null;
    selectedFile: KnowledgeFile | null;
    documentPath: string;
    onOpenChange: (open: boolean) => void;
}

export function PortalAiDrawer({
    open,
    activeSpace,
    selectedFile,
    onOpenChange,
}: PortalAiDialogProps) {
    if (!open || !activeSpace || !selectedFile) return null;

    return (
        <aside
            data-testid="portal-ai-drawer"
            className={s.aiDrawer}
            aria-label="AI 对话抽屉"
        >
            <div className={s.aiDrawerHeader}>
                <div className={s.aiDrawerTitle}>AI对话</div>
                <button
                    type="button"
                    className={s.aiDrawerClose}
                    aria-label="关闭AI抽屉"
                    onClick={() => onOpenChange(false)}
                >
                    <X size={18} />
                </button>
            </div>
            <div className={s.aiDrawerBody}>
                <AiAssistantPanel
                    features={{
                        tools: false,
                        modelSelect: true,
                        knowledgeBase: false,
                        fileUpload: false,
                    }}
                    onClose={() => onOpenChange(false)}
                    noBorder
                    fileChat={{ spaceId: activeSpace.id, fileId: selectedFile.id }}
                    portalDrawer
                />
            </div>
        </aside>
    );
}

export function PortalAiDialog(props: PortalAiDialogProps) {
    return (
        <PortalAiDrawer
            {...props}
        />
    );
}
