import { Label } from "@/components/bs-ui/label";
import Cascader from "@/components/bs-ui/select/cascader";
import { getLlmDefaultModel } from "@/controllers/API/finetune";
import { useModel } from "@/pages/ModelPage/manage";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

export default function ModelItem({ agent = false, data, onChange, onValidate }) {
    const { t } = useTranslation()

    const { llmOptions, isLoading } = useModel(agent ? 'assistant' : 'llm')
    const [modelId, setModelId] = useState('')

    useEffect(() => {
        if (llmOptions && llmOptions.length > 0 && agent && !data.value) {
            const id = String(llmOptions[0]?.children[0]?.value)
            setModelId(id)
                    onChange(Number(id))
                    // onChange(id)
        } else if (!agent) {
            getLlmDefaultModel().then(res => {
                if (res && !data.value) {
                    const id = String(res.model_id)
                    setModelId(id)
                    onChange(Number(id))
                }
            })
        } else {
            setModelId(data.value)
        }
    }, [llmOptions])


    const defaultValue = useMemo(() => {
        let _defaultValue = []
        if (!modelId) return _defaultValue
        llmOptions.some(option => {
            const model = option.children.find(el => String(el.value) === modelId)
            if (model) {
                _defaultValue = [{ value: option.value, label: option.label }, { value: model.value, label: model.label }]
                return true
            } else {
                // const firstOp = options[0]
                // _defaultValue = [{ value: firstOp.value, label: firstOp.label }, { value: firstOp.children[0].value, label: firstOp.children[0].label }]
            }
        })
        // 无对应选项自动清空旧值
        if (_defaultValue.length === 0) onChange(null)
        return _defaultValue
    }, [modelId, llmOptions])

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
        <Cascader
            key={modelId}
            error={error}
            placholder={data.placeholder}
            defaultValue={defaultValue}
            options={llmOptions}
            onChange={(val) => onChange(Number(val[1]))}
        />
    </div>
};