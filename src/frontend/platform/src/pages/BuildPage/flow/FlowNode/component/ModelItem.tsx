import { Label } from "@/components/bs-ui/label";
import Cascader from "@/components/bs-ui/select/cascader";
import { getLlmDefaultModel } from "@/controllers/API/finetune";
import { useModel } from "@/pages/ModelPage/manage";
import { useEffect, useMemo, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";

export default function ModelItem({ agent = false, data, onChange, onValidate }) {
    const { t } = useTranslation();

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

    const defaultValue = useMemo(() => {
        if (!modelId || !llmOptions || llmOptions.length === 0) return [];

        let _defaultValue = [];
        llmOptions.some(option => {
            const model = option.children.find(el => String(el.value) === modelId);
            if (model) {
                _defaultValue = [{ value: option.value, label: option.label }, { value: model.value, label: model.label }];
                return true;
            }
            return false;
        });

        if (_defaultValue.length === 0) {
            onChange(null); // handle missing model gracefully
        }

        return _defaultValue;
    }, [modelId, llmOptions]);

    const [error, setError] = useState(false);

    useEffect(() => {
        onValidate(() => {
            if (!data.value) {
                setError(true)
                return data.label + ' ' + t('required')
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
                {data.label}
            </Label>
            <Cascader
                error={error}
                placeholder={data.placeholder}
                defaultValue={defaultValue}
                options={llmOptions}
                onChange={(val) => onChange(Number(val[1]))}
            />
        </div>
    );
}
