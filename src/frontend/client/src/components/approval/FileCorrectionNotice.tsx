import { useEffect, useState } from "react";
import { getFileCorrection } from "~/api/fileCorrection";

interface FileCorrectionNoticeProps {
    correctionId: number | null;
    fileName?: string;
    spaceId?: number | string;
    fileId?: number | string;
}

/** 审批详情里的纠错说明. 正文来自纠错接口, 不读审批快照. */
export function FileCorrectionNotice({ correctionId, fileName, spaceId, fileId }: FileCorrectionNoticeProps) {
    const [content, setContent] = useState<string | null>(null);
    const [loading, setLoading] = useState(Boolean(correctionId));

    useEffect(() => {
        if (!correctionId) {
            setContent(null);
            setLoading(false);
            return;
        }
        let cancelled = false;
        setLoading(true);
        setContent(null);
        void getFileCorrection(correctionId)
            .then((record) => {
                if (!cancelled) setContent(record.content);
            })
            .catch(() => {
                if (!cancelled) setContent(null);
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
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

    return (
        <div data-testid="file-correction-notice">
            <div className="mb-2 text-[14px] font-medium text-[#1d2129]">纠错说明</div>
            <div className="rounded-xl bg-[#fafbfc] p-4 text-[14px] text-[#4e5969] whitespace-pre-wrap break-all">
                {!correctionId
                    ? "暂时无法显示纠错说明"
                    : loading
                        ? "正在加载纠错说明"
                        : content == null
                            ? "无权查看纠错说明"
                            : content}
            </div>
            {spaceId && fileId ? (
                <button type="button" className="mt-3 text-[14px] text-[#165dff]" onClick={handleOpenDocument}>
                    打开文档
                </button>
            ) : null}
        </div>
    );
}
