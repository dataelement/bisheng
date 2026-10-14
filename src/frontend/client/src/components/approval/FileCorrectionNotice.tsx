import { useEffect, useState } from "react";
import { getFileCorrection, type FileCorrectionRecord } from "~/api/fileCorrection";

interface FileCorrectionNoticeProps {
    correctionId: number | null;
    fileName?: string;
    spaceId?: number | string;
    fileId?: number | string;
}

type NoticeState = {
    loading: boolean;
    record: FileCorrectionRecord | null;
};

function hasTwoPartContent(record: FileCorrectionRecord | null): boolean {
    return Boolean(record?.original_error?.trim() && record?.corrected_content?.trim());
}

/** 审批详情里的纠错说明. 正文来自纠错接口, 不读审批快照. */
export function FileCorrectionNotice({ correctionId, fileName, spaceId, fileId }: FileCorrectionNoticeProps) {
    const [state, setState] = useState<NoticeState>({ loading: Boolean(correctionId), record: null });

    useEffect(() => {
        if (!correctionId) {
            setState({ loading: false, record: null });
            return;
        }
        let cancelled = false;
        setState({ loading: true, record: null });
        void getFileCorrection(correctionId)
            .then((record) => {
                if (!cancelled) setState({ loading: false, record });
            })
            .catch(() => {
                if (!cancelled) setState({ loading: false, record: null });
            });
        return () => {
            cancelled = true;
        };
    }, [correctionId]);

    function handleOpenDocument() {
        if (!spaceId || !fileId) return;
        const params = new URLSearchParams({
            spaceId: String(spaceId),
            fileId: String(fileId),
        });
        if (fileName) params.set("fileName", fileName);
        const target = window.top && window.top !== window ? window.top : window;
        target.location.assign(`/knowledge-spaces?${params.toString()}`);
    }

    const twoPart = hasTwoPartContent(state.record);
    const body = !correctionId
        ? "暂时无法显示纠错说明"
        : state.loading
            ? "正在加载纠错说明"
            : state.record == null
                ? "无权查看纠错说明"
                : null;

    return (
        <div data-testid="file-correction-notice">
            {body ? (
                <>
                    <div className="mb-2 text-[14px] font-medium text-[#1d2129]">纠错说明</div>
                    <div className="rounded-xl bg-[#fafbfc] p-4 text-[14px] text-[#4e5969] whitespace-pre-wrap break-all">
                        {body}
                    </div>
                </>
            ) : twoPart && state.record ? (
                <>
                    <div className="mb-2 text-[14px] font-medium text-[#1d2129]">原文错误处</div>
                    <div
                        className="rounded-xl bg-[#fafbfc] p-4 text-[14px] text-[#4e5969] whitespace-pre-wrap break-all"
                        data-testid="file-correction-original-error"
                    >
                        {state.record.original_error}
                    </div>
                    <div className="mb-2 mt-3 text-[14px] font-medium text-[#1d2129]">纠正后内容</div>
                    <div
                        className="rounded-xl bg-[#fafbfc] p-4 text-[14px] text-[#4e5969] whitespace-pre-wrap break-all"
                        data-testid="file-correction-corrected-content"
                    >
                        {state.record.corrected_content}
                    </div>
                </>
            ) : (
                <>
                    <div className="mb-2 text-[14px] font-medium text-[#1d2129]">纠错说明</div>
                    <div className="rounded-xl bg-[#fafbfc] p-4 text-[14px] text-[#4e5969] whitespace-pre-wrap break-all">
                        {state.record?.content}
                    </div>
                </>
            )}
            {spaceId && fileId ? (
                <button type="button" className="mt-3 text-[14px] text-[#165dff]" onClick={handleOpenDocument}>
                    打开文档
                </button>
            ) : null}
        </div>
    );
}
