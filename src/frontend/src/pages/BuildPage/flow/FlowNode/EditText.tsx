import { Input, Textarea } from "@/components/bs-ui/input"
import { useState } from "react"

export default function EditText({ type = 'input', children }) {
    const [edit, setEdit] = useState(false)

    return <div className="cursor-text">
        {edit ?
            type === 'input' ? <Input type="text" className="h-8" onBlur={() => setEdit(false)} /> : <Textarea onBlur={() => setEdit(false)} />
            : <div onClick={() => setEdit(true)}>{children}</div>}
    </div>
};
