// src/features/chat-config/ChatConfig.tsx
import { Button } from "@/components/bs-ui/button";
import { CardContent } from "@/components/bs-ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Label } from "@/components/bs-ui/label";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { generateUUID } from "@/components/bs-ui/utils";
import { locationContext } from "@/contexts/locationContext";
import { userContext } from "@/contexts/userContext";
import { getWorkstationConfigApi, setWorkstationConfigApi } from "@/controllers/API";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { t } from "i18next";
import { Settings } from "lucide-react";
import { useCallback, useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import WebSearchForm from "../tools/builtInTool/WebSearchFrom";
import { FormInput } from "./FormInput";
import { IconUploadSection } from "./IconUploadSection";
import { Model, ModelManagement } from "./ModelManagement";
import Preview from "./Preview";
import { ToggleSection } from "./ToggleSection";
import { WebSearchConfig } from "./WebSearchConfig";


export interface FormErrors {
    sidebarSlogan: string;
    welcomeMessage: string;
    functionDescription: string;
    inputPlaceholder: string;
    modelNames: string[] | string[][];
    webSearch?: Record<string, string>;
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
    webSearch: {
        enabled: boolean;
        tool: string;
        bing: {
            type: string;
            config: {
                api_key: string;
                base_url: string;
            };
        };
        bocha: {
            type: string;
            config: {
                api_key: string;
            };
        };
        jina: {
            type: string;
            config: {
                api_key: string;
            };
        };
        serp: {
            type: string;
            config: {
                api_key: string;
                engine: string;
            };
        };
        tavily: {
            type: string;
            config: {
                api_key: string;
            };
        };
        prompt: string;
    };
    knowledgeBase: {
        enabled: boolean;
        prompt: string;
    };
    fileUpload: {
        enabled: boolean;
        prompt: string;
    };
}
export default function index({ formData: parentFormData, setFormData: parentSetFormData }) {
    const sidebarSloganRef = useRef<HTMLDivElement>(null);
    const welcomeMessageRef = useRef<HTMLDivElement>(null);
    const functionDescriptionRef = useRef<HTMLDivElement>(null);
    const inputPlaceholderRef = useRef<HTMLDivElement>(null);
    const knowledgeBaseRef = useRef<HTMLDivElement>(null);
    const modelRefs = useRef<(HTMLDivElement | null)[]>([]);
    const webSearchRef = useRef<HTMLDivElement>(null);
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
        knowledgeBaseRef,
        modelRefs,
        webSearchRef,
        systemPromptRef,
        appCenterWelcomeRef,
        appCenterDescriptionRef,
        modelManagementContainerRef, // Pass in the new ref
    }, parentFormData, parentSetFormData);

    useEffect(() => {
        modelRefs.current = modelRefs.current.slice(0, formData.models.length);
    }, [formData.models]);
    const [webSearchDialogOpen, setWebSearchDialogOpen] = useState(false);
    // Redirect non-admin users
    const { user } = useContext(userContext);
    const navigate = useNavigate()
    const [open, setOpen] = useState(false);
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
            models: [...prev.models, { key: generateUUID(4), id: '', name: '', displayName: '' }]
        }));
    };
    const handleOpenWebSearchSettings = () => {
        setWebSearchDialogOpen(true);
    };
    // Add this method in the parent component
    const handleWebSearchChange = useCallback((field: string, value: any) => {
        console.log('Updating field:', field, 'New value:', value);

        // Update local state
        setFormData(prev => ({
            ...prev,
            webSearch: {
                ...prev.webSearch,
                [field]: value
            }
        }));

    }, [setFormData]);
    return (
        <div className=" h-full overflow-y-scroll scrollbar-hide relative border-t">
            <div className="pt-4 relative">
                <CardContent className="pt-4 relative  ">
                    <div className="w-full  max-h-[calc(100vh-180px)] overflow-y-scroll scrollbar-hide">
                        <ToggleSection
                            title={t('chatConfig.workstationEntry')}
                            enabled={formData.menuShow}
                            onToggle={(enabled) => setFormData(prev => ({ ...prev, menuShow: enabled }))}
                        >{null}</ToggleSection>
                        {/* Icon Uploads */}
                        <p className="text-lg font-bold mb-2">{t('chatConfig.iconUpload')}</p>
                        <div className="flex gap-8 mb-6">
                            <IconUploadSection
                                label={t('chatConfig.sidebarIcon')}
                                enabled={formData.sidebarIcon.enabled}
                                image={formData.sidebarIcon.image}
                                onToggle={(enabled) => toggleFeature('sidebarIcon', enabled)}
                                onUpload={(fileUrl, relativePath) => uploadAvator(fileUrl, 'sidebar', relativePath)}
                            />
                            <IconUploadSection
                                label={t('chatConfig.assistantIcon')}
                                enabled={formData.assistantIcon.enabled}
                                image={formData.assistantIcon.image}
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
                        <ToggleSection
                            title={t('chatConfig.webSea')}
                            enabled={formData.webSearch.enabled}
                            onToggle={(enabled) => toggleFeature('webSearch', enabled)}
                            extra={
                                <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={handleOpenWebSearchSettings}
                                    className="p-1 h-auto"
                                >
                                    <Settings className="-ml-2 h-4 w-4" />
                                </Button>
                            }
                        >
                            <WebSearchConfig
                                config={formData.webSearch.prompt}
                                onChange={handleWebSearchChange}
                            />
                        </ToggleSection>
                        <ToggleSection
                            title={t('chatConfig.knowledgeBase')}
                            enabled={formData.knowledgeBase.enabled}
                            onToggle={(enabled) => toggleFeature('knowledgeBase', enabled)}
                        >
                            <FormInput
                                label={<Label className="bisheng-label">{t('chatConfig.knowledgeBasePrompt')}</Label>}
                                isTextarea
                                value={formData.knowledgeBase.prompt}
                                error={errors.kownledgeBase}
                                placeholder=""
                                maxLength={30000}
                                onChange={(val) => setFormData(prev => ({
                                    ...prev,
                                    knowledgeBase: { ...prev.knowledgeBase, prompt: val }
                                }))}
                            />
                        </ToggleSection>

                        <ToggleSection
                            title={t('chatConfig.fileUpload')}
                            enabled={formData.fileUpload.enabled}
                            onToggle={(enabled) => toggleFeature('fileUpload', enabled)}
                        >
                            <FormInput
                                label={<Label className="bisheng-label">{t('chatConfig.fileUploadPrompt')}</Label>}
                                isTextarea
                                value={formData.fileUpload.prompt}
                                error={''}
                                maxLength={9999}
                                onChange={(val) => setFormData(prev => ({
                                    ...prev,
                                    fileUpload: { ...prev.fileUpload, prompt: val }
                                }))}
                            />
                        </ToggleSection>

                    </div>
                    {/* Action Buttons */}
                    <div className="flex justify-end gap-4 absolute bottom-4 right-4">
                        <Preview onBeforView={handleSave} />
                        <Button onClick={handleSave}>{t('save')}</Button>
                    </div>
                </CardContent>
            </div>
            <Dialog open={webSearchDialogOpen} onOpenChange={setWebSearchDialogOpen}>
                <DialogContent className="sm:max-w-[625px] bg-background-login">
                    <DialogHeader>
                        <DialogTitle>{t('chatConfig.webSearchConfig')}</DialogTitle>
                    </DialogHeader>
                    <WebSearchForm isApi={true} />
                </DialogContent>
            </Dialog>
        </div>
    );
}


interface UseChatConfigProps {
    sidebarSloganRef: React.RefObject<HTMLDivElement>;
    welcomeMessageRef: React.RefObject<HTMLDivElement>;
    functionDescriptionRef: React.RefObject<HTMLDivElement>;
    inputPlaceholderRef: React.RefObject<HTMLDivElement>;
    knowledgeBaseRef: React.RefObject<HTMLDivElement>;
    modelRefs: React.MutableRefObject<(HTMLDivElement | null)[]>;
    webSearchRef: React.RefObject<HTMLDivElement>;
    systemPromptRef: React.RefObject<HTMLDivElement>;
    appCenterWelcomeRef: React.RefObject<HTMLDivElement>;
    appCenterDescriptionRef: React.RefObject<HTMLDivElement>;
    modelManagementContainerRef: React.RefObject<HTMLDivElement>; // New
}

const useChatConfig = (refs: UseChatConfigProps, parentFormData, parentSetFormData) => {
    const { t } = useTranslation()

    const [formData, setFormData] = useState<ChatConfigForm>(parentFormData || {
        menuShow: true,
        systemPrompt: t('chatConfig.systemPrompt2'),
        sidebarIcon: { enabled: true, image: '', relative_path: '' },
        assistantIcon: { enabled: true, image: '', relative_path: '' },
        sidebarSlogan: '',
        welcomeMessage: '',
        functionDescription: '',
        inputPlaceholder: '',
        applicationCenterWelcomeMessage: '',
        applicationCenterDescription: '',
        models: [{ key: generateUUID(4), id: null, name: '', displayName: '' }],
        maxTokens: 15000,
        voiceInput: { enabled: false, model: '' },
        webSearch: {
            enabled: true,
            tool: 'bing',
            params: {
                api_key: '',
                base_url: 'https://api.bing.microsoft.com/v7.0/search'
            },
            prompt: t('chatConfig.webSearchPrompt'),
        },
        knowledgeBase: {
            enabled: true,
            prompt: t('chatConfig.internationalization')
        },
        fileUpload: {
            enabled: true,
            prompt: `{file_content}
{question}`,
        },
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
        if (parentFormData && !isDeepEqual(formData, parentFormData)) {
            setFormData(parentFormData);
        }
    }, [parentFormData]);

    useEffect(() => {
        if (parentSetFormData && !isDeepEqual(formData, parentFormData)) {
            parentSetFormData(formData);
        }
    }, [formData, parentFormData]);

    useEffect(() => {
        if (!parentFormData) {
            console.log('parentFormData :>> ', parentFormData);

            getWorkstationConfigApi().then((res) => {
                if (res) {
                    // 确保 systemPrompt 有值
                    const defaultSystemPrompt = t('chatConfig.systemPrompt2')
                    const systemPrompt = res.systemPrompt || defaultSystemPrompt;

                    setFormData((prev) => {
                        return 'menuShow' in res ? res : { ...prev, ...res, systemPrompt }
                    })
                }
            });
        }
    }, [parentFormData]);

    const [errors, setErrors] = useState<FormErrors>({
        sidebarSlogan: '',
        welcomeMessage: '',
        functionDescription: '',
        inputPlaceholder: '',
        kownledgeBase: '',
        model: '',
        modelNames: [],
        webSearch: undefined,
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

        // Validate web search
        if (formData.webSearch.enabled) {
            const webSearchErrors: any = {};
            let hasWebSearchError = false;

            switch (formData.webSearch.tool) {
                case 'bing':
                    if (!formData.webSearch.params.api_key?.trim()) {
                        webSearchErrors.params = { ...webSearchErrors.params, api_key: t('chatConfig.errors.required') };
                        hasWebSearchError = true;
                    }
                    if (!formData.webSearch.params.base_url?.trim()) {
                        webSearchErrors.params = { ...webSearchErrors.params, base_url: t('chatConfig.errors.required') };
                        hasWebSearchError = true;
                    }
                    break;
                case 'bocha':
                case 'jina':
                case 'tavily':
                    if (!formData.webSearch.params.api_key?.trim()) {
                        webSearchErrors.params = { ...webSearchErrors.params, api_key: t('chatConfig.errors.required') };
                        hasWebSearchError = true;
                    }
                    break;
                case 'serp':
                    if (!formData.webSearch.params.api_key?.trim()) {
                        webSearchErrors.params = { ...webSearchErrors.params, api_key: t('chatConfig.errors.required') };
                        hasWebSearchError = true;
                    }
                    if (!formData.webSearch.params.engine?.trim()) {
                        webSearchErrors.params = { ...webSearchErrors.params, engine: t('chatConfig.errors.required') };
                        hasWebSearchError = true;
                    }
                    break;
            }

            if (hasWebSearchError && !firstErrorRef && refs.webSearchRef.current) {
                firstErrorRef = refs.webSearchRef;
            }
            if (Object.keys(webSearchErrors).length) {
                newErrors.webSearch = webSearchErrors;
            }
        }

        newErrors.modelNames = modelNameErrors;
        setErrors(newErrors);

        return { isValid, firstErrorRef };
    };

    const { toast } = useToast()
    const { reloadConfig } = useContext(locationContext)
    const handleSave = async () => {
        const { isValid, firstErrorRef } = validateForm();
        if (!isValid) {
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
            ...formData,
            sidebarSlogan: formData.sidebarSlogan.trim(),
            welcomeMessage: formData.welcomeMessage.trim(),
            functionDescription: formData.functionDescription.trim(),
            inputPlaceholder: formData.inputPlaceholder.trim(),
            applicationCenterWelcomeMessage: formData.applicationCenterWelcomeMessage.trim() || t('chatConfig.appCenterWelcomePlaceholder'),
            applicationCenterDescription: formData.applicationCenterDescription.trim() || t('chatConfig.appCenterDescriptionPlaceholder'),
            maxTokens: formData.maxTokens || 15000,
        };

        console.log('Saving data:', dataToSave);

        captureAndAlertRequestErrorHoc(setWorkstationConfigApi(dataToSave)).then((res) => {
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