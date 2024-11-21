import { Input, Textarea } from "@/components/bs-ui/input";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { cname } from "@/components/bs-ui/utils";
import { useState } from "react";

export default function EditText({ type = 'input', children, disable = false, defaultValue, maxLength = 0, className = '', onChange }) {
    const [edit, setEdit] = useState(false)
    const [value, setValue] = useState(defaultValue)

    const { message } = useToast()

    const handleChange = (e) => {
        const nval = e.target.value
        setValue(nval)
    }

    const handleBlur = () => {
        if (maxLength && value.length > maxLength) {
            return message({
                variant: 'warning',
                description: `不能超过 ${maxLength} 个字符`
            })
        }
        setEdit(false)
        if (!value) {
            // Restore default if empty
            setValue(defaultValue)
            return onChange(defaultValue)
        }
        onChange(value)
    }

    if (disable) return children

    return <div className="cursor-text">
        {edit ?
            type === 'input' ? <Input
                type="text"
                className={cname("h-6", className)}
                autoFocus={edit}
                value={value}
                onBlur={handleBlur}
                onChange={handleChange}
            /> : <Textarea
                className={className}
                autoFocus={edit}
                value={value}
                onBlur={handleBlur}
                onChange={handleChange}
            />
            : <div onClick={() => setEdit(true)}>{children}</div>}
    </div>
};
