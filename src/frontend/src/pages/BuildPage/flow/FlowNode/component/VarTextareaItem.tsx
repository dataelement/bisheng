import { Label } from "@/components/bs-ui/label";
import { useEffect, useState } from "react";
import VarInput from "./VarInput";

export default function VarTextareaItem({ nodeId, data, onChange, onValidate, onVarEvent }) {
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

    return (
        <div className='node-item mb-4 nodrag' data-key={data.key}>
            <Label className='bisheng-label'>
                {data.required && <span className="text-red-500">*</span>}
                {data.label}
            </Label>
            <VarInput
                itemKey={data.key}
                nodeId={nodeId}
                flowNode={data}
                placeholder={data.placeholder}
                error={error}
                value={data.value}
                onChange={onChange}
                onVarEvent={onVarEvent}
            >
            </VarInput>
            <p className="text-xs text-primary/60">{data.desc}</p>
        </div>
    );
}
