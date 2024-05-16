import { CheckIcon, Cross1Icon } from "@radix-ui/react-icons"
import React, { useEffect, useRef } from "react"
import { Select, SelectContent, SelectItem, SelectTrigger } from "."
import { Badge } from "../badge"
import { SearchInput } from "../input"

const MultiItem = ({ active, children, value, onClick }) => {

    return <div key={value}
        className={`relative flex w-full cursor-default select-none items-center rounded-sm py-1.5 pl-2 pr-8 mb-1 text-sm outline-none hover:bg-[#EBF0FF] hover:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50 break-all 
    ${active && 'bg-[#EBF0FF]'}`}
        onClick={() => { onClick(value) }}
    >
        <span className="absolute right-2 flex h-3.5 w-3.5 items-center justify-center">
            {active && <CheckIcon className="h-4 w-4"></CheckIcon>}
        </span>
        {children}
    </div>
}


interface IProps {
    className?: string,
    options: { label: string, value: string }[],
    value?: string[],
    defaultValue?: string[],
    children?: React.ReactNode,
    placeholder?: string,
    searchPlaceholder?: string,
    lockedValues?: string[],
    onChange?: (value: string[]) => void
}
// 临时用 andt 设计方案封装组件
const MultiSelect = ({
    className,
    value = [],
    defaultValue = [],
    options = [],
    children = null,
    placeholder = '',
    searchPlaceholder = '',
    lockedValues = [],
    onChange, ...props
}: IProps) => {

    const [values, setValues] = React.useState(defaultValue)
    const [optionFilter, setOptionFilter] = React.useState(options)


    const inputRef = useRef(null)

    useEffect(() => {
        setValues(value)
    }, [value])

    useEffect(() => {
        setOptionFilter(options)
        if (inputRef.current) {
            inputRef.current.value = ''
        }
    }, [options])
    // delete
    const handleDelete = (value: string) => {
        const newValues = values.filter((item) => {
            return item !== value
        })
        setValues(newValues)
        onChange?.(newValues)
    }
    // add
    const handleSwitch = (value: string) => {
        if (lockedValues.includes(value)) {
            return
        }
        if (values.includes(value)) {
            const newValues = values.filter((item) => {
                return item !== value
            })
            setValues(newValues)
            onChange?.(newValues)
        } else {
            const _newValues = [...values, value]
            setValues(_newValues)
            onChange?.(_newValues)
        }
    }

    // search
    const handleSearch = (e) => {
        const newValues = options.filter((item) => {
            return item.label.toLowerCase().indexOf(e.target.value.toLowerCase()) !== -1
        })
        setOptionFilter(newValues)
    }
    return <Select {...props} required onOpenChange={(e) => !e && setOptionFilter(options)}>
        <SelectTrigger className="mt-2 h-auto">
            {
                values.length
                    ? <div className="flex flex-wrap">
                        {
                            options.filter(option => values.includes(option.value)).map(option =>
                                <Badge onPointerDown={(e) => e.stopPropagation()} key={option.value} className="flex whitespace-normal items-center gap-1 select-none bg-primary/20 text-primary hover:bg-primary/15 m-[2px]">
                                    {option.label}
                                    {lockedValues.includes(option.value) || <Cross1Icon className="h-3 w-3" onClick={() => handleDelete(option.value)}></Cross1Icon>}
                                </Badge>
                            )
                        }
                    </div>
                    : placeholder
            }
        </SelectTrigger>
        <SelectContent className={className}
            headNode={
                <div className="p-2">
                    <SearchInput ref={inputRef} inputClassName="h-8" placeholder={searchPlaceholder} onChange={handleSearch} iconClassName="w-4 h-4" />
                </div>
            }
            footerNode={children}
        >
            <div className="mt-2">
                {
                    optionFilter.map((item, index) => (
                        <MultiItem active={values.includes(item.value)} value={item.value} onClick={handleSwitch}>{item.label}</MultiItem>
                    ))
                }
            </div>
        </SelectContent>
    </Select>
}

MultiSelect.displayName = 'MultiSelect'

export default MultiSelect