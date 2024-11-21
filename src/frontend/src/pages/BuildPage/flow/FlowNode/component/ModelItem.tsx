import { Label } from "@/components/bs-ui/label";
import Cascader from "@/components/bs-ui/select/cascader";
import { getModelListApi } from "@/controllers/API/finetune";
import { useEffect, useMemo, useState } from "react";

export default function ModelItem({ data, onChange, onValidate }) {
    const [options, setOptions] = useState<any[]>([])

    useEffect(() => {
        getModelListApi().then(res => {
            let llmOptions = []
            let embeddings = []
            res.forEach(server => {
                const serverEmbItem = { value: server.id, label: server.name, children: [] }
                const serverLlmItem = { value: server.id, label: server.name, children: [] }
                server.models.forEach(model => {
                    const item = {
                        value: model.id,
                        label: model.model_name
                    }
                    if (!model.online) return

                    model.model_type === 'embedding' ?
                        serverEmbItem.children.push(item) : serverLlmItem.children.push(item)
                })

                if (serverLlmItem.children.length) llmOptions.push(serverLlmItem)
                if (serverEmbItem.children.length) embeddings.push(serverEmbItem)
            });

            setOptions(llmOptions)
            // return { llmOptions, embeddings }
        })
    }, [])

    const defaultValue = useMemo(() => {
        if (!options.length) return ''
        let _defaultValue = []
        if (!data.value) return _defaultValue
        options.some(option => {
            const model = option.children.find(el => el.value === data.value)
            if (model) {
                _defaultValue = [{ value: option.value, label: option.label }, { value: model.value, label: model.label }]
                return true
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
                return data.label + '不可为空'
            }
            setError(false)
            return false
        })

        return () => onValidate(() => {})
    }, [data.value])

    return <div className='node-item mb-4'>
        <Label className="flex items-center bisheng-label mb-2">{data.label}</Label>
        {defaultValue ? <Cascader
            error={error}
            defaultValue={defaultValue}
            options={options}
            onChange={(val) => onChange(val[1])}
        /> : null}
    </div>
};
