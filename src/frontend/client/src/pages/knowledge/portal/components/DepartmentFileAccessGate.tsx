import { useMemo, useState } from "react";
import { FileLock2, Loader2 } from "lucide-react";
import type { DepartmentFileViewAccess } from "~/api/approval";

const STATUS_COPY: Record<
    DepartmentFileViewAccess["status"],
    { title: string; description: string }
> = {
    allowed: {
        title: "已获得查看权限",
        description: "正在加载文档内容。",
    },
    approval_required: {
        title: "查看此部门文件需要审批",
        description: "提交申请后，由文件所属部门的管理员审批。",
    },
    pending: {
        title: "查看申请审批中",
        description: "审批通过后即可查看文档详情和正文。",
    },
    rejected: {
        title: "上次查看申请未通过",
        description: "你可以补充新的申请原因后重新提交。",
    },
    withdrawn: {
        title: "上次查看申请已撤回",
        description: "如仍需查看，可重新提交申请。",
    },
    scenario_disabled: {
        title: "暂时无法提交查看申请",
        description: "部门文件查看审批当前已停用，请联系管理员。",
    },
    approver_unavailable: {
        title: "暂时找不到可审批人员",
        description: "请联系部门或系统管理员完成审批人配置。",
    },
    invalid_binding: {
        title: "文件归属配置异常",
        description: "当前文件无法申请查看，请联系管理员核对部门库绑定。",
    },
};

function metadataText(metadata: Record<string, unknown>, key: string): string {
    const value = metadata[key];
    return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

interface DepartmentFileAccessGateProps {
    access: DepartmentFileViewAccess;
    applying: boolean;
    error: string;
    onApply: (reason: string) => void | Promise<void>;
    onOpenRequests: () => void;
}

export function DepartmentFileAccessGate({
    access,
    applying,
    error,
    onApply,
    onOpenRequests,
}: DepartmentFileAccessGateProps) {
    const [reason, setReason] = useState("");
    const [validationError, setValidationError] = useState("");
    const copy = STATUS_COPY[access.status];
    const fileName = metadataText(access.safeMetadata, "file_name") || `文件 ${access.fileId}`;
    const spaceName = metadataText(access.safeMetadata, "space_name");
    const folderPath = metadataText(access.safeMetadata, "folder_path");
    const canApply = ["approval_required", "rejected", "withdrawn"].includes(access.status);
    const remaining = useMemo(() => 2000 - reason.length, [reason.length]);

    const handleSubmit = () => {
        const normalizedReason = reason.trim();
        if (!normalizedReason) {
            setValidationError("请填写申请原因");
            return;
        }
        if (normalizedReason.length > 2000) {
            setValidationError("申请原因不能超过2000个字符");
            return;
        }
        setValidationError("");
        void onApply(normalizedReason);
    };

    return (
        <section
            className="mx-auto flex h-full max-w-2xl flex-col items-center justify-center px-8 text-center"
            aria-live="polite"
            data-testid="department-file-access-gate"
        >
            <div className="mb-4 rounded-full bg-blue-50 p-4 text-blue-600">
                <FileLock2 size={30} />
            </div>
            <h1 className="text-xl font-semibold text-gray-900">{copy.title}</h1>
            <p className="mt-2 text-sm text-gray-500">{copy.description}</p>
            <dl className="mt-6 w-full rounded-lg bg-gray-50 p-4 text-left text-sm">
                <div className="flex gap-3"><dt className="w-20 text-gray-500">文件</dt><dd>{fileName}</dd></div>
                {spaceName ? (
                    <div className="mt-2 flex gap-3">
                        <dt className="w-20 text-gray-500">知识库</dt><dd>{spaceName}</dd>
                    </div>
                ) : null}
                {folderPath ? (
                    <div className="mt-2 flex gap-3">
                        <dt className="w-20 text-gray-500">所在目录</dt><dd>{folderPath}</dd>
                    </div>
                ) : null}
            </dl>

            {canApply ? (
                <div className="mt-6 w-full text-left">
                    <label className="text-sm font-medium text-gray-800" htmlFor="department-file-view-reason">
                        申请原因
                    </label>
                    <textarea
                        id="department-file-view-reason"
                        className="mt-2 min-h-28 w-full resize-none rounded-md border border-gray-200 p-3 text-sm outline-none focus:border-blue-500"
                        value={reason}
                        maxLength={2000}
                        placeholder="请说明查看该文件的业务用途"
                        onChange={(event) => {
                            setReason(event.target.value);
                            if (validationError) setValidationError("");
                        }}
                    />
                    <div className="mt-1 text-right text-xs text-gray-400">{remaining} / 2000</div>
                    {validationError || error ? (
                        <p className="mt-2 text-sm text-red-600" role="alert">
                            {validationError || error}
                        </p>
                    ) : null}
                    <button
                        type="button"
                        className="mt-4 flex w-full items-center justify-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm text-white disabled:opacity-60"
                        disabled={applying}
                        onClick={handleSubmit}
                    >
                        {applying ? <Loader2 size={16} className="animate-spin" /> : null}
                        {applying ? "正在提交" : "提交查看申请"}
                    </button>
                </div>
            ) : error ? (
                <p className="mt-4 text-sm text-red-600" role="alert">{error}</p>
            ) : null}

            {access.instanceId ? (
                <button
                    type="button"
                    className="mt-4 text-sm text-blue-600 hover:text-blue-700"
                    onClick={onOpenRequests}
                >
                    打开我的申请
                </button>
            ) : null}
        </section>
    );
}
