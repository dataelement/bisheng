import { FileText, X } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "~/components/ui";
import type { KnowledgeFile, KnowledgeSpace } from "~/api/knowledge";
import { AiAssistantPanel } from "~/pages/Subscription/AiChat/AiAssistantPanel";
import { formatTime } from "../../knowledgeUtils";
import { formatFileSize } from "../utils";
import s from "../PortalKnowledgeWorkbench.module.css";

interface PortalAiDialogProps {
    open: boolean;
    activeSpace: KnowledgeSpace | null;
    selectedFile: KnowledgeFile | null;
    documentPath: string;
    onOpenChange: (open: boolean) => void;
}

export function PortalAiDialog({
    open,
    activeSpace,
    selectedFile,
    documentPath,
    onOpenChange,
}: PortalAiDialogProps) {
    if (!activeSpace || !selectedFile) return null;

    const updatedText = selectedFile.updatedAt ? formatTime(selectedFile.updatedAt) : "";
    const fileSizeText = formatFileSize(selectedFile.size);

    return (
        <Dialog
            open={open}
            onOpenChange={(nextOpen) => {
                if (!nextOpen) onOpenChange(false);
            }}
        >
            <DialogContent
                close={false}
                className={s.aiDialogContent}
                onPointerDownOutside={(event) => event.preventDefault()}
            >
                <div data-testid="portal-ai-dialog" className={s.aiDialog}>
                    <DialogHeader className={s.aiDialogHeader}>
                        <div className={s.aiFileIcon}>
                            <FileText size={22} />
                        </div>
                        <div className={s.aiFileMeta}>
                            <DialogTitle className={s.aiFileTitle}>{selectedFile.name}</DialogTitle>
                            <div className={s.aiFileFacts}>
                                <span>{documentPath}</span>
                                {updatedText ? <span>{updatedText}</span> : null}
                                {fileSizeText !== "-" ? <span>{fileSizeText}</span> : null}
                            </div>
                        </div>
                        <button
                            type="button"
                            className={s.aiDialogClose}
                            aria-label="关闭AI弹窗"
                            onClick={() => onOpenChange(false)}
                        >
                            <X size={18} />
                        </button>
                    </DialogHeader>
                    <div className={s.aiDialogBody}>
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
                        />
                    </div>
                </div>
            </DialogContent>
        </Dialog>
    );
}
