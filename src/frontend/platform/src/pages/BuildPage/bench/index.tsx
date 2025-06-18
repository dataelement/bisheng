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
import { useContext, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
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
    webSearch?: Record<string, string>; // 新增动态错误存储
    systemPrompt: string;
    model: string;
    kownledgeBase: string;
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
    models: Model[];
    maxTokens: number;
    voiceInput: {
        enabled: boolean;
        model: string;
    };
    webSearch: {
        enabled: boolean;
        tool: string;
        params: {
            api_key?: string;
            base_url?: string;
            engine?: string;
        },
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

export default function index() {
    const {
        formData,
        errors,
        setFormData,
        handleInputChange,
        toggleFeature,
        handleSave
    } = useChatConfig();

    // 非admin角色跳走
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
            models: [...prev.models, { key: generateUUID(4), id: '', name: '', displayName: '' }]
        }));
    };

    return (
        <div className="px-10 py-10 h-full overflow-y-scroll scrollbar-hide relative bg-background-main border-t">
            <Card className="">
                <CardContent className="pt-4 relative  ">
                    <div className="w-full  max-h-[calc(100vh-180px)] overflow-y-scroll scrollbar-hide">
                        <ToggleSection
                            title="工作台入口"
                            enabled={formData.menuShow}
                            onToggle={(enabled) => setFormData(prev => ({ ...prev, menuShow: enabled }))}
                        >{null}</ToggleSection>
                        {/* Icon Uploads */}
                        <p className="text-lg font-bold mb-2">图标上传</p>
                        <div className="flex gap-8 mb-6">
                            <IconUploadSection
                                label="左侧边栏图标"
                                enabled={formData.sidebarIcon.enabled}
                                image={formData.sidebarIcon.image}
                                onToggle={(enabled) => toggleFeature('sidebarIcon', enabled)}
                                onUpload={(fileUrl, relativePath) => uploadAvator(fileUrl, 'sidebar', relativePath)}
                            />
                            <IconUploadSection
                                label="欢迎页面图标&对话头像"
                                enabled={formData.assistantIcon.enabled}
                                image={formData.assistantIcon.image}
                                onToggle={(enabled) => toggleFeature('assistantIcon', enabled)}
                                onUpload={(fileUrl, relativePath) => uploadAvator(fileUrl, 'assistant', relativePath)}
                            />
                        </div>

                        {/* Form Inputs */}
                        <FormInput
                            label={<Label className="bisheng-label">左侧边栏slogan</Label>}
                            value={formData.sidebarSlogan}
                            error={errors.sidebarSlogan}
                            placeholder=""
                            maxLength={15}
                            onChange={(v) => handleInputChange('sidebarSlogan', v, 15)}
                        />

                        <FormInput
                            label="欢迎语设置"
                            value={formData.welcomeMessage}
                            error={errors.welcomeMessage}
                            placeholder="我是 xx，很高兴见到你！"
                            maxLength={1000}
                            onChange={(v) => handleInputChange('welcomeMessage', v, 1000)}
                        />

                        <FormInput
                            label="功能说明"
                            value={formData.functionDescription}
                            error={errors.functionDescription}
                            placeholder="我可以帮你写代码、读文件、写作各种创意内容，请把你的任务交给我吧～"
                            maxLength={1000}
                            onChange={(v) => handleInputChange('functionDescription', v, 1000)}
                        />

                        <FormInput
                            label="输入框提示语"
                            value={formData.inputPlaceholder}
                            error={errors.inputPlaceholder}
                            placeholder="给xx发送消息"
                            maxLength={1000}
                            onChange={(v) => handleInputChange('inputPlaceholder', v, 100)}
                        />

                        {/* Model Management */}
                        <div className="mb-6">
                            <p className="text-lg font-bold mb-2">对话模型管理</p>
                            <div className="mb-6">
                                <ModelManagement
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
                                    onNameChange={(index, name) => {
                                        handleModelNameChange(index, name);
                                    }}
                                />
                            </div>
                            <FormInput
                                label={<Label className="bisheng-label block pt-2">知识库/联网检索结果最大字符数</Label>}
                                type="number"
                                value={formData.maxTokens}
                                error={''}
                                placeholder="模型支持的最大字符数"
                                maxLength={1000}
                                onChange={(v) => handleInputChange('maxTokens', v, 100)}
                            />
                            <FormInput
                                label={<Label className="bisheng-label">系统提示词</Label>}
                                isTextarea
                                value={formData.systemPrompt}
                                error={errors.systemPrompt}
                                placeholder="你是毕昇 AI 助手"
                                maxLength={30000}
                                onChange={(val) => setFormData(prev => ({
                                    ...prev,
                                    systemPrompt: val
                                }))}
                            />
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
                            title="联网搜索"
                            enabled={formData.webSearch.enabled}
                            onToggle={(enabled) => toggleFeature('webSearch', enabled)}
                        >
                            <WebSearchConfig
                                config={formData.webSearch}
                                onChange={(field, value) => setFormData(prev => ({
                                    ...prev,
                                    webSearch: { ...prev.webSearch, [field]: value }
                                }))}
                                errors={errors.webSearch} // 传递错误信息
                            />
                        </ToggleSection>

                        <ToggleSection
                            title="个人知识"
                            enabled={formData.knowledgeBase.enabled}
                            onToggle={(enabled) => toggleFeature('knowledgeBase', enabled)}
                        >
                            <FormInput
                                label={<Label className="bisheng-label">个人知识库搜索提示词</Label>}
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
                            title="文件上传"
                            enabled={formData.fileUpload.enabled}
                            onToggle={(enabled) => toggleFeature('fileUpload', enabled)}
                        >
                            <FormInput
                                label={<Label className="bisheng-label">文件上传提示词</Label>}
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
                        <Button onClick={handleSave}>保存</Button>
                    </div>
                </CardContent>
            </Card>
        </div>
    );
}




const useChatConfig = () => {
    const [formData, setFormData] = useState<ChatConfigForm>({
        menuShow: true,
        systemPrompt: '你是毕昇 AI 助手',
        sidebarIcon: { enabled: true, image: '', relative_path: '' },
        assistantIcon: { enabled: true, image: '', relative_path: '' },
        sidebarSlogan: '',
        welcomeMessage: '',
        functionDescription: '',
        inputPlaceholder: '',
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
在我给你的搜索结果中，每个结果都是[webpage X begin]...[webpage X end]格式的，X代表每篇文章的数字索引。请在适当的情况下在句子末尾引用上下文。请按照引用编号[citation:X]的格式在答案中对应部分引用上下文。如果一句话源自多个上下文，请列出所有相关的引用编号，例如[citation:3][citation:5]，切记不要将引用集中在最后返回引用编号，而是在答案对应部分列出。
在回答时，请注意以下几点：
- 今天是{cur_date}。
- 并非搜索结果的所有内容都与用户的问题密切相关，你需要结合问题，对搜索结果进行甄别、筛选。
- 对于列举类的问题（如列举所有航班信息），尽量将答案控制在10个要点以内，并告诉用户可以查看搜索来源、获得完整信息。优先提供信息完整、最相关的列举项；如非必要，不要主动告诉用户搜索结果未提供的内容。
- 对于创作类的问题（如写论文），请务必在正文的段落中引用对应的参考编号，例如[citation:3][citation:5]，不能只在文章末尾引用。你需要解读并概括用户的题目要求，选择合适的格式，充分利用搜索结果并抽取重要信息，生成符合用户要求、极具思想深度、富有创造力与专业性的答案。你的创作篇幅需要尽可能延长，对于每一个要点的论述要推测用户的意图，给出尽可能多角度的回答要点，且务必信息量大、论述详尽。
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
        getWorkstationConfigApi().then((res) => {
            // res.webSearch.params = {
            //     api_key: '',
            //     base_url: 'https://api.bing.microsoft.com/v7.0/search'
            // }
            res && setFormData(res);
        })
    }, [])

    const [errors, setErrors] = useState<FormErrors>({
        sidebarSlogan: '',
        systemPrompt: '',
        welcomeMessage: '',
        functionDescription: '',
        inputPlaceholder: '',
        kownledgeBase: '',
        model: '',
        modelNames: [],
    });
    console.log('errors :>> ', errors);

    const handleInputChange = (field: keyof ChatConfigForm, value: string, maxLength: number) => {
        setFormData(prev => ({ ...prev, [field]: value }));

        // if (value.length > maxLength) {
        //     setErrors(prev => ({ ...prev, [field]: `最多${maxLength}个字符` }));
        // } else {
        //     setErrors(prev => ({ ...prev, [field]: '' }));
        // }
    };

    const toggleFeature = (feature: keyof ChatConfigForm, enabled: boolean) => {
        setFormData(prev => ({
            ...prev,
            [feature]: { ...prev[feature], enabled }
        }));
    };

    const validateForm = (): boolean => {
        let isValid = true;
        const newErrors: FormErrors = {
            sidebarSlogan: '',
            welcomeMessage: '',
            functionDescription: '',
            inputPlaceholder: '',
            kownledgeBase: '',
            model: '',
            modelNames: [],
        };

        if (formData.sidebarSlogan.length > 15) {
            newErrors.sidebarSlogan = '最多15个字符';
            isValid = false;
        }

        // Validate welcome message
        if (formData.welcomeMessage.length > 1000) {
            newErrors.welcomeMessage = '最多1000个字符';
            isValid = false;
        }

        // Validate function description
        if (formData.functionDescription.length > 1000) {
            newErrors.functionDescription = '最多1000个字符';
            isValid = false;
        }

        // Validate input placeholder
        if (formData.inputPlaceholder.length > 100) {
            newErrors.inputPlaceholder = '最多100个字符';
            isValid = false;
        }

        if (formData.knowledgeBase.prompt.length > 30000) {
            newErrors.kownledgeBase = '最多30000个字符';
            isValid = false;
        }

        // Validate models
        if (formData.models.length === 0) {
            newErrors.model = '至少添加一个模型';
            isValid = false;
        }
        const modelNameErrors: string[][] = [];
        formData.models.forEach((model, index) => {
            const displayName = model.displayName.trim();
            let error = [];

            // 检查是否为空
            if (!displayName) {
                error = ['', '模型显示名称不能为空'];
            } else if (!model.id) {
                error = ['模型不能为空', ''];
            }
            // 检查长度
            else if (displayName.length > 30) {
                error = ['', '最多30个字符'];
            }
            // 检查重复（仅在非空且长度有效时检查）
            else {
                console.log('formData.models :>> ', formData.models);
                formData.models.some(
                    (m, i) => {
                        if (i !== index) {
                            error = ['', ''];
                            if (m.id === model.id) {
                                error[0] = '模型不能重复'
                            }
                            if (m.displayName.trim().toLowerCase() === displayName.toLowerCase()) {
                                error[1] = '显示名称不能重复'
                            }
                            if (error[0] || error[1]) {
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

            // 根据当前工具动态校验
            switch (formData.webSearch.tool) {
                case 'bing':
                    if (!formData.webSearch.params.api_key?.trim()) {
                        webSearchErrors.params = {
                            ...webSearchErrors.params,
                            api_key: '不能为空'
                        };
                        isValid = false;
                    }
                    if (!formData.webSearch.params.base_url?.trim()) {
                        webSearchErrors.params = {
                            ...webSearchErrors.params,
                            base_url: '不能为空'
                        };
                        isValid = false;
                    }
                    break;

                case 'bocha':
                case 'jina':
                case 'tavily':
                    if (!formData.webSearch.params.api_key?.trim()) {
                        webSearchErrors.params = {
                            ...webSearchErrors.params,
                            api_key: '不能为空'
                        };
                        isValid = false;
                    }
                    break;

                case 'serp':
                    if (!formData.webSearch.params.api_key?.trim()) {
                        webSearchErrors.params = {
                            ...webSearchErrors.params,
                            api_key: '不能为空'
                        };
                        isValid = false;
                    }
                    if (!formData.webSearch.params.engine?.trim()) {
                        webSearchErrors.params = {
                            ...webSearchErrors.params,
                            engine: '不能为空'
                        };
                        isValid = false;
                    }
                    break;

                // 其他工具的校验可以在这里添加
            }

            if (Object.keys(webSearchErrors).length) {
                newErrors.webSearch = webSearchErrors;
            }
        }

        newErrors.modelNames = modelNameErrors;

        setErrors(newErrors);
        return isValid;
    };

    const { toast } = useToast()
    const { reloadConfig } = useContext(locationContext)
    const handleSave = async () => {
        if (!validateForm()) {
            return;
        }


        // Prepare the data to be saved
        const dataToSave = {
            ...formData,
            // Ensure sidebar slogan has a default value
            sidebarSlogan: formData.sidebarSlogan.trim(),
            welcomeMessage: formData.welcomeMessage.trim(),
            functionDescription: formData.functionDescription.trim(),
            inputPlaceholder: formData.inputPlaceholder.trim(),
            maxTokens: formData.maxTokens || 15000,
        };

        // Here you would typically make an API call to save the data
        // For example:
        // const response = await api.saveChatConfig(dataToSave);
        console.log('Saving data:', dataToSave);

        captureAndAlertRequestErrorHoc(setWorkstationConfigApi(dataToSave)).then((res) => {
            if (res) {
                // Show success message or handle response
                toast({
                    variant: 'success',
                    description: '配置保存成功',
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