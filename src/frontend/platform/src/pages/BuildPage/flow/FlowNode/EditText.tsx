import { Input, Textarea, toast } from '@bisheng/ui';


import { cname } from "@/components/bs-ui/utils";
import { useState } from "react";
import { useTranslation } from "react-i18next";

export default function EditText({ type = 'input', reDefaultValue = false, children, disable = false, defaultValue, maxLength = 0, className = '', onChange }) {
    const [edit, setEdit] = useState(false)
    const [value, setValue] = useState(defaultValue)
    const { t } = useTranslation('flow')



    const handleChange = (e) => {
        const nval = e.target.value
        setValue(nval)
    }

    const handleBlur = () => {
        if (maxLength && value.length > maxLength) {
            return toast.show({ type: 'warning', message: String(t('cannotExceedMaxLength', { maxLength }) ?? '') })
        }
        setEdit(false)
        if (reDefaultValue && !value.trim()) {
            // Restore default if empty
            setValue(defaultValue)
            return onChange(defaultValue)
        }
        onChange(value)
    }

    if (disable) return children

    return <div className="cursor-text">
        {edit ?
            type === 'input' ? <Input type="text" autoFocus={edit} value={value} onBlur={handleBlur} onChange={handleChange} onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        handleBlur();
                    }
                }} className={cname("h-6", className)} /> : <Textarea autoFocus={edit} value={value} onBlur={handleBlur} onChange={handleChange} onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        handleBlur();
                    }
                }} textareaClassName={className} />
            : <div onClick={() => setEdit(true)}>{children}</div>}
    </div>
};
