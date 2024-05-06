import { useState } from "react"
import { Input } from "."

export default function TextInput({
    type = 'doubleclick',
    value,
    onChange = (val) => { },
    onSave = (val) => { },
    ...props }) {

    const [edit, setEdit] = useState(false)

    if (edit) return <Input defaultValue={value} {...props}
        onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                onSave(event.target.value)
                setEdit(false)
            }
        }}
        onBlur={e => {
            onSave(e.target.value)
            setEdit(false)
        }}
        onChange={onChange}
    ></Input>

    return <p
        className="text-sm px-3 py-1 border border-transparent w-full overflow-hidden text-ellipsis"
        onDoubleClick={() => setEdit(true)} onMouseOver={() => type === 'hover' && setEdit(true)}>{value}</p>
};
