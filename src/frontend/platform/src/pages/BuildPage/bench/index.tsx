// src/features/chat-config/ChatConfig.tsx
import { Button } from "@/components/bs-ui/button";
import { Card, CardContent } from "@/components/bs-ui/card";
import { Label } from "@/components/bs-ui/label";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { generateUUID } from "@/components/bs-ui/utils";
import { locationContext } from "@/contexts/locationContext";
import { userContext } from "@/contexts/userContext";
import { getWorkstationConfigApi, setWorkstationConfigApi } from "@/controllers/API";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useCallback, useContext, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { FormInput } from "./FormInput";
import { IconUploadSection } from "./IconUploadSection";
import { Model, ModelManagement } from "./ModelManagement";
import Preview from "./Preview";
import { ToggleSection } from "./ToggleSection";
import { WebSearchConfig } from "./WebSearchConfig";
import { Settings } from "lucide-react";
import { useWebSearchStore } from "../tools/webSearchStore";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import WebSearchForm from "../tools/builtInTool/WebSearchFrom";
import { getAssistantToolsApi, updateAssistantToolApi } from "@/controllers/API/assistant";
import { useTranslation } from "react-i18next";
import { t } from "i18next";


export interface FormErrors {
    sidebarSlogan: string;
    welcomeMessage: string;
    functionDescription: string;
    inputPlaceholder: string;
    modelNames: string[] | string[][];
    webSearch?: Record<string, string>; // 新增动态错误存储
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
    // 添加这两个属性
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
    }, parentFormData, parentSetFormData);

    useEffect(() => {
        modelRefs.current = modelRefs.current.slice(0, formData.models.length);
    }, [formData.models]);
    const [webSearchDialogOpen, setWebSearchDialogOpen] = useState(false);
    // 非admin角色跳走
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
    const handleWebSearchSave = async (config) => {
        const res = await getAssistantToolsApi('default');
        console.log(res, 222);
        const webSearchTool = res.find(tool => tool.name === "联网搜索");

        if (!webSearchTool) {
            console.error("Web search tool not found");
            return;
        }
        const toolId = webSearchTool.id;
        setFormData(prev => ({ ...prev, webSearch: config }));
        await updateAssistantToolApi(toolId, config);
        setWebSearchDialogOpen(false)
    }
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
    // 在父组件中添加这个方法
    const handleWebSearchChange = useCallback((field: string, value: any) => {
        console.log('更新字段:', field, '新值:', value);

        // 更新本地状态
        setFormData(prev => ({
            ...prev,
            webSearch: {
                ...prev.webSearch,
                [field]: value
            }
        }));

    }, [setFormData]); // 添加依赖项
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

                        {/* 新增的应用中心描述输入框 */}
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
                        <div className="mb-6">
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
                            title="语音输入"
                            enabled={formData.voiceInput.enabled}
                            onToggle={(enabled) => toggleFeature('voiceInput', enabled)}
                        >
                            <Label className="bisheng-label">语音输入模型选择</Label>
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
                            title={t('chatConfig.webSearch')}
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
                    <WebSearchForm
                        prompt={formData.webSearch.prompt}
                        enabled={formData.webSearch.enabled}
                        formData={formData}
                        onSubmit={handleWebSearchSave}
                    />
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
}

const useChatConfig = (refs: UseChatConfigProps, parentFormData, parentSetFormData) => {
    const [formData, setFormData] = useState<ChatConfigForm>(parentFormData || {
        menuShow: true,

        systemPrompt: "你是BISHENG智能问答助手，你的任务是根据用户问题进行回答。在回答时，请注意以下几点：- 当前时间是{cur_date}。- 不要泄露任何敏感信息，回答应基于一般性知识和逻辑。- 确保回答不违反法律法规、道德准则和公序良俗。",
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
            prompt: `# 以下内容是基于用户发送的消息的搜索结果:
{search_results}
在我给你的搜索结果中，每个结果都是[webpage X begin]...[webpage X end]格式的，X代表每篇文章的数字索引。请在适当的情况下在句子末尾引用上下文。请按照引用编号[citation:X]的格式在答案中对应部分引用上下文。如果一句话源自多个上下文，请列出所有相关的引用编号，例如:cite[3]:cite[5]，切记不要将引用集中在最后返回引用编号，而是在答案对应部分列出。
在回答时，请注意以下几点：
- 今天是{cur_date}。
- 并非搜索结果的所有内容都与用户的问题密切相关，你需要结合问题，对搜索结果进行甄别、筛选。
- 对于列举类的问题（如列举所有航班信息），尽量将答案控制在10个要点以内，并告诉用户可以查看搜索来源、获得完整信息。优先提供信息完整、最相关的列举项；如非必要，不要主动告诉用户搜索结果未提供的内容。
- 对于创作类的问题（如写论文），请务必在正文的段落中引用对应的参考编号，例如:cite[3]:cite[5]，不能只在文章末尾引用。你需要解读并概括用户的题目要求，选择合适的格式，充分利用搜索结果并抽取重要信息，生成符合用户要求、极具思想深度、富有创造力与专业性的答案。你的创作篇幅需要尽可能延长，对于每一个要点的论述要推测用户的意图，给出尽可能多角度的回答要点，且务必信息量大、论述详尽。
- 如果回答很长，请尽量结构化、分段落总结。如果需要分点作答，尽量控制在5个点以内，并合并相关的内容。
- 对于客观类的问答，如果问题的答案非常简短，可以适当补充一到两句相关信息，以丰富内容。
- 你需要根据用户要求和回答内容选择合适、美观的回答格式，确保可读性强。
- 你的回答应该综合多个相关网页来回答，不能重复引用一个网页。
- 除非用户要求，否则你回答的语言需要和用户提问的语言保持一致。

# 用户消息为：
{question}`,
        },
        knowledgeBase: {
            enabled: true, prompt: `{retrieved_file_content}
{question}` },
        fileUpload: {
            enabled: true,
            prompt: `{file_content}
{question}`,
        },
    });
    useEffect(() => {
        if (parentFormData) {
            setFormData(parentFormData);
        }
    }, [parentFormData]);

    useEffect(() => {
        parentSetFormData?.(formData);
    }, [formData]);

    //         const sidebarSloganRef = useRef<HTMLDivElement>(null);
    // const welcomeMessageRef = useRef<HTMLDivElement>(null);
    // const functionDescriptionRef = useRef<HTMLDivElement>(null);
    // const inputPlaceholderRef = useRef<HTMLDivElement>(null);
    // const knowledgeBaseRef = useRef<HTMLDivElement>(null);
    // const modelRefs = useRef<(HTMLDivElement | null)[]>([]);
    // const webSearchRef = useRef<HTMLDivElement>(null);
    // const systemPromptRef = useRef<HTMLDivElement>(null);
    useEffect(() => {
        if (!parentFormData) {
            console.log('parentFormData :>> ', parentFormData);

            getWorkstationConfigApi().then((res) => {
                if (res) {
                    // 确保 systemPrompt 有值
                    const defaultSystemPrompt = `你是BISHENG智能问答助手，你的任务是根据用户问题进行回答。
在回答时，请注意以下几点：
- 当前时间是{cur_date}。
- 不要泄露任何敏感信息，回答应基于一般性知识和逻辑。
- 确保回答不违反法律法规、道德准则和公序良俗。`
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
    console.log('errors :>> ', errors);

    const handleInputChange = (field: keyof ChatConfigForm, value: string, maxLength: number) => {
        setFormData(prev => ({ ...prev, [field]: value }));

        if (value.length >= maxLength) {
            setErrors(prev => ({ ...prev, [field]: `最多${maxLength}个字符` }));
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

        // 验证应用中心描述
        if (formData.applicationCenterDescription.length > 1000) {
            newErrors.applicationCenterDescription = t('chatConfig.errors.maxCharacters', { count: 1000 });
            if (!firstErrorRef) firstErrorRef = refs.appCenterDescriptionRef;
            isValid = false;
        }
        // Validate models
        if (formData.models.length === 0) {
            newErrors.model = t('chatConfig.errors.atLeastOneModel');
            if (!firstErrorRef) {
                firstErrorRef = refs.modelRefs.current[0] ?
                    { current: refs.modelRefs.current[0] } :
                    refs.sidebarSloganRef; // 默认回退
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
                    behavior: 'smooth', // 平滑滚动
                    block: 'end', // 滚动后文本框底部显示在视图中（下方位置）
                    inline: 'nearest'
                });

                // 延迟聚焦输入框，确保滚动完成后再聚焦（提升体验）
                setTimeout(() => {
                    const input = firstErrorRef.current?.querySelector('input, textarea, [role="combobox"]');
                    if (input) input.focus(); // 聚焦到错误输入框
                }, 300); // 300ms 匹配滚动动画时长
            }
            return false;
        }
        const dataToSave = {
            ...formData,
            sidebarSlogan: formData.sidebarSlogan.trim(),
            welcomeMessage: formData.welcomeMessage.trim(),
            functionDescription: formData.functionDescription.trim(),
            inputPlaceholder: formData.inputPlaceholder.trim(),
            applicationCenterWelcomeMessage: formData.applicationCenterWelcomeMessage.trim() || '探索BISHENG的智能体',
            applicationCenterDescription: formData.applicationCenterDescription.trim() || '您可以在这里选择需要的智能体来进行生产与工作~',
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