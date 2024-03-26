import * as React from "react"
import { cname } from "../utils"
import { SearchIcon } from "../../bs-icons/search"
import { MinusCircleIcon } from "lucide-react"

export interface InputProps
    extends React.InputHTMLAttributes<HTMLInputElement> { }

const Input = React.forwardRef<HTMLInputElement, InputProps>(
    ({ className, type, ...props }, ref) => {
        return (
            <input
                type={type}
                className={cname(
                    "flex h-9 w-full rounded-md border border-input bg-[#FAFBFC] px-3 py-1 text-sm text-[#111] shadow-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
                    className
                )}
                ref={ref}
                {...props}
            />
        )
    }
)
Input.displayName = "Input"


const SearchInput = React.forwardRef<HTMLInputElement, InputProps & { inputClassName?: string }>(
    ({ className, inputClassName, ...props }, ref) => {
        return <div className={cname("relative", className)}>
            <SearchIcon className="h-5 w-5 absolute left-2 top-2" />
            <Input type="text" ref={ref} className={cname("pl-8", inputClassName)} {...props}></Input>
        </div>
    }
)

SearchInput.displayName = "SearchInput"



/**
 * 多行文本
 */
export interface TextareaProps
    extends React.TextareaHTMLAttributes<HTMLTextAreaElement> { }

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
    ({ className, ...props }, ref) => {
        return (
            <textarea
                className={cname(
                    "flex min-h-[80px] w-full rounded-md border border-input bg-[#FAFBFC] px-3 py-2 text-sm text-[#111] shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
                    className
                )}
                ref={ref}
                {...props}
            />
        )
    }
)
Textarea.displayName = "Textarea"


/**
 * input list
 */
const InputList = React.forwardRef<HTMLDivElement, InputProps & {
    inputClassName?: string,
    defaultValue?: string[],
    onChange?: (values: string[]) => void
}>(
    ({ className, inputClassName, defaultValue, ...props }, ref) => {
        // TODO key
        const [values, setValues] = React.useState<string[]>(defaultValue && defaultValue.length > 0 ? defaultValue : [''])

        // input change
        const handleChange = (value, index) => {
            let newValues = null
            // push
            if (index === values.length - 1) {
                newValues = [...values, '']
            }
            newValues = (newValues || values).map((v, i) => i === index ? value : v)
            setValues(newValues)
            props.onChange?.(newValues)
        }

        // delete input
        const handleDel = (index) => {
            setValues(values.filter((_, i) => i !== index))
        }

        return <div className={cname('', className)}>
            {
                values.map((value, index) => (
                    <div className="relative mt-2">
                        <Input
                            key={index}
                            defaultValue={value}
                            className={cname('pr-8', inputClassName)}
                            placeholder={props.placeholder || ''}
                            onChange={(e) => handleChange(e.target.value, index)}
                        ></Input>
                        {index !== values.length - 1 && <MinusCircleIcon onClick={() => handleDel(index)} size={18} className="absolute top-2 right-2 text-gray-500 hover:text-gray-700 cursor-pointer" />}
                    </div>
                ))
            }
        </div>
    }
)

export { Input, SearchInput, Textarea, InputList }
