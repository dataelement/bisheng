// @ts-strict-ignore
import { Checkbox } from "@/components/bs-ui/checkBox";
import { Textarea } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Switch } from "@/components/bs-ui/switch";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import {
    getSensitiveWordPolicyApi,
    updateSensitiveWordPolicyApi,
    WORKBENCH_CHAT_POLICY,
    type SensitiveWordType,
} from "@/controllers/API/sensitiveWordPolicy";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { Upload } from "lucide-react";
import type { ChangeEvent } from "react";
import { forwardRef, useEffect, useImperativeHandle, useState } from "react";
import { useTranslation } from "react-i18next";

type SensitiveForm = {
    isCheck: boolean;
    words: string;
    wordsType: number[];
    autoReply: string;
};

type FieldErrors = {
    wordsType: string;
    autoReply: string;
};

const DEFAULT_FORM: SensitiveForm = {
    isCheck: false,
    words: "",
    wordsType: [],
    autoReply: "",
};

const EMPTY_FIELD_ERRORS: FieldErrors = {
    wordsType: "",
    autoReply: "",
};

export type WorkbenchSensitivePolicyHandle = {
    save: () => Promise<boolean>;
};

function toWordsType(wordsTypes: SensitiveWordType[] = []) {
    return wordsTypes
        .map((item) => item === "builtin" ? 1 : item === "custom" ? 2 : null)
        .filter((item): item is number => item !== null);
}

function toApiWordsType(wordsType: number[] = []): SensitiveWordType[] {
    return wordsType
        .map((item) => item === 1 ? "builtin" : item === 2 ? "custom" : null)
        .filter((item): item is SensitiveWordType => item !== null);
}

function normalizeCustomWords(words: string) {
    return words
        .split(/[\r\n,，、;；|\s]+/)
        .map((word) => word.trim())
        .filter(Boolean)
        .join("\n");
}

export const WorkbenchSensitivePolicy = forwardRef<WorkbenchSensitivePolicyHandle>(
function WorkbenchSensitivePolicy(_, ref) {
    const { t } = useTranslation();
    const { toast } = useToast();
    const [form, setForm] = useState<SensitiveForm>(DEFAULT_FORM);
    const [fieldErrors, setFieldErrors] = useState<FieldErrors>(EMPTY_FIELD_ERRORS);
    const [loaded, setLoaded] = useState(false);

    useEffect(() => {
        getSensitiveWordPolicyApi(WORKBENCH_CHAT_POLICY).then((policy) => {
            setForm({
                isCheck: Boolean(policy?.enabled),
                words: normalizeCustomWords(policy?.custom_words || ""),
                wordsType: toWordsType(policy?.words_types),
                autoReply: policy?.auto_reply || "",
            });
            setLoaded(true);
        });
    }, []);

    const savePolicy = async (nextForm: SensitiveForm) => {
        const res = await captureAndAlertRequestErrorHoc(updateSensitiveWordPolicyApi({
            enabled: nextForm.isCheck,
            words_types: toApiWordsType(nextForm.wordsType),
            custom_words: nextForm.words || "",
            auto_reply: nextForm.autoReply || "",
            extra_config: {},
        }, WORKBENCH_CHAT_POLICY));
        if (res) {
            setForm(nextForm);
        }
        return Boolean(res);
    };

    const validateForm = (nextForm: SensitiveForm) => {
        if (!nextForm.isCheck) {
            setFieldErrors(EMPTY_FIELD_ERRORS);
            return true;
        }
        const nextErrors: FieldErrors = { ...EMPTY_FIELD_ERRORS };
        if (nextForm.wordsType.length === 0) {
            nextErrors.wordsType = t("build.errors.workbenchSelectAtLeastOneWordType");
        }
        const autoReply = (nextForm.autoReply || "").trim();
        if (!autoReply) {
            nextErrors.autoReply = t("build.errors.workbenchAutoReplyNotEmpty");
        } else if (autoReply.length > 500) {
            nextErrors.autoReply = t("build.errors.workbenchAutoReplyMaxLength");
        }
        setFieldErrors(nextErrors);
        return !nextErrors.wordsType && !nextErrors.autoReply;
    };

    useImperativeHandle(ref, () => ({
        save: async () => {
            if (!loaded) {
                toast({
                    title: t("prompt"),
                    variant: "error",
                    description: t("build.errors.sensitivePolicyLoading", "敏感词配置加载中，请稍后再试"),
                });
                return false;
            }
            const nextForm = {
                ...form,
                words: normalizeCustomWords(form.words),
                autoReply: form.autoReply,
            };
            if (!validateForm(nextForm)) return false;
            return savePolicy(nextForm);
        },
    }), [form, loaded, t, toast]);

    const handleSwitchChange = (checked: boolean) => {
        setForm((prev) => ({ ...prev, isCheck: checked }));
        if (!checked) {
            setFieldErrors(EMPTY_FIELD_ERRORS);
        }
    };

    const handleWordTypeChange = (checked: boolean, value: number) => {
        setForm((prev) => {
            const wordsType = prev.wordsType || [];
            if (checked && !wordsType.includes(value)) {
                return { ...prev, wordsType: [...wordsType, value] };
            }
            return { ...prev, wordsType: wordsType.filter((item) => item !== value) };
        });
        setFieldErrors((prev) => ({ ...prev, wordsType: "" }));
    };

    const handleUploadFile = (event: ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (readerEvent) => {
            const text = String(readerEvent.target?.result || "");
            setForm((prev) => ({ ...prev, words: normalizeCustomWords(text) }));
        };
        reader.readAsText(file);
        event.target.value = "";
    };

    return (
        <div className="p-5 rounded-lg">
            <div className="border-t border-[#ECECEC] pt-6">
                <div className="flex items-center justify-between gap-4">
                    <div>
                        <div className="flex items-center gap-2">
                            <p className="text-lg font-bold">
                                {t("build.contentSecurityReview", "内容安全审查")}
                            </p>
                        </div>
                        <p className="mt-1 text-sm text-[#86909C]">
                            {t("bench.workbenchContentSecurityDesc")}
                        </p>
                    </div>
                    <Switch checked={form.isCheck} onCheckedChange={handleSwitchChange} />
                </div>
                {form.isCheck && (
                    <div className="mt-4 w-full max-w-[560px] rounded-lg border border-[#ECECEC] bg-[#FAFBFC] p-4">
                        <div>
                            <span className="bisheng-label">{t("build.wordListType")}</span>
                            <div className="mt-4 space-y-3">
                                <div className="space-x-2 flex items-center">
                                    <Checkbox
                                        id="workbench-sensitive-builtin"
                                        value="1"
                                        checked={form.wordsType?.includes(1)}
                                        onCheckedChange={(checked) => handleWordTypeChange(Boolean(checked), 1)}
                                    />
                                    <Label htmlFor="workbench-sensitive-builtin" className="cursor-pointer">
                                        {t("build.builtinWordList")}
                                    </Label>
                                </div>
                                <div className="space-x-2 flex items-center">
                                    <Checkbox
                                        id="workbench-sensitive-custom"
                                        value="2"
                                        checked={form.wordsType?.includes(2)}
                                        onCheckedChange={(checked) => handleWordTypeChange(Boolean(checked), 2)}
                                    />
                                    <Label htmlFor="workbench-sensitive-custom" className="cursor-pointer">
                                        {t("build.customWordList")}
                                    </Label>
                                </div>
                            </div>
                            {form.wordsType?.includes(2) && (
                                <div className="flex justify-center relative mt-4">
                                    <Textarea
                                        className="h-[100px] resize-none"
                                        value={form.words}
                                        onChange={(event) => setForm({ ...form, words: event.target.value })}
                                        placeholder={t("bench.workbenchCustomWordsPlaceholder")}
                                    />
                                    <input
                                        type="file"
                                        accept=".txt"
                                        id="workbenchSensitiveFileUpload"
                                        className="hidden"
                                        onChange={handleUploadFile}
                                    />
                                    <Label
                                        htmlFor="workbenchSensitiveFileUpload"
                                        className="flex items-center absolute right-1 top-1 cursor-pointer"
                                    >
                                        <Upload color="blue" className="w-3 h-3" />
                                        <span className="text-xs text-primary cursor-pointer">{t("build.txtFile")}</span>
                                    </Label>
                                </div>
                            )}
                            {fieldErrors.wordsType && (
                                <p className="text-red-500 text-xs mt-1">{fieldErrors.wordsType}</p>
                            )}
                        </div>
                        <div className="mt-6">
                            <span className="bisheng-label">{t("build.autoReplyContent")}</span>
                            <div className="flex justify-center mt-4">
                                <Textarea
                                    className="h-[100px] resize-none"
                                    value={form.autoReply}
                                    onChange={(event) => {
                                        setForm({ ...form, autoReply: event.target.value });
                                        setFieldErrors((prev) => ({ ...prev, autoReply: "" }));
                                    }}
                                    maxLength={500}
                                    placeholder={t("bench.workbenchAutoReplyPlaceholder")}
                                />
                            </div>
                            {fieldErrors.autoReply && (
                                <p className="text-red-500 text-xs mt-1">{fieldErrors.autoReply}</p>
                            )}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
});
