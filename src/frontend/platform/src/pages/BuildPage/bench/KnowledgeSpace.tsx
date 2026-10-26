import { Button, Input, Textarea, notification } from '@bisheng/ui';

import { CardContent } from "@/components/bs-ui/card";
import { NonNegativeInput } from '@/components/bs-comp/formFields/NonNegativeInput';
import { Label } from "@/components/bs-ui/label";

import { locationContext } from "@/contexts/locationContext";
import { userContext } from "@/contexts/userContext";
import { getKnowledgeConfigApi, setKnowledgeConfigApi } from "@/controllers/API";
import {
    getDepartmentKnowledgeSpacesApi,
    type DepartmentKnowledgeSpaceSummary,
} from "@/controllers/API/departmentKnowledgeSpace";
import { handleUiRequest, showApiError } from "@/controllers/request";
import { canManageWorkbenchConfig, isGlobalSuperUser } from "@/pages/ModelPage/manage/permissions";
import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import ConfigInheritanceBanner, { resolveConfigEnvelope } from "./ConfigInheritanceBanner";
import { resolveConfigString } from "./configValue";
import { DepartmentKnowledgeSpaceManagerDialog } from "./DepartmentKnowledgeSpaceManagerDialog";
import { FormInput } from "./FormInput";
import {
    KnowledgeSpaceSensitivePolicy,
    type KnowledgeSpaceSensitivePolicyHandle,
} from "./KnowledgeSpaceSensitivePolicy";
import KnowledgeSpaceTagLibrarySection from "./KnowledgeSpaceTagLibrarySection";
import { clampMenuName, toStoredMenuName } from "./menuDisplayName";
import Preview from "./Preview";

interface KnowledgeConfigForm {
    systemPrompt: string;

    userPrompt: string;

    maxChunkSize: number;

    autoTagVisible: boolean;

    assistantName: string;

    menuDisplayName: string;
}

export default function KnowledgeSpace({ scopeVersion = 0 }: { scopeVersion?: number }) {
    const { t } = useTranslation();
    const {
        formData,
        setFormData,
        errors,
        setErrors,
        handleSave: saveKnowledgeConfig,
        configMeta,
    } = useKnowledgeConfig(scopeVersion);
    const sensitivePolicyRef = useRef<KnowledgeSpaceSensitivePolicyHandle>(null);
    const [managerOpen, setManagerOpen] = useState(false);
    const [departmentSpaces, setDepartmentSpaces] = useState<DepartmentKnowledgeSpaceSummary[]>([]);
    const [departmentSpacesLoading, setDepartmentSpacesLoading] = useState(false);
    const { user } = useContext(userContext);
    const navigate = useNavigate();
    const canManageWorkbench = canManageWorkbenchConfig(user);
    const isGlobalSuper = isGlobalSuperUser(user);

    const loadDepartmentSpaces = async () => {
        setDepartmentSpacesLoading(true);
        try {
        const res = await getDepartmentKnowledgeSpacesApi({ order_by: "name" });
        if (Array.isArray(res)) {
            setDepartmentSpaces(res);
        }
        } finally {
            setDepartmentSpacesLoading(false);
        }
    };

    useEffect(() => {
        if (user.user_id && !canManageWorkbench) {
            navigate("/build/apps");
        }
    }, [canManageWorkbench, navigate, user.user_id]);

    useEffect(() => {
        if (user.user_id && isGlobalSuper) {
            void loadDepartmentSpaces().catch(showApiError);
        }
    }, [isGlobalSuper, user.user_id]);

    const handleSave = async () => {
        if (!configMeta) return false;
        if ((String((formData.assistantName) ?? '').length > 50) || (String((formData.systemPrompt) ?? '').length > 30000) || (String((formData.userPrompt) ?? '').length > 30000)) return;

        const sensitiveSaved = await sensitivePolicyRef.current?.save();
        if (sensitiveSaved === false) return false;
        return saveKnowledgeConfig();
    };

    return (
        <div className="h-full overflow-y-scroll scrollbar-hide relative border-t">
            <div className="pt-4 relative">
                <CardContent className="p-0 pt-4 relative">
                    <div className="w-full max-h-[calc(100vh-180px-var(--license-banner-h,0px))] overflow-y-scroll scrollbar-hide">
                        <ConfigInheritanceBanner meta={configMeta} />
                        {}
                        <div className="px-5">
                            <FormInput
                                label={t("chatConfig.menuDisplayName")}
                                value={formData.menuDisplayName}
                                error={errors.menuDisplayName}
                                placeholder={t("bench.knowledgeSpace")}
                                onChange={(v) => {
                                    setFormData((prev) => ({ ...prev, menuDisplayName: clampMenuName(v) }));
                                    setErrors((prev) => ({ ...prev, menuDisplayName: "" }));
                                }}
                            />
                        </div>
                        <div className="mb-6">
                            <div className="p-5 bg-gray-50 rounded-lg">
                                <div className="flex items-center mb-2">
                                    <p className="text-lg font-bold flex items-center">
                                        <span>{t("chatConfig.prompts")}</span>
                                    </p>
                                </div>
                                {}
                                <>
                                    <Label className="bisheng-label">{t("chatConfig.aiAssistantName")}</Label>
                                    <div className="mt-3 mb-4">
                                        <Input value={formData.assistantName} placeholder={t("chatConfig.aiAssistantNamePlaceholder")} maxLength={50} onChange={(e) => {
                                                const val = e.target.value;
                                                setFormData((prev) => ({ ...prev, assistantName: val }));
                                            }} showCount />
                                    </div>
                                </>
                                {}
                                <>
                                    <Label className="bisheng-label">{t("chatConfig.sysPrompts")}</Label>
                                    <div className="mt-3">
                                        <Textarea value={formData.systemPrompt} placeholder={t("chatConfig.aiPrompt")} maxLength={30000} onChange={(e) => {
                                                const val = e.target.value;
                                                setFormData((prev) => ({ ...prev, systemPrompt: val }));
                                                setErrors((prev) => ({
                                                    ...prev,
                                                    systemPrompt:
                                                        val.length >= 30000
                                                            ? t("chatConfig.errors.maxCharacters", { count: 30000 })
                                                            : "",
                                                }));
                                            }} textareaClassName={"min-h-48"} showCount />
                                        {errors.systemPrompt && (
                                            <p className="text-xs text-red-500 mt-1">{errors.systemPrompt}</p>
                                        )}
                                    </div>
                                </>
                                {}
                                <>
                                    <Label className="bisheng-label">{t("chatConfig.userPrompts")}</Label>
                                    <div className="mt-3">
                                        <Textarea value={formData.userPrompt} placeholder={t("chatConfig.retrievedAndQuestion")} maxLength={30000} onChange={(e) => {
                                                const val = e.target.value;
                                                setFormData((prev) => ({ ...prev, userPrompt: val }));
                                                setErrors((prev) => ({
                                                    ...prev,
                                                    userPrompt:
                                                        val.length >= 30000
                                                            ? t("chatConfig.errors.maxCharacters", { count: 30000 })
                                                            : "",
                                                }));
                                            }} textareaClassName={"min-h-48"} showCount />
                                        {errors.userPrompt && (
                                            <p className="text-xs text-red-500 mt-1">{errors.userPrompt}</p>
                                        )}
                                    </div>
                                </>
                                {}
                                <>
                                    <Label className="bisheng-label">{t("chatConfig.knowledgeSpaceMaxChars")}</Label>
                                    <div className="flex items-center max-w-40">
                                        <NonNegativeInput
                                            className="mt-3"
                                            value={formData.maxChunkSize ?? ""}
                                            defaultValue={15000}
                                            // max={15000}
                                            onValueChange={(val) => {
                                                setFormData((prev) => ({ ...prev, maxChunkSize: val }));
                                            }}
                                        />
                                        <span className="mt-3 ml-2">{t("chatConfig.character")}</span>
                                    </div>
                                </>
                            </div>

                            <KnowledgeSpaceTagLibrarySection
                                visible={formData.autoTagVisible}
                                onToggle={(checked) => setFormData((prev) => ({ ...prev, autoTagVisible: checked }))}
                            />

                            <KnowledgeSpaceSensitivePolicy ref={sensitivePolicyRef} />

                            {isGlobalSuper && (
                                <div className="p-5 rounded-lg">
                                    <div className="mt-8 border-t border-[#ECECEC] pt-6">
                                        <div className="flex items-center justify-between gap-4">
                                            <div>
                                                <p className="text-lg font-bold">
                                                    {t("bench.departmentKnowledgeSpace")}
                                                </p>
                                                <p className="mt-1 text-sm text-[#86909C]">
                                                    {t("bench.departmentKnowledgeSpaceDesc")}
                                                </p>
                                            </div>
                                            <Button variant="outlined" onClick={() => setManagerOpen(true)} color="default">
                                                {t("bench.departmentKnowledgeSpaceManager")}
                                            </Button>
                                        </div>
                                        <div className="mt-5 rounded-lg border border-[#ECECEC] bg-[#FAFBFC] p-4">
                                            <div className="flex items-center justify-between gap-4">
                                                <div>
                                                    <p className="text-sm font-medium text-[#1D2129]">
                                                        {t("bench.departmentKnowledgeSpaceCreatedList")}
                                                    </p>
                                                    <p className="mt-1 text-sm text-[#86909C]">
                                                        {t("bench.departmentKnowledgeSpaceCreatedListDesc")}
                                                    </p>
                                                </div>
                                                <span className="rounded bg-white px-2.5 py-1 text-xs text-[#4E5969] border border-[#E5E6EB]">
                                                    {departmentSpaces.length}
                                                </span>
                                            </div>
                                            <div className="mt-4 space-y-3">
                                                {departmentSpacesLoading ? (
                                                    <div className="rounded-lg border border-dashed border-[#D9DDE5] bg-white px-4 py-8 text-center text-sm text-[#86909C]">
                                                        {t("loading")}
                                                    </div>
                                                ) : !departmentSpaces.length ? (
                                                    <div className="rounded-lg border border-dashed border-[#D9DDE5] bg-white px-4 py-8 text-center text-sm text-[#86909C]">
                                                        {t("bench.departmentKnowledgeSpaceCreatedEmpty")}
                                                    </div>
                                                ) : (
                                                    departmentSpaces.map((space) => (
                                                        <div
                                                            key={space.id}
                                                            className="rounded-lg border border-[#E5E6EB] bg-white px-4 py-3"
                                                        >
                                                            <div className="flex items-start justify-between gap-4">
                                                                <div className="min-w-0">
                                                                    <div className="flex items-center gap-2">
                                                                        <p className="truncate text-sm font-medium text-[#1D2129]">
                                                                            {space.name}
                                                                        </p>
                                                                        <span className="rounded bg-[#F2F3F5] px-2 py-0.5 text-xs text-[#4E5969]">
                                                                            {space.department_name || "--"}
                                                                        </span>
                                                                    </div>
                                                                    <p className="mt-2 text-xs text-[#86909C]">
                                                                        {t(
                                                                            "bench.departmentKnowledgeSpaceDepartmentLabel",
                                                                        )}
                                                                        ：{space.department_name || "--"}
                                                                    </p>
                                                                </div>
                                                            </div>
                                                        </div>
                                                    ))
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                    <div className="flex justify-end gap-4 absolute bottom-1 right-4">
                        <Preview onBeforView={handleSave} />
                        <Button onClick={handleUiRequest(handleSave)} disabled={(String((formData.assistantName) ?? '').length > 50) || (String((formData.systemPrompt) ?? '').length > 30000) || (String((formData.userPrompt) ?? '').length > 30000)}>{t("save")}</Button>
                    </div>
                </CardContent>
            </div>

            {isGlobalSuper && (
                <>
                    <DepartmentKnowledgeSpaceManagerDialog
                        open={managerOpen}
                        onOpenChange={setManagerOpen}
                        onChanged={handleUiRequest(loadDepartmentSpaces)}
                    />
                </>
            )}
        </div>
    );
}

const useKnowledgeConfig = (scopeVersion = 0) => {
    const { t } = useTranslation();
    const [formData, setFormData] = useState<KnowledgeConfigForm>({
        systemPrompt: "",
        userPrompt: "",
        maxChunkSize: 15000,
        autoTagVisible: false,
        assistantName: "",
        // Blank until configured — the input placeholder shows the default name
        menuDisplayName: "",
    });

    const [errors, setErrors] = useState<{ systemPrompt: string; userPrompt: string; menuDisplayName: string }>({
        systemPrompt: "",
        userPrompt: "",
        menuDisplayName: "",
    });
    const [configMeta, setConfigMeta] = useState<any>(null);

    useEffect(() => {
        setConfigMeta(null);
        getKnowledgeConfigApi().then((res) => {
            const { data: envData, meta } = resolveConfigEnvelope<Record<string, unknown>>(res);
            setConfigMeta(meta);
            const cfg = envData != null && typeof envData === "object" ? envData : null;
            const systemPromptFromRes = cfg?.system_prompt ?? cfg?.systemPrompt;
            const userPromptFromRes = cfg?.user_prompt ?? cfg?.userPrompt;
            const maxChunkSizeFromRes = cfg?.max_chunk_size ?? cfg?.maxTokens;
            const autoTagVisibleFromRes = cfg?.auto_tag_visible ?? cfg?.autoTagVisible;
            const assistantNameFromRes = cfg?.assistant_name ?? cfg?.assistantName;
            const menuDisplayNameFromRes = cfg?.menu_display_name ?? cfg?.menuDisplayName;
            // When backend returns no saved value, seed the textarea with the
            // localized default template so it is editable as a real value.
            const resolvedSystemPrompt = resolveConfigString(systemPromptFromRes, "");
            const resolvedUserPrompt = resolveConfigString(userPromptFromRes, "");
            setFormData((prev) => ({
                ...prev,
                systemPrompt: resolvedSystemPrompt || t("chatConfig.aiPrompt"),
                userPrompt: resolvedUserPrompt || t("chatConfig.retrievedAndQuestion"),
                maxChunkSize: typeof maxChunkSizeFromRes === "number" ? maxChunkSizeFromRes : prev.maxChunkSize,
                autoTagVisible: Boolean(autoTagVisibleFromRes),
                // Keep blank when unset — empty means "use client i18n default".
                assistantName: resolveConfigString(assistantNameFromRes, ""),
                // Blank = unconfigured; the client falls back to its localized default
                menuDisplayName: resolveConfigString(menuDisplayNameFromRes, "").trim(),
            }));
        }).catch(showApiError);
    }, [scopeVersion, t]);


    const { reloadConfig } = useContext(locationContext);

    const handleSave = async () => {
        // Refill blank prompts with the i18n default template so the empty input
        // never reaches the server; reflect the refill in formData for the UI too.
        const finalSystemPrompt = (formData.systemPrompt || "").trim() || t("chatConfig.aiPrompt");
        const finalUserPrompt = (formData.userPrompt || "").trim() || t("chatConfig.retrievedAndQuestion");
        if (finalSystemPrompt !== formData.systemPrompt || finalUserPrompt !== formData.userPrompt) {
            setFormData((prev) => ({
                ...prev,
                systemPrompt: finalSystemPrompt,
                userPrompt: finalUserPrompt,
            }));
        }

        // Length cap is the only remaining check after auto-refill removes the blank case.
        let isValid = true;
        const nextErrors = { systemPrompt: "", userPrompt: "", menuDisplayName: "" };

        if (finalSystemPrompt.length > 30000) {
            nextErrors.systemPrompt = t("chatConfig.errors.maxCharacters", { count: 30000 });
            isValid = false;
        }
        if (finalUserPrompt.length > 30000) {
            nextErrors.userPrompt = t("chatConfig.errors.maxCharacters", { count: 30000 });
            isValid = false;
        }

        setErrors(nextErrors);
        if (!isValid) {
            return false;
        }

        const dataToSave = {
            system_prompt: finalSystemPrompt,
            user_prompt: finalUserPrompt,
            max_chunk_size: formData.maxChunkSize,
            auto_tag_visible: formData.autoTagVisible,
            assistant_name: (formData.assistantName || "").trim(),
            menu_display_name: await toStoredMenuName(formData.menuDisplayName, "bench.knowledgeSpace"),
        };

        const res = await setKnowledgeConfigApi(dataToSave);
        if (res) {
            setConfigMeta({
                inherited_from_root: false,
                has_override: true,
            });
            notification.open({ type: "success", description: String(t("chatConfig.saveSuccess") ?? '') });
            reloadConfig();
        }

        return Boolean(res);
    };

    return {
        formData,
        setFormData,
        errors,
        setErrors,
        configMeta,
        handleSave,
    };
};
