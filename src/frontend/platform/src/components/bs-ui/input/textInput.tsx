// @ts-strict-ignore
import { Input } from '@bisheng/ui';
import { showApiError } from "@/controllers/request"
import { useRef, useState } from "react"


export default function TextInput({
    type = 'doubleclick',
    value,
    disabled = false,
    onChange = (val) => { },
    onSave = (val) => { },
    ...props }) {

    const [edit, setEdit] = useState(false)
    const [saving, setSaving] = useState(false)
    const savingRef = useRef(false)
    const handleSave = async (nextValue: string) => {
        if (savingRef.current) return
        savingRef.current = true
        setSaving(true)
        try {
            await onSave(nextValue)
            setEdit(false)
        } catch (error) {
            showApiError(error)
        } finally {
            savingRef.current = false
            setSaving(false)
        }
    }

    if (edit) return <Input defaultValue={value} {...props} disabled={saving} onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void handleSave(event.target.value)
            }
        }} onBlur={e => {
            void handleSave(e.target.value)
        }} onMouseLeave={event => { if (!savingRef.current && event.currentTarget.value === value) setEdit(false) }} onChange={onChange}></Input>

    if (disabled) return <p className="text-sm px-3 py-1 border border-transparent w-full overflow-hidden text-ellipsis truncate">{value}</p>

    return <p
        className="text-sm px-3 py-1 border border-transparent w-full overflow-hidden text-ellipsis truncate"
        onDoubleClick={() => setEdit(true)} onMouseOver={() => type === 'hover' && setEdit(true)}>{value}</p>
};
