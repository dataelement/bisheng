import { Listbox } from "@headlessui/react";
import { CheckIcon, ChevronsUpDown } from "lucide-react";
import { useEffect, useMemo } from "react";
import { cn } from "../../utils";

export default function Select({ value, options, onChange, className = '', multiple = false, error = false }) {

    useEffect(() => {
        if (multiple && !Array.isArray(value)) throw new Error('value must be an array')
    }, [value, multiple])

    const name = useMemo(() => {
        return (Array.isArray(value) ? value : [value]).map(el => {
            const option = options.find(op => op.value === el)
            return option?.label || el
        }).join(';')
    }, [value, options])

    return <Listbox
        multiple={multiple}
        value={value}
        onChange={onChange}
    // by={compareDepartments}
    >
        <div className={cn(`relative mt-1`, className)}>
            <Listbox.Button className={`relative w-full cursor-default rounded-lg bg-white py-2 pl-3 pr-10 text-left shadow-md focus:outline-none border sm:text-sm  h-[38px] ${error && 'border-red-400'}`}>
                <div className="block truncate">{name}</div>
                <span className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2">
                    <ChevronsUpDown />
                </span>
            </Listbox.Button>

            <Listbox.Options className="absolute mt-1 max-h-60 w-full overflow-auto rounded-md bg-white py-1 text-base shadow-lg ring-1 ring-black ring-opacity-5 focus:outline-none sm:text-sm">
                {options.map((option) => (
                    <Listbox.Option
                        key={option.value}
                        className={({ active }) =>
                            `relative cursor-default select-none py-2 pl-10 pr-4 ${active ? 'bg-blue-100 text-gray-700' : 'text-gray-900 bg-gray-50'
                            }`
                        }
                        value={option.value}
                    >
                        {({ selected }) => (
                            <>
                                <span className={`block truncate ${selected ? 'font-medium' : 'font-normal'}`} >
                                    {option.label}
                                </span>
                                {selected ? (
                                    <span className="absolute inset-y-0 left-0 flex items-center pl-3 text-blue-600">
                                        <CheckIcon className="h-5 w-5" aria-hidden="true" />
                                    </span>
                                ) : null}
                            </>
                        )}
                    </Listbox.Option>
                ))}
            </Listbox.Options>
        </div>
    </Listbox>
};
