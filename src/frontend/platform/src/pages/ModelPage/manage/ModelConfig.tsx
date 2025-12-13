import { LoadingIcon } from "@/components/bs-icons/loading";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button, LoadButton } from "@/components/bs-ui/button";
import { Input, Textarea } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { Switch } from "@/components/bs-ui/switch";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { generateUUID } from "@/components/bs-ui/utils";
import ShadTooltip from "@/components/ShadTooltipComponent";
import { addLLmServer, deleteLLmServer, getLLmServerDetail, updateLLmServer } from "@/controllers/API/finetune";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { ArrowLeft, Plus, Settings, Trash2Icon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import CustomForm from "./CustomForm";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/bs-ui/dialog";
import { getAdvancedParamsTemplate, templateToJsonString } from "@/util/advancedParamsTemplates";
import { useLinsightConfig } from "./tabs/WorkbenchModel";
import { useModelProviderInfo } from "./useLink";
import { t } from "i18next";

function ModelItem({ data, type, onDelete, onInput, onConfig }) {
    const { t } = useTranslation()
    const [model, setModel] = useState({
        ...data,
        voice: data.config?.voice || ''
    })
    const [error, setError] = useState('')
    const [isWebSearchEnabled, setIsWebSearchEnabled] = useState(data.config?.enable_web_search || false)
    const [maxTokens, setMaxTokens] = useState(data.config?.max_tokens ?? '')
    const [voiceError, setVoiceError] = useState('')
    const [dialogOpen, setDialogOpen] = useState(false);
    const [inputAdvancedParams, setInputAdvancedParams] = useState('');
    const [savedInputParams, setSavedInputParams] = useState(data.config?.user_kwargs || '');
    const [advancedParams, setAdvancedParams] = useState(() => {
        const template = getAdvancedParamsTemplate(type, model.model_type as 'llm' | 'embedding') || {};
        return templateToJsonString(template)
    });
    const [originalAdvancedParams, setOriginalAdvancedParams] = useState(advancedParams);
    const [jsonError, setJsonError] = useState(false);

    const prevDepsRef = useRef({
        type: type,
        modelType: model.model_type,
        dialogOpen: dialogOpen
    });

    useEffect(() => {
        setModel({
            ...data,
            voice: data.config?.voice || ''
        });
        const userSavedParams = data.config?.user_kwargs || '';
        setSavedInputParams(userSavedParams);

        const template = getAdvancedParamsTemplate(type, model.model_type as 'llm' | 'embedding') || {};
        const newPlaceholder = templateToJsonString(template) || '{"temperature": 0.7, "top_p": 0.9}';
        setAdvancedParams(newPlaceholder);
        setOriginalAdvancedParams(newPlaceholder);

        if (dialogOpen) {
            setInputAdvancedParams(userSavedParams);
            initTemplate();
        }
        setJsonError(false);
    }, [data, dialogOpen, type, model.model_type]);

    const initTemplate = () => {
        if (!['llm', 'embedding'].includes(model.model_type)) return;

        try {
            const template = getAdvancedParamsTemplate(type, model.model_type as 'llm' | 'embedding');
            const templateStr = templateToJsonString(template);

            if (templateStr !== advancedParams) {
                setAdvancedParams(templateStr);
                setInputAdvancedParams(templateStr);
                if (!originalAdvancedParams) {
                    setOriginalAdvancedParams(templateStr);
                }
                onConfig({
                    ...model.config,
                    user_kwargs: templateStr
                });
            }
        } catch (err) {
            console.error('Failed to initialize template:', err);
        }
    };

    useEffect(() => {
        if (dialogOpen) {
            const currentDeps = {
                type: type,
                modelType: model.model_type,
                dialogOpen: dialogOpen
            };

            if (
                currentDeps.type !== prevDepsRef.current.type ||
                currentDeps.modelType !== prevDepsRef.current.modelType ||
                currentDeps.dialogOpen !== prevDepsRef.current.dialogOpen
            ) {
                initTemplate();
                prevDepsRef.current = currentDeps;
            }
        } else {
            prevDepsRef.current.dialogOpen = false;
        }
    }, [dialogOpen, type, model.model_type]);

    const handleInput = (e) => {
        const value = e.target.value
        const updatedModel = { ...model, model_name: value }
        setModel(updatedModel)
        const repeated = onInput(value, model.model_type)

        setError('')
        if (!value) setError(t('model.modelNameEmpty'))
        if (value.length > 100) setError(t('model.modelNameLength'))
        if (repeated) setError(t('model.modelNameDuplicate'))
    }

    const handleVoiceInput = (e) => {
        const value = e.target.value
        const updatedModel = { ...model, voice: value }
        setModel(updatedModel)
        onConfig({ ...model.config, voice: value })
        setVoiceError('')
    }

    const handleSelectChange = (val) => {
        const oldType = model.model_type;
        const updatedModel = { ...model, model_type: val }
        setModel(updatedModel)
        onInput(model.model_name, val)

        setIsWebSearchEnabled(false)
        setMaxTokens('')

        if (dialogOpen && oldType !== val) {
            initTemplate();
        }
    }

    const handleDelClick = () => {
        bsConfirm({
            desc: t('model.deleteModelConfirmation'),
            onOk(next) {
                onDelete()
                next()
            }
        })
    }

    const handleSwitchChange = (checked) => {
        setIsWebSearchEnabled(checked)
        onConfig({
            enable_web_search: checked,
            max_tokens: maxTokens,
            ...(model.config?.user_kwargs && { user_kwargs: model.config.user_kwargs })
        })
    }

    const handleMaxTokensChange = (e) => {
        const value = e.target.value
        setMaxTokens(value)

        if (value === '') {
            onConfig({
                enable_web_search: isWebSearchEnabled,
                ...(model.config?.user_kwargs && { user_kwargs: model.config.user_kwargs })
            })
        } else {
            onConfig({
                enable_web_search: isWebSearchEnabled,
                max_tokens: parseInt(value, 10),
                ...(model.config?.user_kwargs && { user_kwargs: model.config.user_kwargs })
            })
        }
    }

    const handleSaveAdvancedParams = () => {
        const currentInput = inputAdvancedParams.trim();
        if (currentInput) {
            try {
                const parsed = JSON.parse(currentInput);
                if (typeof parsed !== 'object' || parsed === null) {
                    setJsonError(true);
                    return;
                }
                setJsonError(false);
            } catch (err) {
                setJsonError(true);
                return;
            }
        }

        onConfig({
            ...model.config,
            user_kwargs: currentInput
        });
        setSavedInputParams(currentInput);
        setInputAdvancedParams(currentInput);
        setDialogOpen(false);
        setJsonError(false);
    };

    const handleCloseDialog = () => {
        setInputAdvancedParams(savedInputParams);
        setJsonError(false);
        setDialogOpen(false);
    };

    const refreshTemplate = () => {
        if (dialogOpen) {
            initTemplate();
        }
    };
    const showAsrTtsTypes = ['azure_openai', 'openai', 'qwen', 'qianfan'];
    return (
        <div className="group w-full border rounded-sm p-4 mb-2">
            <div className="flex items-center justify-between">
                <span className="flex">{model.name.replace('model', t('model.model'))}

                    {(model.model_type === 'llm' || model.model_type === 'embedding') && (
                        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
                            <DialogTrigger asChild>
                                <div className="flex items-center cursor-pointer ml-2">
                                    <Settings className=" text-blue-500" size={16} strokeWidth={2} />
                                    <span className="ml-1 text-blue-500 text-xs">{t('model.advancedParamsConfig')}</span>
                                </div>
                            </DialogTrigger>

                            <DialogContent className="sm:max-w-[625px]">
                                <DialogHeader>
                                    <DialogTitle>{t('model.advancedParamsConfig')}</DialogTitle>
                                </DialogHeader>
                                <div className="mt-4 text-gray-500">
                                    <Label>{t('model.pasteAdvancedParamsHere')}</Label>
                                    <Textarea
                                        value={inputAdvancedParams}
                                        onChange={(e) => {
                                            const value = e.target.value;
                                            setInputAdvancedParams(value);
                                            
                                            if (value.trim()) {
                                                try {
                                                    const parsed = JSON.parse(value.trim());
                                                    if (typeof parsed !== 'object' || parsed === null) {
                                                        setJsonError(true);
                                                    } else {
                                                        setJsonError(false);
                                                    }
                                                } catch (err) {
                                                    setJsonError(true);
                                                }
                                            } else {
                                                setJsonError(false);
                                            }
                                        }}
                                        className={`mt-1 font-mono text-sm ${jsonError ? 'border-red-500 focus-visible:ring-red-500' : ''}`}
                                        rows={10}
                                        placeholder={advancedParams}
                                    />
                                    {jsonError && (
                                        <span className="text-red-500 text-xs mt-1 inline-block">
                                            {t('model.errorInvalidJsonFormat')}
                                        </span>
                                    )}
                                </div>
                                <DialogFooter className="mt-4">
                                    <Button variant="outline" onClick={handleCloseDialog}>{t('model.cancel')}</Button>
                                    <Button onClick={handleSaveAdvancedParams}>{t('model.save')}</Button>
                                </DialogFooter>
                            </DialogContent>
                        </Dialog>
                    )}
                </span>

                <Trash2Icon
                    onClick={handleDelClick}
                    className="w-[16px] h-[16px] opacity-0 group-hover:opacity-100 cursor-pointer text-gray-500"
                />
            </div>
            <div className="space-y-2 mt-2">
                <div>
                    <Label className="bisheng-label">
                        <span>{t('model.modelName')}</span>
                        <QuestionTooltip
                            className="relative top-0.5 ml-1"
                            content={t('model.modelNameTooltip')}
                        ><span /></QuestionTooltip>
                    </Label>
                    <Input value={model.model_name} onChange={handleInput} className="h-8"></Input>
                    {error && <span className="text-red-500 text-xs">{error}</span>}
                </div>
                <div>
                    <Label className="bisheng-label">{t('model.modelType')}</Label>
                    <Select value={model.model_type} onValueChange={handleSelectChange}>
                        <SelectTrigger className="h-8">
                            <SelectValue placeholder="" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectGroup>
                                <SelectItem value="llm">{t('model.llm')}</SelectItem>
                                <SelectItem value="embedding">{t('model.embedding')}</SelectItem>
                                <SelectItem value="rerank">{t('model.rerank')}</SelectItem>
                                {showAsrTtsTypes.includes(type) && (
                                    <>
                                        <SelectItem value="asr">{t('model.asr')}</SelectItem>
                                        <SelectItem value="tts">{t('model.tts')}</SelectItem>
                                    </>
                                )}
                            </SelectGroup>
                        </SelectContent>
                    </Select>
                </div>
                {model.model_type === 'tts' && (
                    <div>
                        <Label className="bisheng-label">
                            <span>{t('model.voiceType')}</span>
                            <span className="text-red-500">*</span>
                            <QuestionTooltip
                                className="relative top-0.5 ml-1"
                                content={t('model.voiceTypeTooltip')}
                            ><span /></QuestionTooltip>
                        </Label>
                        <Input
                            value={model.voice || ''}
                            onChange={handleVoiceInput}
                            className="h-8"
                        ></Input>

                        {voiceError && <span className="text-red-500 text-xs">{voiceError}</span>}
                    </div>
                )}
                {model.model_type === 'llm' && (
                    <>
                        {['qwen', 'tencent', 'moonshot'].includes(type) && <div className="flex gap-2 items-center">
                            <Label className="bisheng-label">
                                {t('model.webSearch')}
                            </Label>
                            <Switch checked={isWebSearchEnabled} onCheckedChange={handleSwitchChange} />
                        </div>}
                        <div>
                            <Label className="bisheng-label">
                                {type === 'qianfan' ? 'max_output_tokens' : (type === 'ollama' ? 'num_ctx' : 'max_tokens')}
                            </Label>
                            <Input
                                type="number"
                                value={maxTokens}
                                onChange={handleMaxTokensChange}
                                className="h-8"
                            />
                        </div>
                    </>
                )}
            </div>
        </div>
    )
}

export const modelProvider = [
    { "name": "OpenAI", "value": "openai" },
    { "name": "Azure OpenAI", "value": "azure_openai" },
    { "name": "Ollama", "value": "ollama" },
    { "name": "xinference", "value": "xinference" },
    { "name": "llamacpp", "value": "llamacpp" },
    { "name": "vllm", "value": "vllm" },
    { "name": t('model.aliYunBaiLian'), "value": "qwen" }, // Using translation key
    { "name": "DeepSeek", "value": "deepseek" },
    { "name": t('model.guiJiLiuDong'), "value": "silicon" }, // Using translation key
    { "name": t('model.huoShanYinQing'), "value": "volcengine" }, // Using translation key
    { "name": t('model.zhiPuAI'), "value": "zhipu" }, // Using translation key
    { "name": t('model.xunFeiXingHuo'), "value": "spark" }, // Using translation key
    { "name": t('model.tengXunYun'), "value": "tencent" }, // Using translation key
    { "name": t('model.yueZhiAnMian'), "value": "moonshot" }, // Using translation key
    { "name": t('model.baiDuQianFan'), "value": "qianfan" }, // Using translation key
    { "name": "Minimax", "value": "minimax" },
    { "name": "Anthropic", "value": "anthropic" },
    { "name": "MindIE", "value": "MindIE" },
]
const bishengModelProvider = { "name": "bishengRT", "value": "bisheng_rt" }

const defaultForm = {
    id: null as any,
    type: '',
    name: '',
    limit_flag: false,
    limit: 1,
    config: {},
    models: []
}

export default function ModelConfig({ id, onGetName, onBack, onReload, onBerforSave, onAfterSave }) {
    const { t } = useTranslation()
    const { refetch: refetchConfig } = useLinsightConfig();

    const [formData, setFormData] = useState({ ...defaultForm })
    const [modelRefs, setModelRefs] = useState({});

    useEffect(() => {
        if (id === -1) return
        getLLmServerDetail(id).then(res => {
            setFormData(res)
            const refs = {};
            res.models.forEach(model => {
                refs[model.id] = null;
            });
            setModelRefs(refs);
        })
    }, [id])

    const getModelsByType = useSelectModel()
    const handleTypeChange = (val) => {
        const name = onGetName(_modelProvider.find(el => el.value === val).name || '')
        const models = getModelsByType(val)
        setFormData({ ...formData, type: val, name, models })
        const refs = {};
        models.forEach(model => {
            refs[model.id] = null;
        });
        setModelRefs(refs);
    }

    const handleAddModel = () => {
        const maxIndex = formData.models.reduce((max, el, i) => el.name.match(/model (\d+)/) ? Math.max(max, +el.name.match(/model (\d+)/)[1]) : max, 0)

        const model = {
            id: generateUUID(4),
            name: `model ${maxIndex + 1}`,
            model_name: '',
            model_type: 'llm',
            voice: ''
        }
        const newModels = [...formData.models, model];
        setFormData({ ...formData, models: newModels })
        setModelRefs(prev => ({
            ...prev,
            [model.id]: null
        }));
    }

    const handleDelete = (index) => {
        const models = formData.models.filter((el, i) => index !== i)
        setFormData({ ...formData, models })
        const modelId = formData.models[index].id;
        setModelRefs(prev => {
            const newRefs = { ...prev };
            delete newRefs[modelId];
            return newRefs;
        });
    }

    const handleModelChange = (name, type, index) => {
        const models = formData.models.map((el, i) => index === i ? {
            ...el,
            config: type === 'llm' ? el.config : null,
            model_name: name,
            model_type: type,
            voice: type === 'tts' ? (el.voice || '') : ''
        } : el)
        setFormData({ ...formData, models })

        setTimeout(() => {
            if (modelRefs[models[index].id]?.refreshTemplate) {
                modelRefs[models[index].id].refreshTemplate();
            }
        }, 0);

        return formData.models.find((el, i) => index !== i && el.model_name === name)
    }

    const handleVoiceChange = (voice, index) => {
        const models = formData.models.map((el, i) => index === i ? {
            ...el,
            voice
        } : el)
        setFormData({ ...formData, models })
    }

    const handleModelConfig = (config, index) => {
        const models = formData.models.map((el, i) => index === i ? {
            ...el,
            config
        } : el)
        setFormData({ ...formData, models })
    }

    const { message } = useToast()
    const formRef = useRef(null)
    const [isLoading, setIsLoading] = useState(false);
    const handleSave = async () => {
        setIsLoading(true)
        try {
            const exists = onBerforSave(formData.id, formData.name)
            if (exists) {
                return message({
                    variant: 'warning',
                    description: t('model.duplicateServiceProviderName')
                })
            }
            if (!formData.name || formData.name.length > 100) {
                return message({
                    variant: 'warning',
                    description: t('model.duplicateServiceProviderNameValidation')
                })
            }
            const [config, errorKey] = formRef.current.getData();
            if (errorKey) {
                return message({
                    variant: 'warning',
                    description: `${errorKey} ${t('model.notBeEmpty')}`
                })
            }

            const map = {}
            let repeat = false
            let hasTTSVoiceError = false

            const error = formData.models.some(model => {
                if (map[model.model_name]) repeat = true
                map[model.model_name] = true

                if (model.model_type === 'tts' && !model.config?.voice) {
                    hasTTSVoiceError = true
                }

                return !model.model_name || model.model_name.length > 100
            })
            if (error) {
                return message({
                    variant: 'warning',
                    description: t('model.modelNameValidation')
                })
            }
            if (repeat) {
                return message({
                    variant: 'warning',
                    description: t('model.modelDuplicate')
                })
            }
            if (hasTTSVoiceError) {
                return message({
                    variant: 'warning',
                    description: t('model.voiceTypeRequired')
                })
            }

            const saveData = {
                ...formData,
                config
            }

            if (id === -1) {
                await captureAndAlertRequestErrorHoc(addLLmServer(saveData).then(res => {
                    onAfterSave(res.code === 10803 ? res.msg : t('model.addSuccess'))
                    onBack()
                }))
            } else {
                await captureAndAlertRequestErrorHoc(updateLLmServer(saveData).then(res => {
                    onAfterSave(t('model.updateSuccess'))
                    onBack()
                }))
            }
            refetchConfig()
        } catch (error) {
            console.error('Save error:', error);
        } finally {
            setIsLoading(false);
        }
    };

    const handleModelDel = () => {
        bsConfirm({
            desc: t('model.deleteConfirmation'),
            onOk(next) {
                captureAndAlertRequestErrorHoc(deleteLLmServer(id).then(res => {
                    onAfterSave(t('model.deleteSuccess'))
                    refetchConfig()
                }))
                onBack()
                next()
            }
        })
    }

    const _modelProvider = useMemo(() => {
        return id === -1 ? modelProvider : [...modelProvider, bishengModelProvider]
    }, [id])

    const providerInfo = useModelProviderInfo(formData.type)

    if (!formData) return <div className="absolute left-0 top-0 z-10 flex h-full w-full items-center justify-center bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
        <LoadingIcon />
    </div>

    return <div className="relative size-full py-4">
        <div className="flex ml-6 items-center gap-x-3">
            <ShadTooltip content={t('back', { ns: 'bs' })} side="right">
                <button className="extra-side-bar-buttons w-[36px]" onClick={() => onBack()}>
                    <ArrowLeft strokeWidth={1.5} className="side-bar-button-size" />
                </button>
            </ShadTooltip>
            <span>{id === -1 ? t('model.addModel') : t('model.modelConfiguration')}</span>
        </div>
        <div className="w-[50%] min-w-64 px-4 pb-10 mx-auto mt-6 h-[calc(100vh-220px)] overflow-y-auto">
            <div className="mb-2">
                <Label className="bisheng-label"> {t('model.interModelFormat')}</Label>
                <Select value={formData.type} disabled={id !== -1} onValueChange={handleTypeChange}>
                    <SelectTrigger>
                        <SelectValue placeholder="" />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectGroup>
                            {_modelProvider.map((model => <SelectItem key={model.value} value={model.value}>{model.name}</SelectItem>))}
                        </SelectGroup>
                    </SelectContent>
                </Select>
            </div>
            <div className="mb-2">
                <Label className="bisheng-label">
                    <span>{t('model.serviceProviderName')}</span>
                    <QuestionTooltip className="relative top-0.5 ml-1" content={t('model.serviceProviderNameTooltip')}><span /></QuestionTooltip>
                </Label>
                <Input value={formData.name} onChange={(e) => {
                    const name = e.target.value
                    setFormData({ ...formData, name })
                    document.getElementById('model_provider_name_error').style.display = !name || name.length > 100 ? 'block' : 'none'
                }}></Input>
                <span id="model_provider_name_error" style={{ display: 'none' }} className="text-red-500 text-xs">{
                    formData.name ? t('model.max100Characters') : t('model.cannotBeEmpty')
                }</span>
            </div>
            <CustomForm
                ref={formRef}
                showDefault={id === -1}
                provider={formData.type}
                formData={formData.config}
                providerName={_modelProvider.find(el => el.value === formData.type)?.name}
                apiKeySite={providerInfo?.apiKeyUrl}
            />
            <div className={formData.type ? 'visible' : 'invisible'}>
                <div className="mb-2">
                    <div className="flex items-center gap-x-6">
                        <Label className="bisheng-label">
                            {t('model.dailyCallLimit')}
                        </Label>
                        <Switch checked={formData.limit_flag} onCheckedChange={(val) => setFormData(form => ({ ...form, limit_flag: val }))} />
                        <div className={`flex items-center gap-x-2 ${formData.limit_flag ? '' : 'invisible'}`}>
                            <Input type="number" value={formData.limit} onChange={(e) => setFormData({ ...formData, limit: Number(e.target.value) })}
                                className="w-24 h-8"
                            ></Input>
                            <span>{t('model.timesPerDay')}</span>
                        </div>
                    </div>
                </div>
                <div className="mb-2">
                    <Label className="bisheng-label">
                        {t('model.model')}
                        {providerInfo && <a href={providerInfo.modelUrl} target="_blank" rel="noreferrer" className="ml-1 text-primary/80">({t('model.visitOfficialWebsiteToViewAvailableModels')})</a>}
                    </Label>
                    <div className="w-[92%]">
                        {
                            formData.models.map((m, i) => (
                                <ModelItem
                                    key={m.id}
                                    ref={el => modelRefs[m.id] = el}
                                    data={m}
                                    type={formData.type}
                                    onInput={(name, type) => handleModelChange(name, type, i)}
                                    onVoiceChange={(voice) => handleVoiceChange(voice, i)}
                                    onConfig={(config) => handleModelConfig(config, i)}
                                    onDelete={() => handleDelete(i)}
                                />
                            ))
                        }
                        <Button className="w-full mt-2 border-dashed border-border" variant="outline" onClick={handleAddModel}>
                            <Plus className="size-5 text-primary mr-1" />
                            <span>{t('model.addModel')}</span>
                        </Button>
                    </div>
                </div>
            </div>
        </div>
        <div className="absolute right-0 bottom-0 p-4 flex gap-4">
            {id !== -1 && <Button className="px-8" variant="destructive" onClick={handleModelDel}>{t('model.delete')}</Button>}
            <Button className="px-8" variant="outline" onClick={() => onBack()}>{t('model.cancel')}</Button>
            <LoadButton
                className="px-16"
                disabled={!formData.type}
                loading={isLoading}
                onClick={handleSave}
            >
                {isLoading ? t('model.modelStatusChecking') : t('model.save')}
            </LoadButton>
        </div>
    </div>
}

const useSelectModel = () => {
    const modelsRef = useRef<any>(null)

    const loadData = async () => {
        try {
            const response = await fetch(__APP_ENV__?.BASE_URL + '/models/data.json');
            if (!response.ok) {
                throw new Error('Failed to fetch data');
            }
            return await response.json();
        } catch (error) {
            console.error('Failed to load commitments:', error);
            return { title: '', commitments: [] };
        }
    }

    useEffect(() => {
        loadData().then(
            res => modelsRef.current = res
        )
    }, [])

    return (type) => {
        return (modelsRef.current?.[type] || [])
            .map(item => ({
                ...item,
                id: generateUUID(4)
            }))
    }
}