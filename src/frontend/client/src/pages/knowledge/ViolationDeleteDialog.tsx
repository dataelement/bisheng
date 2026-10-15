import { useEffect, useState } from "react";
import { AlertTriangle, Trash2 } from "lucide-react";
import {
    commitViolationDeleteApi,
    previewViolationDeleteApi,
    type ViolationDeletePreview,
    type ViolationDeleteRuleOption,
} from "~/api/knowledge";
import { Button } from "~/components";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "~/components/ui/Dialog";
import { useLocalize } from "~/hooks";

interface ViolationDeleteDialogProps {
    fileId: string | null;
    fileName?: string;
    onClose: () => void;
    /** 不扣分: 走当前删除, 不扩大删除范围. 普通删除接口没有原因字段. */
    onDeleteWithoutDeduct: () => void;
    /** 按规则扣分成功后刷新列表. */
    onDeducted: () => void;
}

const fieldClassName = "mt-1.5 w-full rounded-lg border border-[#E5E6EB] bg-white px-2.5 py-2 text-sm text-[#1D2129] outline-none focus:border-[#165DFF] disabled:opacity-50";

/** 删除确认. 下拉默认不扣分; 选了规则才走违规删除接口. */
export function ViolationDeleteDialog({
    fileId,
    fileName,
    onClose,
    onDeleteWithoutDeduct,
    onDeducted,
}: ViolationDeleteDialogProps) {
    const localize = useLocalize();
    const [rules, setRules] = useState<ViolationDeleteRuleOption[]>([]);
    const [ruleCode, setRuleCode] = useState("");
    const [remark, setRemark] = useState("");
    const [preview, setPreview] = useState<ViolationDeletePreview | null>(null);
    const [loadingRules, setLoadingRules] = useState(false);
    const [previewing, setPreviewing] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");

    useEffect(() => {
        setRules([]);
        setRuleCode("");
        setRemark("");
        setPreview(null);
        setError("");
        if (!fileId) return;
        let cancelled = false;
        setLoadingRules(true);
        previewViolationDeleteApi(fileId)
            .then((data) => {
                if (!cancelled) setRules(data.rules);
            })
            .catch((err: Error) => {
                if (!cancelled) setError(err.message || localize("com_knowledge.violation_delete_failed"));
            })
            .finally(() => {
                if (!cancelled) setLoadingRules(false);
            });
        return () => {
            cancelled = true;
        };
        // localize 每次渲染都是新函数, 放进依赖会反复请求预览.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [fileId]);

    useEffect(() => {
        if (!fileId || !ruleCode) {
            setPreview(null);
            setPreviewing(false);
            return;
        }
        let cancelled = false;
        setPreviewing(true);
        setError("");
        previewViolationDeleteApi(fileId, ruleCode)
            .then((data) => {
                if (!cancelled) setPreview(data);
            })
            .catch((err: Error) => {
                if (!cancelled) {
                    setPreview(null);
                    setError(err.message || localize("com_knowledge.violation_delete_failed"));
                }
            })
            .finally(() => {
                if (!cancelled) setPreviewing(false);
            });
        return () => {
            cancelled = true;
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [fileId, ruleCode]);

    const blockedReason = preview?.reason === "monthly_award_exempt"
        || preview?.reason === "self_author"
        || preview?.reason === "payee_missing";
    const reasonText = preview?.reason === "monthly_award_exempt"
        ? localize("com_knowledge.delete_point_reason_monthly")
        : preview?.reason === "self_author"
            ? localize("com_knowledge.delete_point_reason_self")
            : preview?.reason === "payee_missing"
                ? localize("com_knowledge.delete_point_reason_payee")
                : "";

    function levelLabel(level: string) {
        const key = `com_knowledge.library_level_${level}`;
        const text = localize(key);
        return text === key ? level : text;
    }

    function handleRuleChange(nextCode: string) {
        setRuleCode(nextCode);
        const picked = rules.find((rule) => rule.rule_code === nextCode);
        setRemark(picked?.name?.trim() || "");
        setError("");
    }

    async function handleConfirm() {
        if (!fileId || loadingRules) return;
        if (!ruleCode) {
            onDeleteWithoutDeduct();
            onClose();
            return;
        }
        if (!preview?.can_deduct || previewing) return;
        setBusy(true);
        setError("");
        try {
            await commitViolationDeleteApi(fileId, ruleCode, remark);
            onDeducted();
            onClose();
        } catch (err) {
            setError(err instanceof Error ? err.message : localize("com_knowledge.violation_delete_failed"));
        } finally {
            setBusy(false);
        }
    }

    const libraryText = preview
        ? [...new Set(preview.libraries.map((item) => levelLabel(item.level)))].join("、")
        : "";
    const confirmDisabled = busy
        || loadingRules
        || (Boolean(ruleCode) && (previewing || !preview?.can_deduct));

    return (
        <Dialog open={Boolean(fileId)} onOpenChange={(open) => { if (!open && !busy) onClose(); }}>
            <DialogContent className="max-w-[480px] gap-3 p-6 text-center sm:max-w-[480px]">
                <AlertTriangle className="mx-auto size-8 text-[#f53f3f]" aria-hidden />
                <DialogHeader className="items-center space-y-0 text-center sm:text-center">
                    <DialogTitle className="text-base font-medium text-[#1D2129]">
                        {localize("com_knowledge.delete")}
                    </DialogTitle>
                </DialogHeader>
                <p className="text-sm leading-6 text-[#4E5969]">
                    {localize("com_knowledge.delete_point_intro", { 0: fileName || "" })}
                </p>
                <div className="text-left">
                    <label htmlFor="knowledge-delete-rule" className="block text-[13px] text-[#4E5969]">
                        {localize("com_knowledge.delete_point_rule_optional")}
                    </label>
                    <select
                        id="knowledge-delete-rule"
                        className={fieldClassName}
                        value={ruleCode}
                        disabled={busy || loadingRules}
                        onChange={(event) => handleRuleChange(event.target.value)}
                    >
                        <option value="">
                            {loadingRules
                                ? localize("com_knowledge.delete_point_loading")
                                : localize("com_knowledge.delete_point_option_skip")}
                        </option>
                        {rules.map((rule) => (
                            <option key={rule.rule_code} value={rule.rule_code}>
                                {rule.rule_code} · {rule.name}
                            </option>
                        ))}
                    </select>
                    <label htmlFor="knowledge-delete-remark" className="mt-3 block text-[13px] text-[#4E5969]">
                        {ruleCode
                            ? localize("com_knowledge.delete_point_remark_deduct")
                            : localize("com_knowledge.delete_point_remark_delete")}
                    </label>
                    <textarea
                        id="knowledge-delete-remark"
                        className={`${fieldClassName} min-h-[88px] resize-y`}
                        rows={3}
                        maxLength={200}
                        value={remark}
                        disabled={busy}
                        placeholder={ruleCode
                            ? localize("com_knowledge.delete_point_remark_placeholder_deduct")
                            : localize("com_knowledge.delete_point_remark_placeholder_delete")}
                        onChange={(event) => setRemark(event.target.value)}
                    />
                    {ruleCode && libraryText ? (
                        <p className="mt-2 text-sm leading-6 text-[#4E5969]">
                            {localize("com_knowledge.delete_point_libraries", { 0: libraryText })}
                        </p>
                    ) : null}
                    {reasonText ? <p className="mt-2 text-sm leading-6 text-[#4E5969]">{reasonText}</p> : null}
                    {preview?.score != null && preview.can_deduct ? (
                        <p className="mt-2 text-sm leading-6 text-[#1D2129]">
                            {localize("com_knowledge.delete_point_score", { 0: preview.score })}
                        </p>
                    ) : null}
                </div>
                {error ? <p className="text-left text-sm text-[#f53f3f]" role="alert">{error}</p> : null}
                {!loadingRules && rules.length === 0 && !error ? (
                    <p className="text-left text-sm text-[#4E5969]">
                        {localize("com_knowledge.delete_point_reason_no_rule")}
                    </p>
                ) : null}
                <div className="mt-2 flex justify-center gap-2">
                    <Button type="button" variant="outline" disabled={busy} onClick={onClose}>
                        {localize("com_knowledge.cancel")}
                    </Button>
                    <Button
                        type="button"
                        variant="outline"
                        className="border-[#ffccc7] bg-[#fff2f0] text-[#f53f3f] hover:bg-[#ffece8] hover:text-[#f53f3f]"
                        disabled={confirmDisabled}
                        onClick={() => void handleConfirm()}
                    >
                        <Trash2 className="size-3.5" />
                        {busy
                            ? localize("com_knowledge.delete_point_busy")
                            : localize("com_knowledge.delete_point_confirm")}
                    </Button>
                </div>
            </DialogContent>
        </Dialog>
    );
}
