import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button } from "@/components/bs-ui/button";
import { Input } from "@/components/bs-ui/input";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { Switch } from "@/components/bs-ui/switch";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import ShadTooltip from "@/components/ShadTooltipComponent";
import { PlusIcon } from "@radix-ui/react-icons";
import { ArrowLeft, Trash2Icon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import CustomForm from "./CustomForm";
import { addLLmServer, deleteLLmServer, getLLmServerDetail, updateLLmServer } from "@/controllers/API/finetune";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";

function ModelItem({ data, onDelete, onInput }) {
    const [model, setModel] = useState(data)
    const [error, setError] = useState('')

    const handleInput = (e) => {
        const value = e.target.value
        setModel({ ...model, model_name: value })
        const repeated = onInput(value, model.model_type)

        setError('')
        if (!value) setError('模型名称不可为空')
        if (value.length > 30) setError('最多三十个字符')
        if (repeated) setError('模型不可重复')
    }

    const handleSelectChange = (val) => {
        setModel({ ...model, model_type: val })
        onInput(model.model_name, val)
    }

    return <div className="w-full border rounded-sm p-4 mb-2">
        <div className="flex items-center justify-between">
            <span className="text-xl">{model.name}</span>
            <Trash2Icon onClick={onDelete} className="w-[20px] cursor-pointer text-gray-500 h-[20px]" />
        </div>
        <div className="space-y-2 mt-2">
            <div>
                <span>模型名称</span>
                <Input value={model.model_name} onChange={handleInput}></Input>
                {error && <span className="text-red-500 text-sm">{error}</span>}
            </div>
            <div>
                <span>模型类型</span>
                <Select value={model.model_type} onValueChange={handleSelectChange}>
                    <SelectTrigger>
                        <SelectValue placeholder="" />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectGroup>
                            <SelectItem value="llm">LLM</SelectItem>
                            <SelectItem value="embedding">Embedding</SelectItem>
                            <SelectItem value="rerank">Rerank</SelectItem>
                        </SelectGroup>
                    </SelectContent>
                </Select>
            </div>
        </div>
    </div>
}

// 模型提供方枚举
export const modelProvider = [
    { "name": "OPENAI", "value": "openai" },
    { "name": "AZURE_OPENAI", "value": "azure_openai" },
    { "name": "OLLAMA", "value": "ollama" },
    { "name": "XINFERENCE", "value": "xinference" },
    { "name": "LLAMACPP", "value": "llamacpp" },
    { "name": "VLLM", "value": "vllm" },
    { "name": "QWEN", "value": "qwen" },
    { "name": "QIAN_FAN", "value": "qianfan" },
    { "name": "ZHIPU", "value": "zhipu" },
    { "name": "MINIMAX", "value": "minimax" },
    { "name": "ANTHROPIC", "value": "anthropic" },
    { "name": "DEEPSEEK", "value": "deepseek" },
    { "name": "SPARK", "value": "spark" },
]

// 默认表单项
const defaultForm = {
    type: '',
    name: '',
    limit_flag: false,
    limit: 1,
    config: {},
    models: [{
        name: '模型 1',
        model_name: '',
        model_type: 'llm'
    }]
}

export default function ModelConfig({ id, onGetName, onBack, onReload, onBerforSave, onAfterSave }) {
    // console.log(id) // id为-1说明是添加模型，否则是模型配置
    const { t } = useTranslation()

    const [formData, setFormData] = useState(id === -1 ? { ...defaultForm } : null)
    useEffect(() => {
        if (id === -1) return
        getLLmServerDetail(id).then(res => {
            console.log('res :>> ', res);
            setFormData(res)
        })
    }, [id])

    const handleTypeChange = (val) => {
        const name = onGetName(val)
        setFormData({ ...formData, type: val, name })
    }

    const handleAddModel = () => {
        // 找最大
        const maxIndex = formData.models.reduce((max, el, i) => el.name.match(/模型 (\d+)/) ? Math.max(max, +el.name.match(/模型 (\d+)/)[1]) : max, 1)

        const model = {
            name: `模型 ${maxIndex + 1}`,
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
            model_name: name,
            model_type: type
        } : el)
        setFormData({ ...formData, models })
        // 重复校验
        return formData.models.find((el, i) => index !== i && el.model_name === name)
    }

    // submit 
    const { message, toast } = useToast()
    const formRef = useRef(null)
    const handleSave = () => {
        if (!formData.type) return
        const exists = onBerforSave(formData.id, formData.name)
        if (exists) {
            return message({
                variant: 'warning',
                description: '服务提供方名称重复，请修改'
            })
        }
        const [config, errorMsg] = formRef.current.getData();
        if (errorMsg) {
            return message({
                variant: 'warning',
                description: errorMsg
            })
        }

        // 重复检验map
        const map = {}
        let repeat = false
        const error = formData.models.some(model => {
            if (map[model.model_name]) repeat = true
            map[model.model_name] = true
            return !model.model_name || model.model_name.length > 30
        })
        if (error) {
            return message({
                variant: 'warning',
                description: '模型名称不可为空，且最多三十个字符'
            })
        }
        if (repeat) {
            return message({
                variant: 'warning',
                description: '模型不可重复'
            })
        }

        if (id === -1) {
            captureAndAlertRequestErrorHoc(addLLmServer({ ...formData, config }).then(res => {
                if (res.code === 10802) {
                    return toast({
                        variant: 'error',
                        description: res.msg
                    })
                }
                onAfterSave(res.code === 10803 ? res.msg : '添加成功')
                onBack()
            }))
        } else {
            captureAndAlertRequestErrorHoc(updateLLmServer({ ...formData, config }).then(res => {
                onAfterSave('修改成功')
                onBack()
            }))
        }
    }

    const handleModelDel = () => {
        bsConfirm({
            title: t('prompt'),
            desc: `删除正在使用的模型可能导致已有应用或知识库不可用，确认删除？`,
            onOk(next) {
                // 删除接口
                captureAndAlertRequestErrorHoc(deleteLLmServer(id).then(res => {
                    onAfterSave('删除成功')
                }))

                onBack()
                next()
            }
        })
    }

    if (!formData) return <div className="absolute left-0 top-0 z-10 flex h-full w-full items-center justify-center bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
        <span className="loading loading-infinity loading-lg"></span>
    </div>

    return <div className="w-full">
        <div className="flex ml-6 items-center gap-x-3">
            <ShadTooltip content={t('back')} side="right">
                <button className="extra-side-bar-buttons w-[36px]" onClick={() => onBack()}>
                    <ArrowLeft strokeWidth={1.5} className="side-bar-button-size" />
                </button>
            </ShadTooltip>
            <span>{id === -1 ? '添加模型' : '模型配置'}</span>
        </div>
        <div className="w-[50%] min-w-64 px-4 flex flex-col gap-y-2 m-auto mt-5 h-[79vh] overflow-y-auto">
            <div>
                <span>服务提供方</span>
                <Select value={formData.type} onValueChange={handleTypeChange}>
                    <SelectTrigger>
                        <SelectValue placeholder="" />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectGroup>
                            {modelProvider.map((model => <SelectItem key={model.value} value={model.value}>{model.name}</SelectItem>))}
                        </SelectGroup>
                    </SelectContent>
                </Select>
            </div>
            <div>
                <span>服务提供方名称</span>
                <Input value={formData.name} onChange={(e) => setFormData({ ...formData, name: e.target.value })}></Input>
            </div>
            <CustomForm
                ref={formRef}
                showDefault={id === -1}
                provider={formData.type}
                formData={formData.config}
            />
            <div className="mt-2">
                <div className="flex items-center gap-x-6">
                    <span>单日调用次数上限</span>
                    <Switch checked={formData.limit_flag} onCheckedChange={(val) => setFormData(form => ({ ...form, limit_flag: val }))} />
                    <div className={`flex items-center gap-x-2 ${formData.limit_flag ? '' : 'hidden'}`}>
                        <Input type="number" value={formData.limit} onChange={(e) => setFormData({ ...formData, limit: Number(e.target.value) })} className={`w-[100px]`}></Input>
                        <span>次/天</span>
                    </div>
                </div>
            </div>
            <div className="mt-2">
                <div className="mr-5">模型</div>
                <div className="w-[92%]">
                    {
                        formData.models.map((m, i) => <ModelItem data={m} onInput={(name, type) => handleModelChange(name, type, i)} key={m.name} onDelete={() => handleDelete(i)} />)
                    }
                    <div onClick={handleAddModel} className="border-[2px] hover:bg-gray-100 h-[40px] cursor-pointer mt-4 flex justify-center rounded-md">
                        <div className="flex justify-center items-center">
                            <PlusIcon className="size-6 text-blue-500" />
                            <span>添加模型</span>
                        </div>
                    </div>
                </div>
            </div>
            <div className="space-x-4 text-right">
                {id !== -1 && <Button variant="destructive" onClick={handleModelDel}>删除</Button>}
                <Button variant="outline" onClick={() => onBack()}>取消</Button>
                <Button onClick={handleSave}>保存</Button>
            </div>
        </div>
    </div >
}