import { Button } from '@bisheng/ui';

import { CardContent } from "@/components/bs-ui/card";
import { Label } from "@/components/bs-ui/label";
import { SkillManagement } from "@/components/LinSight/skill/SkillManagement";
import { locationContext } from "@/contexts/locationContext";
import { userContext } from "@/contexts/userContext";
import { canManageWorkbenchConfig } from "@/pages/ModelPage/manage/permissions";
import { useContext, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import ConfigInheritanceBanner from "./ConfigInheritanceBanner";
import { FormInput } from "./FormInput";
import { IconUploadSection } from "./IconUploadSection";
import { useChatConfig } from "./index";
import { handleUiRequest } from "@/controllers/request";
import OrgKbConfig from "./OrgKbConfig";
import Preview from "./Preview";
import RecommendedAppsConfig from "./RecommendedAppsConfig";
import { ToggleSection } from "./ToggleSection";
import ToolsConfig from "./ToolsConfig";
import { WorkbenchSensitivePolicy, type WorkbenchSensitivePolicyHandle } from "./WorkbenchSensitivePolicy";
interface DailyChatConfigProps {
    scopeVersion?: number;
}
export function DailyChatConfig({ scopeVersion = 0 }: DailyChatConfigProps) {
    const homeMenuDisplayNameRef = useRef<HTMLDivElement>(null);
    const welcomeMessageRef = useRef<HTMLDivElement>(null);
    const functionDescriptionRef = useRef<HTMLDivElement>(null);
    const inputPlaceholderRef = useRef<HTMLDivElement>(null);
    const taskModeNameRef = useRef<HTMLDivElement>(null);
    const knowledgeBaseRef = useRef<HTMLDivElement>(null);
    const modelRefs = useRef<(HTMLDivElement | null)[]>([]);
    const systemPromptRef = useRef<HTMLDivElement>(null);
    // New: ref for model management container
    const modelManagementContainerRef = useRef<HTMLDivElement>(null);

    const { t } = useTranslation();
    const { appConfig } = useContext(locationContext);
    const sensitivePolicyRef = useRef<WorkbenchSensitivePolicyHandle>(null);
    const {
        formData,
        errors,
        configMeta,
        setFormData,
        handleInputChange,
        handleMenuNameChange,
        handleLinsightChange,
        toggleFeature,
        handleSave,
    } = useChatConfig(
        {
            homeMenuDisplayNameRef,
            welcomeMessageRef,
            functionDescriptionRef,
            inputPlaceholderRef,
            taskModeNameRef,
            knowledgeBaseRef,
            modelRefs,
            systemPromptRef,
            modelManagementContainerRef, // Pass in the new ref
        },
        scopeVersion,
        async () => {
            if (!appConfig?.isPro) return true;
            return (await sensitivePolicyRef.current?.save()) !== false;
        },
    );

    useEffect(() => {
        modelRefs.current = modelRefs.current.slice(0, formData.models.length);
    }, [formData.models]);
    // Redirect users who cannot manage workstation settings
    const { user } = useContext(userContext);
    const navigate = useNavigate();
    useEffect(() => {
        if (user.user_id && !canManageWorkbenchConfig(user)) {
            navigate("/build/apps");
        }
    }, [user, navigate]);

    const uploadAvator = (fileUrl: string, type: "sidebar" | "assistant", relativePath?: string) => {
        setFormData((prev) => ({
            ...prev,
            [`${type}Icon`]: { ...prev[`${type}Icon`], image: fileUrl, relative_path: relativePath },
        }));
    };
    return (
        <div className="daily-page h-full overflow-y-scroll scrollbar-hide relative border-t">
            <div className="pt-4 relative">
                <CardContent className="pt-4 pb-0 relative  ">
                    <div className="w-full  max-h-[calc(100vh-180px-var(--license-banner-h,0px))] overflow-y-scroll scrollbar-hide pb-10">
                        <ConfigInheritanceBanner meta={configMeta} />
                        {/* <ToggleSection
                            title={t('chatConfig.workstationEntry')}
                            enabled={formData.menuShow}
                            onToggle={(enabled) => setFormData(prev => ({ ...prev, menuShow: enabled }))}
                        >{null}</ToggleSection> */}
                        {/* Sidebar entry name — optional (blank = localized default), capped at MENU_NAME_MAX_WIDTH */}
                        <div ref={homeMenuDisplayNameRef}>
                            <FormInput
                                label={t("chatConfig.menuDisplayName")}
                                value={formData.homeMenuDisplayName}
                                error={errors.homeMenuDisplayName}
                                placeholder={t("bench.home")}
                                onChange={(v) => handleMenuNameChange("homeMenuDisplayName", v)}
                            />
                        </div>
                        {/* Icon Uploads */}
                        <p className="text-lg font-bold mb-2">{t("chatConfig.iconUpload")}</p>
                        <div className="flex gap-8 mb-6">
                            <IconUploadSection
                                label={t("chatConfig.sidebarIcon")}
                                enabled={formData.sidebarIcon.enabled ?? true}
                                image={formData.sidebarIcon.image ?? ""}
                                onToggle={(enabled) => toggleFeature("sidebarIcon", enabled)}
                                onUpload={(fileUrl, relativePath) => uploadAvator(fileUrl, "sidebar", relativePath)}
                            />
                            <IconUploadSection
                                label={t("chatConfig.assistantIcon")}
                                enabled={formData.assistantIcon.enabled ?? true}
                                image={formData.assistantIcon.image ?? ""}
                                onToggle={(enabled) => toggleFeature("assistantIcon", enabled)}
                                onUpload={(fileUrl, relativePath) => uploadAvator(fileUrl, "assistant", relativePath)}
                            />
                        </div>
                        <div ref={welcomeMessageRef}>
                            <FormInput
                                label={t("chatConfig.welcomeMessage")}
                                value={formData.welcomeMessage}
                                error={errors.welcomeMessage}
                                placeholder={t("chatConfig.welcomeMessagePlaceholder")}
                                maxLength={1000}
                                onChange={(v) => handleInputChange("welcomeMessage", v, 1000)}
                            />
                        </div>
                        <div ref={functionDescriptionRef}>
                            <FormInput
                                label={t("chatConfig.functionDescription")}
                                value={formData.functionDescription}
                                error={errors.functionDescription}
                                placeholder={t("chatConfig.functionDescriptionPlaceholder")}
                                maxLength={1000}
                                onChange={(v) => handleInputChange("functionDescription", v, 1000)}
                            />
                        </div>
                        <div ref={inputPlaceholderRef}>
                            <FormInput
                                label={t("chatConfig.inputPlaceholder")}
                                value={formData.inputPlaceholder}
                                error={errors.inputPlaceholder}
                                placeholder={t("chatConfig.inputPlaceholderPlaceholder")}
                                maxLength={1000}
                                onChange={(v) => handleInputChange("inputPlaceholder", v, 1000)}
                            />
                        </div>
                        {/* F035 (PRD §4.8): task-mode fields merged from the legacy 灵思 tab */}
                        <div ref={taskModeNameRef}>
                            <FormInput
                                label={t("chatConfig.taskModeName")}
                                value={formData.linsightConfig.tab_display_name}
                                error={errors.taskModeName}
                                placeholder={t("chatConfig.inputPlaceholderPlaceholder")}
                                maxLength={20}
                                onChange={(v) => handleLinsightChange("tab_display_name", v)}
                            />
                        </div>
                        <FormInput
                            label={t("chatConfig.taskModeInputPlaceholder")}
                            value={formData.linsightConfig.input_placeholder}
                            error={""}
                            placeholder={t("chatConfig.inputPlaceholderPlaceholder")}
                            maxLength={100}
                            onChange={(v) => handleLinsightChange("input_placeholder", v)}
                        />
                        {/* F035: 应用中心欢迎语/描述 moved to the 应用 tab (AppCenter.tsx);
                            their values still round-trip through dataToSave below. */}
                        <div className="mb-6" ref={modelManagementContainerRef}>
                            <FormInput
                                label={<Label className="bisheng-label block pt-2">{t("chatConfig.maxTokens")}</Label>}
                                type="number"
                                value={formData.maxTokens}
                                error={""}
                                placeholder={t("chatConfig.maxTokensPlaceholder")}
                                maxLength={1000}
                                onChange={(v) => handleInputChange("maxTokens", v, 100)}
                            />
                            <div ref={systemPromptRef}>
                                <FormInput
                                    label={<Label className="bisheng-label">{t("chatConfig.systemPrompt")}</Label>}
                                    isTextarea
                                    value={formData.systemPrompt}
                                    error={errors.systemPrompt}
                                    placeholder={`${t("chatConfig.systemPromptPlaceholder")}`}
                                    maxLength={30000}
                                    onChange={(val) => handleInputChange("systemPrompt", val, 30000)}
                                />
                            </div>
                        </div>

                        {/* Toggle Sections */}
                        {/* <ToggleSection
                            title="Voice Input"
                            enabled={formData.voiceInput.enabled}
                            onToggle={(enabled) => toggleFeature('voiceInput', enabled)}
                        >
                            <Label className="bisheng-label">Voice Input Model Selection</Label>
                            <div className="mt-3">
                                <Select value={""} onValueChange={(val) => { }}>
                                    <SelectTrigger>
                                        <SelectValue placeholder="" />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectGroup>
                                            <SelectItem value="1">{t('model.yes')}</SelectItem>
                                            <SelectItem value="0">{t('model.no')}</SelectItem>
                                        </SelectGroup>
                                    </SelectContent>
                                </Select>
                            </div>
                        </ToggleSection> */}
                        {/* v2.5 Agent-mode: available tools configuration (replaces 联网搜索 toggle) */}
                        <ToolsConfig
                            tools={formData.tools}
                            onChange={(tools) => setFormData((prev) => ({ ...prev, tools }))}
                        />

                        <ToggleSection
                            title={t("chatConfig.knowledgeBase")}
                            enabled={formData.knowledgeBase.enabled}
                            onToggle={(enabled) => toggleFeature("knowledgeBase", enabled)}
                        >
                            <OrgKbConfig
                                orgKbs={formData.orgKbs}
                                onChange={(orgKbs) => setFormData((prev) => ({ ...prev, orgKbs }))}
                            />
                        </ToggleSection>

                        <ToggleSection
                            title={t("chatConfig.fileUpload")}
                            enabled={formData.fileUpload.enabled}
                            onToggle={(enabled) => toggleFeature("fileUpload", enabled)}
                        >
                            {null}
                        </ToggleSection>

                        {/* F035 (PRD §4.5): skill management replaces the legacy SOP manual library.
                            The header toggle (default off) gates the client 添加技能 entry. */}
                        <SkillManagement
                            scopeVersion={scopeVersion}
                            entryEnabled={formData.skillEntry.enabled}
                            onEntryToggle={(enabled) => toggleFeature("skillEntry", enabled)}
                        />

                        {/* Recommended Apps */}
                        <RecommendedAppsConfig
                            selectedAppIds={formData.recommendedApps || []}
                            onSelectedAppsChange={(ids) => setFormData((prev) => ({ ...prev, recommendedApps: ids }))}
                        />
                        {appConfig?.isPro ? <WorkbenchSensitivePolicy ref={sensitivePolicyRef} /> : null}
                    </div>
                    {/* Action Buttons */}
                    <div className="flex justify-end gap-4 absolute bottom-1 right-4">
                        <Preview onBeforView={handleSave} />
                        <Button onClick={handleUiRequest(handleSave)}>{t("save")}</Button>
                    </div>
                </CardContent>
            </div>
        </div>
    );
}
