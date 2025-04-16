import Cascader from "@/components/bs-ui/select/cascader";
import { getAssistantModelList, getModelListApi } from "@/controllers/API/finetune";
import { useEffect, useState } from "react";

export default function ModelSelect({ type = 'assistant', modelType = 'llm', value, onChange }) {

    // const [configServers, setConfigServers] = useState([])
    const [loading, setLoading] = useState(true)
    const [modelValue, setModelValue] = useState(null)
    const [options, setOptions] = useState([])

    const loadModels = async () => {
        // const data = await getAssistantModelsApi()
        // setConfigServers(data)
        setLoading(true)
        const data = await (type === 'assistant' ? getAssistantModelList() : getModelListApi())

        let _value = []
        let _options = []
        data.forEach(server => {
            const serverItem = { value: server.id, label: server.name, children: [] }
            serverItem.children = server.models.reduce((res, model) => {
                if (model.id === value) {
                    _value = [{ ...serverItem }, { value: model.id, label: model.model_name }]
                }
                return model.online && model.model_type === modelType ? [...res, {
                    value: model.id,
                    label: model.model_name
                }] : res
            }, [])
            if (serverItem.children.length) _options.push(serverItem)
        });
        setModelValue(_value)
        setOptions(_options)
        setLoading(false)

        if (!_value.length) onChange(null)
    }

    useEffect(() => {
        loadModels()
    }, [value])
    if (loading) return null
    return <Cascader
        selectPlaceholder="选择一个模型"
        defaultValue={modelValue}
        options={options}
        onChange={(val) => onChange(val[1])}
    />
};
