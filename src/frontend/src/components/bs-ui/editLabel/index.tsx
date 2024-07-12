import { PenLine } from "lucide-react";
import { useContext, useRef, useState } from "react";
import { alertContext } from "../../../contexts/alertContext";

export default function EditLabel({ str, rule, children, onChange }) {
    const [edit, setEdit] = useState(false)
    const inputRef = useRef(null)

    const { setErrorData } = useContext(alertContext);

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

            if (errors.length) return setErrorData({
                title: "",
                list: errors,
            });
        }
        setEdit(false)
        onChange(value)
    }

    if (edit) return <div className="">
        <input
            type="text"
            ref={inputRef}
            defaultValue={str}
            onKeyDown={(e) => {
                e.key === 'Enter' && handleChange();
                e.code === 'Space' && e.preventDefault();
            }}
            onBlur={handleChange}
            className="flex h-6 w-full rounded-xl border border-input bg-search-input px-3 py-1 text-sm shadow-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
        />
    </div>


    return <div className="flex items-center text-gray-900 dark:text-gray-300 group">
        {children(inputRef.current?.value || str)}
        <button
            className="hidden transition-all group-hover:block"
            // title={t('flow.editAlias')}
            onClick={() => setEdit(true)}
        >
            <PenLine size={18} className="ml-2 cursor-pointer" />
        </button>
    </div >
};
