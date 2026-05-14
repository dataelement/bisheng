import { Checkbox } from "@/components/bs-ui/checkBox";
import { Textarea } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Switch } from "@/components/bs-ui/switch";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import {
    CHANNEL_ARTICLE_POLICY,
    getSensitiveWordPolicyApi,
    updateSensitiveWordPolicyApi,
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
};

const DEFAULT_FORM: SensitiveForm = {
    isCheck: false,
    words: "",
    wordsType: [],
};

export type SubscriptionSensitivePolicyHandle = {
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
        .split(/[\r\n,，、;；|]+/)
        .map((word) => word.trim())
        .filter(Boolean)
        .join("\n");
}

export const SubscriptionSensitivePolicy = forwardRef<SubscriptionSensitivePolicyHandle>(
function SubscriptionSensitivePolicy(_, ref) {
    const { t } = useTranslation();
    const { toast } = useToast();
    const [form, setForm] = useState<SensitiveForm>(DEFAULT_FORM);
    const [loaded, setLoaded] = useState(false);

    useEffect(() => {
        getSensitiveWordPolicyApi(CHANNEL_ARTICLE_POLICY).then((policy) => {
            const next = {
                isCheck: Boolean(policy?.enabled),
                words: normalizeCustomWords(policy?.custom_words || ""),
                wordsType: toWordsType(policy?.words_types),
            };
            setForm(next);
            setLoaded(true);
        });
    }, []);

    const savePolicy = async (nextForm: SensitiveForm) => {
        const res = await captureAndAlertRequestErrorHoc(updateSensitiveWordPolicyApi({
            enabled: nextForm.isCheck,
            words_types: toApiWordsType(nextForm.wordsType),
            custom_words: nextForm.words || "",
            extra_config: {},
        }, CHANNEL_ARTICLE_POLICY));
        if (res) {
            setForm(nextForm);
        }
        return Boolean(res);
    };

    const validateForm = (nextForm: SensitiveForm) => {
        if (!nextForm.isCheck) return true;
        const errors: string[] = [];
        if (nextForm.wordsType.length === 0) errors.push(t("build.errors.selectAtLeastOneWordType"));
        if (nextForm.wordsType.includes(2) && !nextForm.words?.trim()) {
            errors.push(t("build.errors.customWordsNotEmpty", "自定义词表不能为空"));
        }
        if (errors.length) {
            toast({ title: t("prompt"), variant: "error", description: errors.join(", ") });
            return false;
        }
        return true;
    };

    useImperativeHandle(ref, () => ({
        save: async () => {
            if (!loaded) {
                toast({ title: t("prompt"), variant: "error", description: t("build.errors.sensitivePolicyLoading", "敏感词配置加载中，请稍后再试") });
                return false;
            }
            const nextForm = { ...form, words: normalizeCustomWords(form.words) };
            if (!validateForm(nextForm)) return false;
            return savePolicy(nextForm);
        },
    }), [form, loaded, t, toast]);

    const handleSwitchChange = (checked: boolean) => {
        setForm((prev) => ({ ...prev, isCheck: checked }));
    };

    const handleWordTypeChange = (checked: boolean, value: number) => {
        setForm((prev) => {
            const wordsType = prev.wordsType || [];
            if (checked && !wordsType.includes(value)) {
                return { ...prev, wordsType: [...wordsType, value] };
            }
            return { ...prev, wordsType: wordsType.filter((item) => item !== value) };
        });
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
        <div className="mb-6 rounded-lg border border-[#ECECEC] bg-white p-5">
            <div className="flex items-center justify-between gap-4">
                <div>
                    <p className="text-lg font-bold">{t("build.contentSecurityReview", "内容安全审查")}</p>
                    <p className="mt-1 text-sm text-[#86909C]">
                        {t("bench.subscriptionContentSecurityDesc", "对订阅文章进行敏感词审查，命中后普通用户不可查看详情。")}
                    </p>
                </div>
                <Switch checked={form.isCheck} onCheckedChange={handleSwitchChange} />
            </div>

            {form.isCheck && (
                <div className="mt-4 w-full max-w-[560px] rounded-lg border border-[#ECECEC] bg-[#FAFBFC] p-4">
                    <div>
                        <span className="bisheng-label">{t("build.wordListType")}</span>
                        <div className="mt-4 mb-6 space-y-3">
                            <div className="flex items-center space-x-2">
                                <Checkbox
                                    id="subscription-sensitive-builtin"
                                    checked={form.wordsType?.includes(1)}
                                    onCheckedChange={(checked) => handleWordTypeChange(Boolean(checked), 1)}
                                />
                                <Label htmlFor="subscription-sensitive-builtin" className="cursor-pointer">
                                    {t("build.builtinWordList")}
                                </Label>
                            </div>
                            <div className="flex items-center space-x-2">
                                <Checkbox
                                    id="subscription-sensitive-custom"
                                    checked={form.wordsType?.includes(2)}
                                    onCheckedChange={(checked) => handleWordTypeChange(Boolean(checked), 2)}
                                />
                                <Label htmlFor="subscription-sensitive-custom" className="cursor-pointer">
                                    {t("build.customWordList")}
                                </Label>
                            </div>
                        </div>
                        <div className="relative flex justify-center">
                            <Textarea
                                className="h-[100px] resize-none"
                                value={form.words}
                                onChange={(event) => setForm({ ...form, words: event.target.value })}
                                placeholder={t("bench.customWordsNewlinePlaceholder", "使用换行符进行分割，每行一个")}
                            />
                            <input
                                type="file"
                                accept=".txt"
                                id="subscriptionSensitiveFileUpload"
                                className="hidden"
                                onChange={handleUploadFile}
                            />
                            <Label
                                htmlFor="subscriptionSensitiveFileUpload"
                                className="absolute right-1 top-1 flex cursor-pointer items-center"
                            >
                                <Upload color="blue" className="h-3 w-3" />
                                <span className="cursor-pointer text-xs text-primary">{t("build.txtFile")}</span>
                            </Label>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
});
