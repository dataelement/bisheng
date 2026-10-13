import { useRef, useState } from "react";
import { FileStatus, uploadFileToServerApi } from "~/api/knowledge";
import { decideApprovalTaskApi } from "~/api/approval";
import { registerCorrectionUpdateFile } from "~/api/fileCorrection";

interface FileCorrectionDecisionProps {
    taskId: number;
    correctionId: number;
    spaceId: number | string;
    disabled: boolean;
    onDone: () => void;
    onError: (message: string) => void;
}

/** 纠错待办的采纳和采纳并更新. 拒绝仍由审批弹窗原按钮处理. */
export function FileCorrectionDecision({
    taskId,
    correctionId,
    spaceId,
    disabled,
    onDone,
    onError,
}: FileCorrectionDecisionProps) {
    const inputRef = useRef<HTMLInputElement>(null);
    const [pendingFileId, setPendingFileId] = useState<number | null>(null);
    const [busy, setBusy] = useState(false);

    async function handleAdopt() {
        if (busy || disabled) return;
        setBusy(true);
        try {
            await decideApprovalTaskApi(taskId, { action: "adopt" });
            onDone();
        } catch (error) {
            onError(error instanceof Error ? error.message : "采纳失败");
        } finally {
            setBusy(false);
        }
    }

    async function finishUpdate(fileId: number) {
        await decideApprovalTaskApi(taskId, { action: "adopt_update", new_file_id: fileId });
        setPendingFileId(null);
        onDone();
    }

    async function handlePickedFile(file: File) {
        setBusy(true);
        try {
            const uploaded = await uploadFileToServerApi(String(spaceId), file);
            const created = await registerCorrectionUpdateFile(correctionId, uploaded.file_path);
            const fileId = Number(created.id);
            if (created.status !== 2 && created.status !== FileStatus.SUCCESS) {
                setPendingFileId(fileId);
                onError("新文件还在解析, 解析完成后再点一次「采纳并更新」");
                return;
            }
            await finishUpdate(fileId);
        } catch (error) {
            onError(error instanceof Error ? error.message : "采纳并更新失败");
        } finally {
            setBusy(false);
        }
    }

    return (
        <>
            <input
                ref={inputRef}
                type="file"
                className="hidden"
                onChange={(event) => {
                    const file = event.target.files?.[0];
                    event.target.value = "";
                    if (file) void handlePickedFile(file);
                }}
            />
            <button
                type="button"
                disabled={disabled || busy}
                className="rounded-lg border border-[#165dff] px-4 py-2 text-[14px] text-[#165dff] hover:bg-[#f2f6ff] disabled:opacity-60"
                onClick={() => {
                    if (pendingFileId) {
                        setBusy(true);
                        void finishUpdate(pendingFileId)
                            .catch((error) => onError(error instanceof Error ? error.message : "采纳并更新失败"))
                            .finally(() => setBusy(false));
                        return;
                    }
                    inputRef.current?.click();
                }}
            >
                采纳并更新
            </button>
            <button
                type="button"
                disabled={disabled || busy}
                className="rounded-lg bg-[#165dff] px-5 py-2 text-[14px] text-white hover:bg-[#1350e8] disabled:opacity-60"
                onClick={() => void handleAdopt()}
            >
                采纳
            </button>
        </>
    );
}
