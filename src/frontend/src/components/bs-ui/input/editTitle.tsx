import { PenLine } from "lucide-react";
import { useRef, useState } from "react";
import { Input } from ".";
import { useToast } from "../toast/use-toast";

export default function EditTitle({ str, rule = [], className = '', children, onChange }) {
    const [edit, setEdit] = useState(false)
    const inputRef = useRef(null)

    const { toast } = useToast()

    const handleChange = () => {
        const value = inputRef.current.value
        if (rule.length) {
            const errors = []
            rule.forEach(r => {
                if (r.pattern) {
                    if (!r.pattern.test(value)) {
                        errors.push(r.message)
                    }
                }
                if (r.validator) {
                    if (!r.validator(value)) {
                        errors.push(r.message)
                    }
                }
            })

            if (errors.length) return toast({
                title: "",
                variant: "error",
                description: errors,
            })
        }
        setEdit(false)
        onChange(value)
    }

    if (edit) return <div className="">
        <Input
            type="text"
            ref={inputRef}
            defaultValue={str}
            onKeyDown={(e) => {
                e.key === 'Enter' && handleChange();
                e.code === 'Space' && e.preventDefault();
            }}
            onBlur={handleChange}
            className="h-6"
        />
    </div>


    return <div className="flex items-center text-gray-900 dark:text-gray-300 group">
        {children(inputRef.current?.value || str)}
        <button
            className="hidden transition-all group-hover:block"
            // title={t('flow.editAlias')}
            onClick={() => setEdit(true)}
        >
            <PenLine size={18} className={"size-3.5 ml-2 cursor-pointer " + className} />
        </button>
    </div >
};
