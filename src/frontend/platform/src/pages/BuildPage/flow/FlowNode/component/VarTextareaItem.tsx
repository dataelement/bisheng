import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import VarInput from "./VarInput";

export default function VarTextareaItem({ nodeId, data, onChange, onValidate, onVarEvent, i18nPrefix }) {
    const [error, setError] = useState(false)
    const { t } = useTranslation('flow')

    useEffect(() => {
        data.required && onValidate(() => {
            if (!data.value.trim()) {
                setError(true)
                return data.label + ' ' + t('required')
            }
            setError(false)
            return false
        })
        return () => onValidate(() => { })
    }, [data.value])

    return (
        <div className='node-item mb-4 max-w-2xl nodrag' data-key={data.key}>
            {/* <Label className='bisheng-label'>
                {data.required && <span className="text-red-500">*</span>}
                {data.label}
            </Label> */}
            <VarInput
                itemKey={data.key}
                nodeId={nodeId}
                paramItem={data}
                label={t(`${i18nPrefix}label`)}
                placeholder={data.placeholder && t(`${i18nPrefix}placeholder`)}
                error={error}
                value={data.value}
                onChange={onChange}
                onVarEvent={onVarEvent}
            >
            </VarInput>
            <p className="bisheng-label text-xs">{data.desc}</p>
        </div>
    );
}
