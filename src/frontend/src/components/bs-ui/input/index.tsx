import * as React from "react"
import { cname } from "../utils"
import { SearchIcon } from "../../bs-icons/search"
import { MinusCircleIcon } from "lucide-react"
import { generateUUID } from "../utils"
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


const SearchInput = React.forwardRef<HTMLInputElement, InputProps & { inputClassName?: string, iconClassName?: string }>(
    ({ className, inputClassName, iconClassName, ...props }, ref) => {
        return <div className={cname("relative", className)}>
            <SearchIcon className={cname("h-5 w-5 absolute left-2 top-2", iconClassName)} />
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
        const [values, setValues] = React.useState<{ id: string; value: string }[]>(
            defaultValue && defaultValue.length > 0
                ? defaultValue.map((value) => ({ id: generateUUID(8), value }))
                : [{ id: generateUUID(8), value: '' }]
        )
        // input change
        const handleChange = (value, id, index) => {
            let newValues = null
            // push
            if (index === values.length - 1) {
                newValues = [...values, {id:generateUUID(8),value:''}]
            }
            newValues = (newValues || values).map((item) =>  item.id === id ? {id:id,value:value} : item)
            setValues(newValues)
            props.onChange?.(newValues.map((item)=>item.value))
        }

        // delete input
        const handleDel = (id) => {
            setValues(values.filter((item) =>  item.id !== id))
        }

        return <div className={cname('', className)}>
            {
                values.map((item,index) => (
                    <div className="relative mt-2">
                        <Input
                            key={item.id}
                            defaultValue={item.value}
                            className={cname('pr-8', inputClassName)}
                            placeholder={props.placeholder || ''}
                            onChange={(e) => handleChange(e.target.value, item.id, index)}
                        ></Input>
                        {index !== values.length - 1 && <MinusCircleIcon onClick={() => handleDel(item.id)} size={18} className="absolute top-2 right-2 text-gray-500 hover:text-gray-700 cursor-pointer" />}
                    </div>
                ))
            }
        </div>
    }
)

export { Input, SearchInput, Textarea, InputList }
