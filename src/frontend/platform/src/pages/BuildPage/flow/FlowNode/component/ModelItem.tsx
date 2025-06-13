import { Label } from "@/components/bs-ui/label";
import Cascader from "@/components/bs-ui/select/cascader";
import { getAssistantModelList, getLlmDefaultModel, getModelListApi, getVoiceDefaultModel } from "@/controllers/API/finetune";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

export default function ModelItem({ agent = false, data, onChange, onValidate, type }: {agent?: boolean, data: any, onChange: any, onValidate: any, type?: string}) {
    const [options, setOptions] = useState<any[]>([])
    const { t } = useTranslation()

    useEffect(() => {
        const isVoiceLlm = ['tts', 'stt'].includes(type);
        (agent ? getAssistantModelList() : getModelListApi()).then(res => {
            let llmOptions = []
            let voiceOptions = []
            let embeddings = []
            res.forEach(server => {
                const serverEmbItem = { value: server.id, label: server.name, children: [] }
                const serverLlmItem = { value: server.id, label: server.name, children: [] }
                const serverVoiceItem = { value: server.id, label: server.name, children: [] }
                server.models.forEach(model => {
                    const item = {
                        value: model.id,
                        label: model.model_name
                    }
                    if (!model.online) return
                    if (model.model_type === 'embedding') {
                        serverEmbItem.children.push(item);
                    } else if (model.model_type === type) {
                        serverVoiceItem.children.push(item);
                    } else {
                        serverLlmItem.children.push(item);
                    }
                    // model.model_type === 'embedding' ?
                    //     serverEmbItem.children.push(item) : serverLlmItem.children.push(item)
                })
                if (serverLlmItem.children.length) llmOptions.push(serverLlmItem)
                if (serverEmbItem.children.length) embeddings.push(serverEmbItem)
                if (serverVoiceItem.children.length) voiceOptions.push(serverVoiceItem)
            });
            setOptions(isVoiceLlm ? voiceOptions : llmOptions);
            agent && !data.value && onChange(llmOptions[0].children[0].value)

            setLoading(false)
            // return { llmOptions, embeddings }
        })
        if (agent) return;
        // 更新默认值
        // 请求默认语音模型
        if (isVoiceLlm) {
            getVoiceDefaultModel().then(res => {
                res && !data.value && onChange(type === 'stt' ? res.stt_model_id : res.tts_model_id)
            })
        } else {
            getLlmDefaultModel().then(res => {
                res && !data.value && onChange(res.model_id)
            })
        }
    }, [])


    const [loading, setLoading] = useState(true)
    const defaultValue = useMemo(() => {
        if (!options.length) return []
        let _defaultValue = []
        if (!data.value) return _defaultValue
        options.some(option => {
            const model = option.children.find(el => el.value === data.value)
            if (model) {
                _defaultValue = [{ value: option.value, label: option.label }, { value: model.value, label: model.label }]
                return true
            } else {
                const firstOp = options[0]
                _defaultValue = [{ value: firstOp.value, label: firstOp.label }, { value: firstOp.children[0].value, label: firstOp.children[0].label }]
            }
        })
        // 无对应选项自动清空旧值
        if (_defaultValue.length === 0) onChange(null)
        return _defaultValue
    }, [data.value, options])

    const [error, setError] = useState(false)
    useEffect(() => {
        data.required && onValidate(() => {
            if (!data.value) {
                setError(true)
                return data.label + ' ' + t('required')
            }
            setError(false)
            return false
        })

        return () => onValidate(() => { })
    }, [data.value])

    return <div className='node-item mb-4'>
        <Label className="flex items-center bisheng-label mb-2">
            {data.required && <span className="text-red-500">*</span>}
            {data.label}
        </Label>
        {!loading ? <Cascader
            error={error}
            placholder={data.placeholder}
            defaultValue={defaultValue}
            options={options}
            onChange={(val) => onChange(val[1])}
        /> : null}
    </div>
};