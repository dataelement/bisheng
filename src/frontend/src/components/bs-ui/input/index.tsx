import * as React from "react"
import { cname } from "../utils"
import { SearchIcon } from "../../bs-icons/search"

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



export interface TextareaProps
    extends React.TextareaHTMLAttributes<HTMLTextAreaElement> { }

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
    ({ className, ...props }, ref) => {
        return (
            <textarea
                className={cname(
                    "flex min-h-[80px] w-full rounded-md border border-input bg-[#FAFBFC] px-3 py-2 text-sm text-[#111] shadow-sm resize-none placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
                    className
                )}
                ref={ref}
                {...props}
            />
        )
    }
)
Textarea.displayName = "Textarea"

export { Input, SearchInput, Textarea }
