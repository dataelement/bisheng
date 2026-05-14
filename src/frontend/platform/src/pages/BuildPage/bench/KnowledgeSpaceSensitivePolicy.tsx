import { Checkbox } from "@/components/bs-ui/checkBox";
import { Textarea } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Switch } from "@/components/bs-ui/switch";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import {
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

export type KnowledgeSpaceSensitivePolicyHandle = {
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
        .replace(/[\r\n，、;；|]+/g, ",")
        .replace(/,+/g, ",")
        .replace(/^,|,$/g, "");
}

export const KnowledgeSpaceSensitivePolicy = forwardRef<KnowledgeSpaceSensitivePolicyHandle>(
function KnowledgeSpaceSensitivePolicy(_, ref) {
    const { t } = useTranslation();
    const { toast } = useToast();
    const [form, setForm] = useState<SensitiveForm>(DEFAULT_FORM);
    const [loaded, setLoaded] = useState(false);

    useEffect(() => {
        getSensitiveWordPolicyApi().then((policy) => {
            const next = {
                isCheck: Boolean(policy?.enabled),
                words: policy?.custom_words || "",
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
        }));
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
        setForm((prev) => ({
            ...prev,
            isCheck: checked,
        }));
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
            const formatContent = normalizeCustomWords(text);
            setForm((prev) => ({ ...prev, words: formatContent }));
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
                            {t("bench.knowledgeSpaceContentSecurityDesc", "对知识空间文件解析结果进行敏感词审查，命中后阻止写入向量库。")}
                        </p>
                    </div>
                    <Switch checked={form.isCheck} onCheckedChange={handleSwitchChange} />
                </div>
                {form.isCheck && (
                    <div className="mt-4 w-full max-w-[560px] rounded-lg border border-[#ECECEC] bg-[#FAFBFC] p-4">
                        <div>
                            <span className="bisheng-label">{t("build.wordListType")}</span>
                            <div className="mt-4 mb-6 space-y-3">
                                <div className="space-x-2 flex items-center">
                                    <Checkbox
                                        id="knowledge-sensitive-builtin"
                                        value="1"
                                        checked={form.wordsType?.includes(1)}
                                        onCheckedChange={(checked) => handleWordTypeChange(Boolean(checked), 1)}
                                    />
                                    <Label htmlFor="knowledge-sensitive-builtin" className="cursor-pointer">
                                        {t("build.builtinWordList")}
                                    </Label>
                                </div>
                                <div className="space-x-2 flex items-center">
                                    <Checkbox
                                        id="knowledge-sensitive-custom"
                                        value="2"
                                        checked={form.wordsType?.includes(2)}
                                        onCheckedChange={(checked) => handleWordTypeChange(Boolean(checked), 2)}
                                    />
                                    <Label htmlFor="knowledge-sensitive-custom" className="cursor-pointer">
                                        {t("build.customWordList")}
                                    </Label>
                                </div>
                            </div>
                            <div className="flex justify-center relative">
                                <Textarea
                                    className="h-[100px] resize-none"
                                    value={form.words}
                                    onChange={(event) => setForm({ ...form, words: event.target.value })}
                                    placeholder={t("build.useCommaToSeparate", "使用英文逗号分隔，例如：词1,词2,词3")}
                                />
                                <input
                                    type="file"
                                    accept=".txt"
                                    id="knowledgeSensitiveFileUpload"
                                    className="hidden"
                                    onChange={handleUploadFile}
                                />
                                <Label
                                    htmlFor="knowledgeSensitiveFileUpload"
                                    className="flex items-center absolute right-1 top-1 cursor-pointer"
                                >
                                    <Upload color="blue" className="w-3 h-3" />
                                    <span className="text-xs text-primary cursor-pointer">{t("build.txtFile")}</span>
                                </Label>
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
});
