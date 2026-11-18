// @ts-strict-ignore
import { Label } from "@/components/bs-ui/label";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import { filterModelOption, toGroupedModelOptions, toModelSelectValue } from "@/components/bs-comp/formFields/modelOptions";
import { Select } from "@bisheng/ui";
import { showApiError } from "@/controllers/request";
import { getLlmDefaultModel } from "@/controllers/API/finetune";
import { useModel } from "@/pages/ModelPage/manage";
import { useEffect,useMemo,useState,useRef } from "react";
import { useTranslation } from "react-i18next";

export default function ModelItem({ agent = false, data, onChange, onValidate, i18nPrefix }) {
    const { t } = useTranslation('flow');

    const { llmOptions, isLoading } = useModel(agent ? 'assistant' : 'llm');
    const latestValue = useRef(data.value);
    latestValue.current = data.value;
    const [modelId, setModelId] = useState(null); // set initial state as null

    useEffect(() => {
        let active = true;
        const empty = data.value == null || data.value === '';
        if (llmOptions && llmOptions.length > 0 && agent && empty) {
            const id = String(llmOptions[0]?.children[0]?.value);
            setModelId(id);
            onChange(Number(id));
        } else if (!agent) {
            getLlmDefaultModel().then(res => {
                if (!active) return;
                if (res && (latestValue.current == null || latestValue.current === '')) {
                    const id = String(res.model_id);
                    setModelId(id);
                    onChange(Number(id));
                } else {
                    setModelId(String(data.value));
                }
            }).catch(error => { if (active) showApiError(error); });
        } else {
            setModelId(String(data.value));
        }
        return () => { active = false; };
    }, [llmOptions, data.value]);

    const selectLabels = useSelectLabels();
    const options = useMemo(() => toGroupedModelOptions(llmOptions, data.value, t('references.unavailable', { ns: 'bs' })), [llmOptions, data.value, t]);

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
