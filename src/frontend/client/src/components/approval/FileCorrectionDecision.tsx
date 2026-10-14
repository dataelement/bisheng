import { useRef, useState } from "react";
import { uploadFileToServerApi } from "~/api/knowledge";
import { decideApprovalTaskApi } from "~/api/approval";
import {
    registerCorrectionUpdateFile,
    retryCorrectionUpdateFile,
    type FileCorrectionUpdatePhase,
} from "~/api/fileCorrection";

interface FileCorrectionDecisionProps {
    taskId: number;
    correctionId: number;
    spaceId: number | string;
    disabled: boolean;
    updatePhase: FileCorrectionUpdatePhase;
    onPhaseReload: () => void;
    onDone: () => void;
    onError: (message: string) => void;
}

/** 纠错待办的采纳和采纳并更新. 拒绝仍由审批弹窗原按钮处理. */
export function FileCorrectionDecision({
    taskId,
    correctionId,
    spaceId,
    disabled,
    updatePhase,
    onPhaseReload,
    onDone,
    onError,
}: FileCorrectionDecisionProps) {
    const inputRef = useRef<HTMLInputElement>(null);
    const [busy, setBusy] = useState(false);
    const locked = disabled || busy || updatePhase === "updating";

    async function handleAdopt() {
        if (locked) return;
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

    async function handlePickedFile(file: File) {
        setBusy(true);
        try {
            const uploaded = await uploadFileToServerApi(String(spaceId), file);
            await registerCorrectionUpdateFile(correctionId, uploaded.file_path);
            onPhaseReload();
        } catch (error) {
            onError(error instanceof Error ? error.message : "采纳并更新失败");
        } finally {
            setBusy(false);
        }
    }

    async function handleRetry() {
        if (locked) return;
        setBusy(true);
        try {
            await retryCorrectionUpdateFile(correctionId);
            onPhaseReload();
        } catch (error) {
            onError(error instanceof Error ? error.message : "重新解析失败");
        } finally {
            setBusy(false);
        }
    }

    if (updatePhase === "updating") {
        return (
            <button
                type="button"
                disabled
                className="rounded-lg border border-[#c9cdd4] px-4 py-2 text-[14px] text-[#86909c] disabled:opacity-60"
            >
                更新中
            </button>
        );
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
            {updatePhase === "failed" ? (
                <>
                    <button
                        type="button"
                        disabled={locked}
                        className="rounded-lg border border-[#165dff] px-4 py-2 text-[14px] text-[#165dff] hover:bg-[#f2f6ff] disabled:opacity-60"
                        onClick={() => void handleRetry()}
                    >
                        重新解析
                    </button>
                    <button
                        type="button"
                        disabled={locked}
                        className="rounded-lg border border-[#165dff] px-4 py-2 text-[14px] text-[#165dff] hover:bg-[#f2f6ff] disabled:opacity-60"
                        onClick={() => inputRef.current?.click()}
                    >
                        重新上传
                    </button>
                </>
            ) : (
                <button
                    type="button"
                    disabled={locked}
                    className="rounded-lg border border-[#165dff] px-4 py-2 text-[14px] text-[#165dff] hover:bg-[#f2f6ff] disabled:opacity-60"
                    onClick={() => inputRef.current?.click()}
                >
                    采纳并更新
                </button>
            )}
            <button
                type="button"
                disabled={locked}
                className="rounded-lg bg-[#165dff] px-5 py-2 text-[14px] text-white hover:bg-[#1350e8] disabled:opacity-60"
                onClick={() => void handleAdopt()}
            >
                采纳
            </button>
        </>
    );
}
