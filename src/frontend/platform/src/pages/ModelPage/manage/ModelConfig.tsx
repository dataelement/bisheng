import { LoadingIcon } from "@/components/bs-icons/loading";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button, LoadButton } from "@/components/bs-ui/button";
import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { Switch } from "@/components/bs-ui/switch";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { generateUUID } from "@/components/bs-ui/utils";
import ShadTooltip from "@/components/ShadTooltipComponent";
import { addLLmServer, deleteLLmServer, getLLmServerDetail, updateLLmServer } from "@/controllers/API/finetune";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { ArrowLeft, Plus, Trash2Icon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import CustomForm from "./CustomForm";

function ModelItem({ data, type, onDelete, onInput, onConfig }) {
    const { t } = useTranslation('model')
    const [model, setModel] = useState(data)
    const [error, setError] = useState('')
    const [isWebSearchEnabled, setIsWebSearchEnabled] = useState(data.config?.enable_web_search || false)
    const [maxTokens, setMaxTokens] = useState(data.config?.max_tokens ?? '')
    const [voice, setVoice] = useState(data.config?.voice ?? '')

    const handleInput = (e) => {
        const value = e.target.value
        setModel({ ...model, model_name: value })
        const repeated = onInput(value, model.model_type)

        setError('')
        if (!value) setError(t('model.modelNameEmpty'))
        if (value.length > 100) setError(t('model.modelNameLength'))
        if (repeated) setError(t('model.modelNameDuplicate'))
    }

    const handleSelectChange = (val) => {
        setModel({ ...model, model_type: val })
        onInput(model.model_name, val)

        // Reset states when model_type changes
        setIsWebSearchEnabled(false)  // Reset web search toggle to false
        setMaxTokens('')  // Reset max tokens input
        // onConfig(null)
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
        onConfig({ enable_web_search: checked, max_tokens: maxTokens })
    }

    const handleVoiceChange = (e) => {
        const value = e.target.value
        setVoice(value)
        onConfig({ voice: value })
    }

    const handleMaxTokensChange = (e) => {
        const value = e.target.value
        setMaxTokens(value)

        if (value === '') {
            onConfig({ enable_web_search: isWebSearchEnabled })
        } else {
            onConfig({ enable_web_search: isWebSearchEnabled, max_tokens: parseInt(value, 10) })
        }
    }

    return (
        <div className="group w-full border rounded-sm p-4 mb-2">
            <div className="flex items-center justify-between">
                <span>{model.name.replace('model', t('model.model'))}</span>
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
                        />
                    </Label>
                    <Label className="bisheng-label"></Label>
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
                                <SelectItem value="llm">LLM</SelectItem>
                                <SelectItem value="embedding">Embedding</SelectItem>
                                <SelectItem value="rerank">Rerank</SelectItem>
                                <SelectItem value="tts">TTS</SelectItem>
                                <SelectItem value="stt">STT</SelectItem>
                            </SelectGroup>
                        </SelectContent>
                    </Select>
                </div>
                {model.model_type === 'tts' && (<div>
                    <Label className="bisheng-label">音色</Label>
                    <Input
                        value={voice}
                        onChange={handleVoiceChange}
                        className="h-8"
                    />
                </div>)}
                {model.model_type === 'llm' && (
                    <>
                        {['qwen', 'tencent', 'moonshot'].includes(type) && <div className="flex gap-2 items-center">
                            <Label className="bisheng-label">联网搜索</Label>
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


// 模型提供方枚举
export const modelProvider = [
    { "name": "OpenAI", "value": "openai" },
    { "name": "Azure OpenAI", "value": "azure_openai" },
    { "name": "Ollama", "value": "ollama" },
    { "name": "xinference", "value": "xinference" },
    { "name": "llamacpp", "value": "llamacpp" },
    { "name": "vllm", "value": "vllm" },
    { "name": "通义千问", "value": "qwen" },
    { "name": "DeepSeek", "value": "deepseek" },
    { "name": "硅基流动", "value": "silicon" },
    { "name": "火山引擎", "value": "volcengine" },
    { "name": "智谱 AI", "value": "zhipu" },
    { "name": "讯飞星火", "value": "spark" },
    { "name": "腾讯云", "value": "tencent" },
    { "name": "月之暗面", "value": "moonshot" },
    { "name": "百度千帆", "value": "qianfan" },
    { "name": "Minimax", "value": "minimax" },
    { "name": "Anthropic", "value": "anthropic" },
]
const bishengModelProvider = { "name": "bishengRT", "value": "bisheng_rt" }

// 默认表单项
const defaultForm = {
    type: '',
    name: '',
    limit_flag: false,
    limit: 1,
    config: {},
    models: []
}

export default function ModelConfig({ id, onGetName, onBack, onReload, onBerforSave, onAfterSave }) {
    // console.log(id) // id为-1说明是添加模型，否则是模型配置
    const { t } = useTranslation('model')

    const [formData, setFormData] = useState(id === -1 ? { ...defaultForm } : null)
    useEffect(() => {
        if (id === -1) return
        getLLmServerDetail(id).then(res => {
            setFormData(res)
        })
    }, [id])

    const getModelsByType = useSelectModel()
    const handleTypeChange = (val) => {
        const name = onGetName(_modelProvider.find(el => el.value === val).name || '')
        // 自动填充模型
        const models = getModelsByType(val)
        setFormData({ ...formData, type: val, name, models })
    }

    const handleAddModel = () => {
        // 找最大
        const maxIndex = formData.models.reduce((max, el, i) => el.name.match(/model (\d+)/) ? Math.max(max, +el.name.match(/model (\d+)/)[1]) : max, 0)

        const model = {
            id: generateUUID(4),
            name: `model ${maxIndex + 1}`,
            model_name: '',
            model_type: 'llm'
        }
        setFormData({ ...formData, models: [...formData.models, model] })
    }

    const handleDelete = (index) => {
        const models = formData.models.filter((el, i) => index !== i)
        setFormData({ ...formData, models })
    }

    const handleModelChange = (name, type, index) => {
        const models = formData.models.map((el, i) => index === i ? {
            ...el,
            config: type === 'llm' ? el.config : null,
            model_name: name,
            model_type: type
        } : el)
        setFormData({ ...formData, models })
        // 重复校验
        return formData.models.find((el, i) => index !== i && el.model_name === name)
    }

    const handleModelConfig = (config, index) => {
        const models = formData.models.map((el, i) => index === i ? {
            ...el,
            config
        } : el)
        setFormData({ ...formData, models })
    }

    // submit 1

    const { message, toast } = useToast()
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

            // 重复检验map
            const map = {}
            let repeat = false
            const error = formData.models.some(model => {
                if (map[model.model_name]) repeat = true
                map[model.model_name] = true
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

            if (id === -1) {
                await captureAndAlertRequestErrorHoc(addLLmServer({ ...formData, config }).then(res => {
                    // if (res.code === 10802) {
                    //     return toast({
                    //         variant: 'error',
                    //         description: res.msg
                    //     })
                    // }
                    onAfterSave(res.code === 10803 ? res.msg : t('model.addSuccess'))
                    onBack()
                }))
            } else {
                await captureAndAlertRequestErrorHoc(updateLLmServer({ ...formData, config }).then(res => {
                    onAfterSave(t('model.updateSuccess'))
                    onBack()
                }))
            }
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
                // 删除接口
                captureAndAlertRequestErrorHoc(deleteLLmServer(id).then(res => {
                    onAfterSave(t('model.deleteSuccess'))
                }))

                onBack()
                next()
            }
        })
    }

    const _modelProvider = useMemo(() => {
        // 编辑模式追加bisheng rt
        return id === -1 ? modelProvider : [...modelProvider, bishengModelProvider]
    }, [id])

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
                <Label className="bisheng-label">模型接口格式</Label>
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
                    <QuestionTooltip className="relative top-0.5 ml-1" content={t('model.serviceProviderNameTooltip')} />
                </Label>
                <Input value={formData.name} onChange={(e) => {
                    const name = e.target.value
                    setFormData({ ...formData, name })
                    document.getElementById('model_provider_name_error').style.display = !name || name.length > 100 ? 'block' : 'none'
                }}></Input>
                <span id="model_provider_name_error" style={{ display: 'none' }} className="text-red-500 text-xs">{
                    formData.name ? '最多 100 个字符' : '不可为空'
                }</span>
            </div>
            <CustomForm
                ref={formRef}
                showDefault={id === -1}
                provider={formData.type}
                formData={formData.config}
            />
            <div className={formData.type ? 'visible' : 'invisible'}>
                <div className="mb-2">
                    <div className="flex items-center gap-x-6">
                        <Label className="bisheng-label">{t('model.dailyCallLimit')}</Label>
                        <Switch checked={formData.limit_flag} onCheckedChange={(val) => setFormData(form => ({ ...form, limit_flag: val }))} />
                        <div className={`flex items-center gap-x-2 ${formData.limit_flag ? '' : 'invisible'}`}>
                            <Input type="number" value={formData.limit} onChange={(e) => setFormData({ ...formData, limit: Number(e.target.value) })}
                                className="w-24 h-8"
                            ></Input>
                            <span>{t('model.timesPerDay')}</span>
                        </div>
                    </div>
                </div>
                {/* 模型卡片 */}
                <div className="mb-2">
                    <Label className="bisheng-label">{t('model.model')}</Label>
                    <div className="w-[92%]">
                        {
                            formData.models.map((m, i) => <ModelItem
                                key={m.id}
                                data={m}
                                type={formData.type}
                                onInput={(name, type) => handleModelChange(name, type, i)}
                                onConfig={(config) => handleModelConfig(config, i)}
                                onDelete={() => handleDelete(i)}
                            />)
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
                {isLoading ? '模型状态检测中' : t('model.save')}
            </LoadButton>
        </div>
    </div>
}


const useSelectModel = () => {
    const modelsRef = useRef<any>(null)

    const loadData = async () => {
        try {
            const response = await fetch(__APP_ENV__.BASE_URL + '/models/data.json');
            if (!response.ok) {
                throw new Error('Failed to fetch data');
            }
            return await response.json();
        } catch (error) {
            console.error('Failed to load commitments:', error);
            return { title: '', commitments: [] }; // 返回默认的数据结构
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