import Cascader from "@/components/bs-ui/select/cascader";
import { useModel } from "@/pages/ModelPage/manage";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

export default function ModelSelect({ type = 'assistant', modelType = 'llm', value, onChange }) {
    const { t } = useTranslation();

    const { llmOptions, embeddings, isLoading } = useModel(type === 'assistant' ? type : 'llm')

    const defaultValue = useMemo(() => {
        let _defaultValue = []
        const options = modelType === 'llm' ? llmOptions : embeddings
        if (!value || !options || options.length === 0) return _defaultValue

        options.forEach(option => {
            const model = option.children?.find(el => el.value == value)
            if (model) {
                _defaultValue = [
                    { value: option.value, label: option.label },
                    { value: model.value, label: model.label }
                ]
                return true
            }
            return false
        })
        return _defaultValue
    }, [value, llmOptions, embeddings])


    if (isLoading) return null
    return <Cascader
        selectPlaceholder={t('build.selectModel')}
        defaultValue={defaultValue}
        options={modelType === 'llm' ? llmOptions : embeddings}
        onChange={(val) => onChange(val[1])}
    />
};
