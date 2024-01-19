import { PenLine } from "lucide-react";
import { useRef, useState } from "react";

export default function EditLabel({ str, children, onChange }) {
    const [value, setValue] = useState(str)

    const [edit, setEdit] = useState(false)
    const inputRef = useRef(str)

    if (edit) return <div className="">
        <input
            type="text"
            ref={inputRef}
            defaultValue={str}
            onKeyDown={(e) => {
                e.key === 'Enter' && (setEdit(false), onChange(inputRef.current.value));
                e.code === 'Space' && e.preventDefault();
            }}
            className="flex h-6 w-full rounded-xl border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
        />
    </div>


    return <div className="flex items-center text-gray-900 dark:text-gray-300 group">
        {children(inputRef.current.value || str)}
        <button
            className="hidden transition-all group-hover:block"
            // title={t('flow.editAlias')}
            onClick={() => setEdit(true)}
        >
            <PenLine size={18} className="ml-2 cursor-pointer" />
        </button>
    </div >
};
