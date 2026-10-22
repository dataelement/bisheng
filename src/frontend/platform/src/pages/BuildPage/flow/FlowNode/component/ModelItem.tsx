// @ts-strict-ignore
import { Label } from "@/components/bs-ui/label";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import { filterModelOption, toGroupedModelOptions, toModelSelectValue } from "@/components/bs-comp/formFields/modelOptions";
import { Select } from "@bisheng/ui";
import { getLlmDefaultModel } from "@/controllers/API/finetune";
import { useModel } from "@/pages/ModelPage/manage";
import { useEffect,useMemo,useState } from "react";
import { useTranslation } from "react-i18next";

export default function ModelItem({ agent = false, data, onChange, onValidate, i18nPrefix }) {
    const { t } = useTranslation('flow');

    const { llmOptions, isLoading } = useModel(agent ? 'assistant' : 'llm');
    const [modelId, setModelId] = useState(null); // set initial state as null

    useEffect(() => {
        if (llmOptions && llmOptions.length > 0 && agent && !data.value) {
            const id = String(llmOptions[0]?.children[0]?.value);
            setModelId(id);
            onChange(Number(id));
        } else if (!agent) {
            getLlmDefaultModel().then(res => {
                if (res && !data.value) {
                    const id = String(res.model_id);
                    setModelId(id);
                    onChange(Number(id));
                } else {
                    setModelId(String(data.value));
                }
            });
        } else {
            setModelId(String(data.value));
        }
    }, [llmOptions]);

    const selectLabels = useSelectLabels();
    const options = useMemo(() => toGroupedModelOptions(llmOptions), [llmOptions]);

    // A saved model that is no longer offered (deleted / offline) is cleared.
    useEffect(() => {
        if (modelId && options.length && !options.some(option => option.value === modelId)) onChange(null);
    }, [modelId, options]);

    const [error, setError] = useState(false);

    useEffect(() => {
        onValidate(() => {
            if (!data.value) {
                setError(true)
                return t(`${i18nPrefix}label`) + ' ' + t('required')
            }
            setError(false)
            return false
        })

        return () => onValidate(() => { });
    }, [data.value])

    return (
        <div className='node-item mb-4'>
            <Label className="flex items-center bisheng-label mb-2">
                {data.required && <span className="text-red-500">*</span>}
                {t(`${i18nPrefix}label`)}
            </Label>
            <Select
                {...selectLabels}
                className="nodrag w-full"
                status={error ? 'error' : 'default'}
                options={options}
                filterOption={filterModelOption}
                value={data.value ? String(data.value) : toModelSelectValue(modelId)}
                onChange={(v) => {
                    setModelId(v == null ? null : String(v));
                    onChange(v == null ? null : Number(v));
                }}
                placeholder={t(`${i18nPrefix}placeholder`)}
                aria-label={t(`${i18nPrefix}label`)}
            />
        </div>
    );
}
