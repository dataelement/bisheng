// @ts-strict-ignore
import { filterModelOption, toGroupedModelOptions, toModelSelectValue } from "@/components/bs-comp/formFields/modelOptions";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import { useModel } from "@/pages/ModelPage/manage";
import { Select } from "@bisheng/ui";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

export default function ModelSelect({ type = 'assistant', modelType = 'llm', value, onChange }) {
    const { t } = useTranslation();
    const selectLabels = useSelectLabels();

    const { llmOptions, embeddings, isLoading } = useModel(type === 'assistant' ? type : 'llm')
    const options = useMemo(
        () => toGroupedModelOptions(modelType === 'llm' ? llmOptions : embeddings),
        [modelType, llmOptions, embeddings],
    )

    if (isLoading) return null
    return <Select
        {...selectLabels}
        className="w-full"
        options={options}
        filterOption={filterModelOption}
        value={toModelSelectValue(value)}
        onChange={(v) => onChange(v == null ? null : String(v))}
        placeholder={t('build.selectModel')}
        aria-label={t('build.selectModel')}
    />
};
