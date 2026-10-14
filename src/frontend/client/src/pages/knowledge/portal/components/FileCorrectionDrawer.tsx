import { useState } from "react";
import { Loader2, X } from "lucide-react";
import { FILE_CORRECTION_CONTENT_LIMIT, submitFileCorrection } from "~/api/fileCorrection";
import { Button } from "~/components/ui/Button";
import { Textarea } from "~/components/ui/Textarea";
import s from "../PortalKnowledgeWorkbench.module.css";

interface FileCorrectionDrawerProps {
    fileId: string;
    fileName: string;
    onClose: () => void;
    onSubmitted: () => void;
    onError: (message: string) => void;
}

function fieldLength(value: string): number {
    return Array.from(value).length;
}

/** 阅读页右侧纠错抽屉. 两段都必填, 不改文档. */
export function FileCorrectionDrawer({
    fileId,
    fileName,
    onClose,
    onSubmitted,
    onError,
}: FileCorrectionDrawerProps) {
    const [originalError, setOriginalError] = useState("");
    const [correctedContent, setCorrectedContent] = useState("");
    const [pending, setPending] = useState(false);
    const originalLength = fieldLength(originalError);
    const correctedLength = fieldLength(correctedContent);
    const canSubmit = Boolean(originalError.trim() && correctedContent.trim()) && !pending
        && originalLength <= FILE_CORRECTION_CONTENT_LIMIT
        && correctedLength <= FILE_CORRECTION_CONTENT_LIMIT;

    async function handleSubmit() {
        if (!canSubmit) return;
        setPending(true);
        try {
            await submitFileCorrection(fileId, {
                originalError: originalError.trim(),
                correctedContent: correctedContent.trim(),
            });
            setOriginalError("");
            setCorrectedContent("");
            onClose();
            onSubmitted();
        } catch (error) {
            onError(error instanceof Error ? error.message : "提交失败");
        } finally {
            setPending(false);
        }
    }

    return (
        <aside className={s.drawer} data-testid="file-correction-drawer">
            <div className={s.drawerHeader}>
                <div className={s.drawerTitle}>纠错</div>
                <button
                    type="button"
                    className={s.toolbarButton}
                    onClick={onClose}
                    disabled={pending}
                    aria-label="关闭"
                >
                    <X size={14} />
                </button>
            </div>
            <div className={s.drawerBody}>
                <div className={s.correctionFileName}>{fileName}</div>
                <div className={s.correctionField}>
                    <label htmlFor="file-correction-original-error" className={s.detailLabel}>原文错误处</label>
                    <Textarea
                        id="file-correction-original-error"
                        value={originalError}
                        maxLength={FILE_CORRECTION_CONTENT_LIMIT}
                        rows={6}
                        aria-label="原文错误处"
                        placeholder="请填写原文中错误的地方"
                        disabled={pending}
                        onChange={(event) => setOriginalError(event.target.value)}
                    />
                    <span className={s.correctionCounter}>
                        {originalLength}/{FILE_CORRECTION_CONTENT_LIMIT}
                    </span>
                </div>
                <div className={s.correctionField}>
                    <label htmlFor="file-correction-corrected-content" className={s.detailLabel}>纠正后内容</label>
                    <Textarea
                        id="file-correction-corrected-content"
                        value={correctedContent}
                        maxLength={FILE_CORRECTION_CONTENT_LIMIT}
                        rows={6}
                        aria-label="纠正后内容"
                        placeholder="请填写纠正后的内容"
                        disabled={pending}
                        onChange={(event) => setCorrectedContent(event.target.value)}
                    />
                    <span className={s.correctionCounter}>
                        {correctedLength}/{FILE_CORRECTION_CONTENT_LIMIT}
                    </span>
                </div>
            </div>
            <div className={s.drawerFooter}>
                <Button type="button" disabled={!canSubmit} onClick={() => void handleSubmit()}>
                    {pending ? <Loader2 className="animate-spin" size={16} /> : "提交"}
                </Button>
            </div>
        </aside>
    );
}
