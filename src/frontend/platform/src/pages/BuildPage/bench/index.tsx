// src/features/chat-config/ChatConfig.tsx
import { Button } from "@/components/bs-ui/button";
import { CardContent } from "@/components/bs-ui/card";
import { Label } from "@/components/bs-ui/label";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { generateUUID } from "@/components/bs-ui/utils";
import { locationContext } from "@/contexts/locationContext";
import { userContext } from "@/contexts/userContext";
import { getDailyConfigApi, setDailyConfigApi } from "@/controllers/API";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { t } from "i18next";
import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { FormInput } from "./FormInput";
import { IconUploadSection } from "./IconUploadSection";
import { Model, ModelManagement } from "./ModelManagement";
import OrgKbConfig, { OrgKbConfig as OrgKbConfigType } from "./OrgKbConfig";
import Preview from "./Preview";
import { ToggleSection } from "./ToggleSection";
import ToolsConfig, { ToolConfig as ToolConfigType } from "./ToolsConfig";


export interface FormErrors {
    sidebarSlogan: string;
    welcomeMessage: string;
    functionDescription: string;
    tabDisplayName: string;
    inputPlaceholder: string;
    modelNames: string[] | string[][];
    systemPrompt: string;
    model: string;
    kownledgeBase: string;
    applicationCenterWelcomeMessage: string;
    applicationCenterDescription: string;
}

export interface ChatConfigForm {
    menuShow: boolean;
    systemPrompt: string;
    sidebarIcon: {
        enabled: boolean;
        image: string;
        relative_path: string;
    };
    assistantIcon: {
        enabled: boolean;
        image: string;
        relative_path: string;
    };
    sidebarSlogan: string;
    welcomeMessage: string;
    functionDescription: string;
    inputPlaceholder: string;
    applicationCenterWelcomeMessage: string;
    applicationCenterDescription: string;
    models: Model[];
    maxTokens: number;
    voiceInput: {
        enabled: boolean;
        model: string;
    };
    knowledgeBase: {
        enabled: boolean;
        prompt: string;
    };
    fileUpload: {
        enabled: boolean;
        prompt: string;
    };
    /** 日常模式 Tab 名称，对应接口 tabDisplayName */
    tabDisplayName?: string;
    // v2.5 Agent-mode additions
    tools: ToolConfigType[];
    orgKbs: OrgKbConfigType[];
}
export default function index() {
    const sidebarSloganRef = useRef<HTMLDivElement>(null);
    const welcomeMessageRef = useRef<HTMLDivElement>(null);
    const functionDescriptionRef = useRef<HTMLDivElement>(null);
    const inputPlaceholderRef = useRef<HTMLDivElement>(null);
    const tabDisplayNameRef = useRef<HTMLDivElement>(null);
    const knowledgeBaseRef = useRef<HTMLDivElement>(null);
    const modelRefs = useRef<(HTMLDivElement | null)[]>([]);
    const systemPromptRef = useRef<HTMLDivElement>(null);
    const appCenterWelcomeRef = useRef<HTMLDivElement>(null);
    const appCenterDescriptionRef = useRef<HTMLDivElement>(null);
    // New: ref for model management container
    const modelManagementContainerRef = useRef<HTMLDivElement>(null);

    const { t } = useTranslation()
    const {
        formData,
        errors,
        setFormData,
        handleInputChange,
        toggleFeature,
        handleSave
    } = useChatConfig({
        sidebarSloganRef,
        welcomeMessageRef,
        functionDescriptionRef,
        inputPlaceholderRef,
        tabDisplayNameRef,
        knowledgeBaseRef,
        modelRefs,
        systemPromptRef,
        appCenterWelcomeRef,
        appCenterDescriptionRef,
        modelManagementContainerRef, // Pass in the new ref
    });

    useEffect(() => {
        modelRefs.current = modelRefs.current.slice(0, formData.models.length);
    }, [formData.models]);
    // Redirect non-admin users
    const { user } = useContext(userContext);
    const navigate = useNavigate()
    useEffect(() => {
        if (user.user_id && user.role !== 'admin') {
            navigate('/build/apps')
        }
    }, [user])

    const uploadAvator = (fileUrl: string, type: 'sidebar' | 'assistant', relativePath?: string) => {
        setFormData(prev => ({
            ...prev,
            [`${type}Icon`]: { ...prev[`${type}Icon`], image: fileUrl, relative_path: relativePath }
        }));
    };
    const handleModelChange = (index: number, id: string) => {
        const newModels = [...formData.models];
        newModels[index].id = id;
        setFormData(prev => ({ ...prev, models: newModels }));
    };

    const handleModelNameChange = (index: number, name: string) => {
        const newModels = [...formData.models];
        newModels[index].displayName = name;
        setFormData(prev => ({ ...prev, models: newModels }));
    };

    const addModel = () => {
        setFormData(prev => ({
            ...prev,
            models: [...prev.models, { key: generateUUID(4), id: '', name: '', displayName: '', visual: false }]
        }));
    };
    const handleVisualToggle = (index: number, enabled: boolean) => {
        const newModels = [...formData.models];
        newModels[index] = {
            ...newModels[index],
            visual: enabled
        };
        setFormData(prev => ({ ...prev, models: newModels }));
    };
    return (
        <div className=" h-full overflow-y-scroll scrollbar-hide relative border-t">
            <div className="pt-4 relative">
                <CardContent className="pt-4 relative  ">
                    <div className="w-full  max-h-[calc(100vh-180px)] overflow-y-scroll scrollbar-hide">
                        {/* <ToggleSection
                            title={t('chatConfig.workstationEntry')}
                            enabled={formData.menuShow}
                            onToggle={(enabled) => setFormData(prev => ({ ...prev, menuShow: enabled }))}
                        >{null}</ToggleSection> */}
                        {/* Icon Uploads */}
                        <p className="text-lg font-bold mb-2">{t('chatConfig.iconUpload')}</p>
                        <div className="flex gap-8 mb-6">
                            <IconUploadSection
                                label={t('chatConfig.sidebarIcon')}
                                enabled={formData.sidebarIcon.enabled ?? true}
                                image={formData.sidebarIcon.image ?? ''}
                                onToggle={(enabled) => toggleFeature('sidebarIcon', enabled)}
                                onUpload={(fileUrl, relativePath) => uploadAvator(fileUrl, 'sidebar', relativePath)}
                            />
                            <IconUploadSection
                                label={t('chatConfig.assistantIcon')}
                                enabled={formData.assistantIcon.enabled ?? true}
                                image={formData.assistantIcon.image ?? ''}
                                onToggle={(enabled) => toggleFeature('assistantIcon', enabled)}
                                onUpload={(fileUrl, relativePath) => uploadAvator(fileUrl, 'assistant', relativePath)}
                            />
                        </div>
                        <div ref={sidebarSloganRef}>
                            <FormInput
                                label={<Label className="bisheng-label">{t('chatConfig.sidebarSlogan')}</Label>}
                                value={formData.sidebarSlogan}
                                error={errors.sidebarSlogan}
                                placeholder=""
                                maxLength={15}
                                onChange={(v) => handleInputChange('sidebarSlogan', v, 15)}
                            />
                        </div>

                        <div ref={welcomeMessageRef}>
                            <FormInput
                                label={t('chatConfig.welcomeMessage')}
                                value={formData.welcomeMessage}
                                error={errors.welcomeMessage}
                                placeholder={t('chatConfig.welcomeMessagePlaceholder')}
                                maxLength={1000}
                                onChange={(v) => handleInputChange('welcomeMessage', v, 1000)}
                            />
                        </div>
                        <div ref={functionDescriptionRef}>
                            <FormInput
                                label={t('chatConfig.functionDescription')}
                                value={formData.functionDescription}
                                error={errors.functionDescription}
                                placeholder={t('chatConfig.functionDescriptionPlaceholder')}
                                maxLength={1000}
                                onChange={(v) => handleInputChange('functionDescription', v, 1000)}
                            />
                        </div>
                        <div ref={tabDisplayNameRef}>
                            <FormInput
                                label={t('chatConfig.dailyModeName')}
                                value={formData.tabDisplayName}
                                error={errors.tabDisplayName}
                                placeholder={t('chatConfig.inputPlaceholderPlaceholder')}
                                maxLength={20}
                                onChange={(v) => handleInputChange('tabDisplayName', v, 20)}
                            />
                        </div>
                        <div ref={inputPlaceholderRef}>
                            <FormInput
                                label={t('chatConfig.inputPlaceholder')}
                                value={formData.inputPlaceholder}
                                error={errors.inputPlaceholder}
                                placeholder={t('chatConfig.inputPlaceholderPlaceholder')}
                                maxLength={1000}
                                onChange={(v) => handleInputChange('inputPlaceholder', v, 1000)}
                            />
                        </div>
                        <div ref={appCenterWelcomeRef}>
                            <FormInput
                                label={t('chatConfig.appCenterWelcome')}
                                value={formData.applicationCenterWelcomeMessage}
                                error={errors.applicationCenterWelcomeMessage}
                                placeholder={t('chatConfig.appCenterWelcomePlaceholder')}
                                onChange={(v) => handleInputChange('applicationCenterWelcomeMessage', v, 1000)}
                            />
                        </div>

                        {/* New application center description input */}
                        <div ref={appCenterDescriptionRef}>
                            <FormInput
                                label={t('chatConfig.appCenterDescription')}
                                value={formData.applicationCenterDescription}
                                error={errors.applicationCenterDescription}
                                placeholder={t('chatConfig.appCenterDescriptionPlaceholder')}
                                onChange={(v) => handleInputChange('applicationCenterDescription', v, 1000)}
                            />
                        </div>

                        {/* Model Management */}
                        {/* Bind model management container ref */}
                        <div className="mb-6" ref={modelManagementContainerRef}>
                            <p className="text-lg font-bold mb-2">{t('chatConfig.modelManagement')}</p>
                            <div className="mb-6">
                                <ModelManagement
                                    ref={modelRefs}
                                    models={formData.models}
                                    errors={errors.modelNames}
                                    error={errors.model}
                                    onAdd={addModel}
                                    onRemove={(index) => {
                                        const newModels = [...formData.models];
                                        newModels.splice(index, 1);
                                        setFormData(prev => ({ ...prev, models: newModels }));
                                    }}
                                    onModelChange={handleModelChange}
                                    onNameChange={handleModelNameChange}
                                    onVisualToggle={handleVisualToggle}
                                />
                            </div>
                            <FormInput
                                label={<Label className="bisheng-label block pt-2">{t('chatConfig.maxTokens')}</Label>}
                                type="number"
                                value={formData.maxTokens}
                                error={''}
                                placeholder={t('chatConfig.maxTokensPlaceholder')}
                                maxLength={1000}
                                onChange={(v) => handleInputChange('maxTokens', v, 100)}
                            />
                            <div ref={systemPromptRef}>
                                <FormInput
                                    label={<Label className="bisheng-label">{t('chatConfig.systemPrompt')}</Label>}
                                    isTextarea
                                    value={formData.systemPrompt}
                                    error={errors.systemPrompt}
                                    placeholder={`${t('chatConfig.systemPromptPlaceholder')}`}
                                    maxLength={30000}
                                    onChange={(val) => handleInputChange('systemPrompt', val, 30000)}
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
                            onChange={(tools) => setFormData(prev => ({ ...prev, tools }))}
                        />

                        <ToggleSection
                            title={t('chatConfig.knowledgeBase')}
                            enabled={formData.knowledgeBase.enabled}
                            onToggle={(enabled) => toggleFeature('knowledgeBase', enabled)}
                        >
                            <OrgKbConfig
                                orgKbs={formData.orgKbs}
                                onChange={(orgKbs) => setFormData(prev => ({ ...prev, orgKbs }))}
                            />
                        </ToggleSection>

                        <ToggleSection
                            title={t('chatConfig.fileUpload')}
                            enabled={formData.fileUpload.enabled}
                            onToggle={(enabled) => toggleFeature('fileUpload', enabled)}
                        >
                            {null}
                        </ToggleSection>

                    </div>
                    {/* Action Buttons */}
                    <div className="flex justify-end gap-4 absolute bottom-1 right-4">
                        <Preview onBeforView={handleSave} />
                        <Button onClick={handleSave}>{t('save')}</Button>
                    </div>
                </CardContent>
            </div>
        </div>
    );
}


interface UseChatConfigProps {
    sidebarSloganRef: React.RefObject<HTMLDivElement>;
    welcomeMessageRef: React.RefObject<HTMLDivElement>;
    functionDescriptionRef: React.RefObject<HTMLDivElement>;
    inputPlaceholderRef: React.RefObject<HTMLDivElement>;
    tabDisplayNameRef: React.RefObject<HTMLDivElement>;
    knowledgeBaseRef: React.RefObject<HTMLDivElement>;
    modelRefs: React.MutableRefObject<(HTMLDivElement | null)[]>;
    systemPromptRef: React.RefObject<HTMLDivElement>;
    appCenterWelcomeRef: React.RefObject<HTMLDivElement>;
    appCenterDescriptionRef: React.RefObject<HTMLDivElement>;
    modelManagementContainerRef: React.RefObject<HTMLDivElement>; // New
}

const useChatConfig = (refs: UseChatConfigProps) => {
    const { t } = useTranslation()

    const [formData, setFormData] = useState<ChatConfigForm>({
        // menuShow: true,
        systemPrompt: t('chatConfig.systemPrompt2'),
        sidebarIcon: { enabled: true, image: '', relative_path: '' },
        assistantIcon: { enabled: true, image: '', relative_path: '' },
        sidebarSlogan: '',
        welcomeMessage: '',
        functionDescription: '',
        inputPlaceholder: '',
        applicationCenterWelcomeMessage: '',
        applicationCenterDescription: '',
        models: [{ key: generateUUID(4), id: null, name: '', displayName: '', visual: false }],
        maxTokens: 15000,
        voiceInput: { enabled: false, model: '' },
        knowledgeBase: {
            enabled: true,
            prompt: t('chatConfig.internationalization')
        },
        fileUpload: {
            enabled: true,
            prompt: `{file_content}
{question}`,
        },
        // 默认展示名称：接口为空时展示默认文案
        tabDisplayName: t('dailyFullName'),
        tools: [],
        orgKbs: [],
    });

    // Simple deep comparison to avoid circular refresh caused by parent-child mutual setting
    const isDeepEqual = (a: any, b: any) => {
        try {
            return JSON.stringify(a) === JSON.stringify(b);
        } catch {
            return a === b;
        }
    };



    useEffect(() => {
        getDailyConfigApi().then((res) => {
            const cfg = (res && (res as any).data) || res;
            if (cfg) {
                const defaultSystemPrompt = t('chatConfig.systemPrompt2');
                setFormData((prev) => {
                    const mergeObj = (a: any, b: any) =>
                        b != null && typeof b === 'object' ? { ...a, ...b } : a;

                    return {
                        ...prev,
                        // 基本文案配置
                        sidebarSlogan: cfg.sidebarSlogan ?? prev.sidebarSlogan,
                        welcomeMessage: cfg.welcomeMessage ?? prev.welcomeMessage,
                        functionDescription: cfg.functionDescription ?? prev.functionDescription,
                        inputPlaceholder: cfg.inputPlaceholder ?? prev.inputPlaceholder,
                        applicationCenterWelcomeMessage:
                            cfg.applicationCenterWelcomeMessage ?? prev.applicationCenterWelcomeMessage,
                        applicationCenterDescription:
                            cfg.applicationCenterDescription ?? prev.applicationCenterDescription,
                        // 模型与 token
                        models:
                            Array.isArray(cfg.models) && cfg.models.length > 0
                                ? cfg.models
                                : prev.models,
                        maxTokens:
                            typeof cfg.maxTokens === 'number' ? cfg.maxTokens : prev.maxTokens,
                        // 系统提示词
                        systemPrompt: cfg.systemPrompt || defaultSystemPrompt,
                        // 图标与其他嵌套配置合并
                        sidebarIcon: mergeObj(prev.sidebarIcon, cfg.sidebarIcon),
                        assistantIcon: mergeObj(prev.assistantIcon, cfg.assistantIcon),
                        knowledgeBase: mergeObj(prev.knowledgeBase, cfg.knowledgeBase),
                        fileUpload: mergeObj(prev.fileUpload, cfg.fileUpload),
                        tabDisplayName: (() => {
                            // Treat empty string / whitespace as "API empty" and don't override defaults.
                            const raw = (cfg as any).tabDisplayName ?? (cfg as any).tab_display_name;
                            if (typeof raw !== 'string') return prev.tabDisplayName;
                            const trimmed = raw.trim();
                            return trimmed ? trimmed : prev.tabDisplayName;
                        })(),
                        // v2.5 Agent-mode fields (parse_config auto-migrates legacy webSearch → tools).
                        tools: Array.isArray(cfg.tools) ? cfg.tools : prev.tools,
                        orgKbs: Array.isArray(cfg.orgKbs) ? cfg.orgKbs : prev.orgKbs,
                    };
                });
            }
        });
    }, [t]);

    const [errors, setErrors] = useState<FormErrors>({
        sidebarSlogan: '',
        welcomeMessage: '',
        functionDescription: '',
        tabDisplayName: '',
        inputPlaceholder: '',
        kownledgeBase: '',
        model: '',
        modelNames: [],
        systemPrompt: '',
        applicationCenterWelcomeMessage: '',
        applicationCenterDescription: '',
    });

    const handleInputChange = (field: keyof ChatConfigForm, value: string, maxLength: number) => {
        setFormData(prev => ({ ...prev, [field]: value }));

        if (value.length >= maxLength) {
            setErrors(prev => ({ ...prev, [field]: t('chatConfig.errors.maxCharacters', { count: maxLength }) }));
        } else {
            setErrors(prev => ({ ...prev, [field]: '' }));
        }
    };

    const toggleFeature = (feature: keyof ChatConfigForm, enabled: boolean) => {
        setFormData(prev => ({
            ...prev,
            [feature]: { ...prev[feature], enabled }
        }));
    };

    const validateForm = (): { isValid: boolean, firstErrorRef: React.RefObject<HTMLDivElement> | null } => {
        let isValid = true;
        let firstErrorRef: React.RefObject<HTMLDivElement> | null = null;
        const newErrors: FormErrors = {
            sidebarSlogan: '',
            welcomeMessage: '',
            functionDescription: '',
            tabDisplayName: '',
            inputPlaceholder: '',
            kownledgeBase: '',
            model: '',
            modelNames: [],
            applicationCenterWelcomeMessage: '',
            applicationCenterDescription: '',
            systemPrompt: '',
        };

        if (formData.sidebarSlogan.length > 15) {
            newErrors.sidebarSlogan = t('chatConfig.errors.maxCharacters', { count: 15 });
            if (!firstErrorRef) firstErrorRef = refs.sidebarSloganRef;
            isValid = false;
        }

        const tabName = (formData.tabDisplayName || '').trim();
        if (!tabName) {
            newErrors.tabDisplayName = t('chatConfig.errors.dailyModeNameRequired');
            if (!firstErrorRef) firstErrorRef = refs.tabDisplayNameRef;
            isValid = false;
        } else if (tabName.length > 20) {
            newErrors.tabDisplayName = t('chatConfig.errors.maxCharacters', { count: 20 });
            if (!firstErrorRef) firstErrorRef = refs.tabDisplayNameRef;
            isValid = false;
        }

        // Validate welcome message
        if (formData.welcomeMessage.length > 1000) {
            newErrors.welcomeMessage = t('chatConfig.errors.maxCharacters', { count: 1000 });
            if (!firstErrorRef) firstErrorRef = refs.welcomeMessageRef;
            isValid = false;
        }

        // Validate function description
        if (formData.functionDescription.length > 1000) {
            newErrors.functionDescription = t('chatConfig.errors.maxCharacters', { count: 1000 });
            if (!firstErrorRef) firstErrorRef = refs.functionDescriptionRef;
            isValid = false;
        }

        // Validate input placeholder
        if (formData.inputPlaceholder.length > 1000) {
            newErrors.inputPlaceholder = t('chatConfig.errors.maxCharacters', { count: 1000 });
            if (!firstErrorRef) firstErrorRef = refs.inputPlaceholderRef;
            isValid = false;
        }

        if (formData.knowledgeBase.prompt.length > 30000) {
            newErrors.kownledgeBase = t('chatConfig.errors.maxCharacters', { count: 30000 });
            if (!firstErrorRef) firstErrorRef = refs.knowledgeBaseRef;
            isValid = false;
        }

        if (formData.systemPrompt?.length > 30000) {
            newErrors.systemPrompt = t('chatConfig.errors.maxCharacters', { count: 30000 });
            if (!firstErrorRef) firstErrorRef = refs.systemPromptRef;
            isValid = false;
        }
        if (formData.applicationCenterWelcomeMessage.length > 1000) {
            newErrors.applicationCenterWelcomeMessage = t('chatConfig.errors.maxCharacters', { count: 1000 });
            if (!firstErrorRef) firstErrorRef = refs.appCenterWelcomeRef;
            isValid = false;
        }

        // Validate application center description
        if (formData.applicationCenterDescription.length > 1000) {
            newErrors.applicationCenterDescription = t('chatConfig.errors.maxCharacters', { count: 1000 });
            if (!firstErrorRef) firstErrorRef = refs.appCenterDescriptionRef;
            isValid = false;
        }
        // Validate models
        if (formData.models.length === 0) {
            newErrors.model = t('chatConfig.errors.atLeastOneModel');
            if (!firstErrorRef) {
                // Modified: Use model management container ref as priority scroll target
                firstErrorRef = refs.modelManagementContainerRef.current
                    ? { current: refs.modelManagementContainerRef.current }
                    : refs.sidebarSloganRef; // Keep default fallback
            }
            isValid = false;
        }

        const modelNameErrors: string[][] = [];
        formData.models.forEach((model, index) => {
            const displayName = model.displayName.trim();
            let error = [];

            if (!displayName) {
                error = ['', t('chatConfig.errors.modelNameRequired')];
                if (!firstErrorRef && refs.modelRefs.current[index]) {
                    firstErrorRef = { current: refs.modelRefs.current[index] };
                }
            } else if (!model.id) {
                error = [t('chatConfig.errors.modelRequired'), ''];
                if (!firstErrorRef && refs.modelRefs.current[index]) {
                    firstErrorRef = { current: refs.modelRefs.current[index] };
                }
            } else if (displayName.length > 30) {
                error = ['', t('chatConfig.errors.maxCharacters', { count: 30 })];
                if (!firstErrorRef && refs.modelRefs.current[index]) {
                    firstErrorRef = { current: refs.modelRefs.current[index] };
                }
            } else {
                formData.models.some((m, i) => {
                    if (i !== index) {
                        error = ['', ''];
                        if (m.id === model.id) {
                            error[0] = t('chatConfig.errors.modelDuplicate')
                        }
                        if (m.displayName.trim().toLowerCase() === displayName.toLowerCase()) {
                            error[1] = t('chatConfig.errors.modelNameDuplicate')
                        }
                        if (error[0] || error[1]) {
                            if (!firstErrorRef && refs.modelRefs.current[index]) {
                                firstErrorRef = { current: refs.modelRefs.current[index] };
                            }
                            return true;
                        }
                    }
                });
            }

            if (error[0] || error[1]) {
                modelNameErrors[model.key] = error;
                isValid = false;
            }
        });

        newErrors.modelNames = modelNameErrors;
        setErrors(newErrors);

        return { isValid, firstErrorRef };
    };

    const { toast } = useToast()
    const { reloadConfig } = useContext(locationContext)
    const handleSave = async () => {
        const { isValid, firstErrorRef } = validateForm();
        if (!isValid) {
            const tabName = (formData.tabDisplayName || '').trim();
            if (!tabName) {
                toast({
                    variant: 'error',
                    description: '日常模式展示名称不能为空',
                });
            }
            if (firstErrorRef?.current) {
                firstErrorRef.current.scrollIntoView({
                    behavior: 'smooth',
                    block: 'end',
                    inline: 'nearest'
                });

                setTimeout(() => {
                    const input = firstErrorRef.current?.querySelector('input, textarea, [role="combobox"]');
                    if (input) input.focus();
                }, 300);
            }
            return false;
        }

        const dataToSave = {
            sidebarIcon: formData.sidebarIcon,
            assistantIcon: formData.assistantIcon,
            sidebarSlogan: formData.sidebarSlogan.trim(),
            welcomeMessage: formData.welcomeMessage.trim(),
            functionDescription: formData.functionDescription.trim(),
            inputPlaceholder: formData.inputPlaceholder.trim(),
            applicationCenterWelcomeMessage: formData.applicationCenterWelcomeMessage.trim() || t('chatConfig.appCenterWelcomePlaceholder'),
            applicationCenterDescription: formData.applicationCenterDescription.trim() || t('chatConfig.appCenterDescriptionPlaceholder'),
            models: formData.models,
            maxTokens: formData.maxTokens || 15000,
            systemPrompt: formData.systemPrompt,
            knowledgeBase: formData.knowledgeBase,
            fileUpload: formData.fileUpload,
            tabDisplayName: formData.tabDisplayName ?? '',
            // v2.5 Agent-mode fields
            tools: formData.tools,
            orgKbs: formData.orgKbs,
        };

        console.log('Saving data:', dataToSave);

        captureAndAlertRequestErrorHoc(setDailyConfigApi(dataToSave)).then((res) => {
            if (res) {
                toast({
                    variant: 'success',
                    description: t('chatConfig.saveSuccess'),
                })
                reloadConfig()
            }
        })

        return true
    };

    return {
        formData,
        errors,
        setFormData,
        setErrors,
        handleInputChange,
        toggleFeature,
        handleSave
    };
};