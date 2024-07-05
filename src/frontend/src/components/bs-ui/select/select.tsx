import React, { ChangeEvent } from "react"
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/bs-ui/select";
import { SearchInput } from "../input";

interface SelectSearchProps {
    value: string,
    options: {label: string, value: string}[],
    selectPlaceholder?:string,
    inputPlaceholder?:string,
    onOpenChange?: (open:boolean) => void,
    onValueChange: (value: string) => void,
    onChange: (e:ChangeEvent<HTMLInputElement>) => void,
    selectClass?: string,
    contentClass?: string
}

const SelectSearch: React.FC<SelectSearchProps> = ({
    value,
    options,
    selectPlaceholder = '',
    inputPlaceholder = '',
    onOpenChange,
    onValueChange,
    onChange,
    selectClass = '',
    contentClass = ''
}) => {
    return <Select value={value} onOpenChange={(open) => onOpenChange?.(open)} onValueChange={(v) => onValueChange(v)}>
        <SelectTrigger className={selectClass}>
            <SelectValue placeholder={selectPlaceholder}/>
        </SelectTrigger>
        <SelectContent className={contentClass}>
            <SearchInput inputClassName="h-8 mb-2 dark:border-gray-700" placeholder={inputPlaceholder} 
            onChange={(e) => onChange(e)} onKeyDown={e => e.stopPropagation()} iconClassName="w-4 h-4" />
            <SelectGroup>
                {options.map(el => (
                    <SelectItem key={el.value} value={el.value}>{el.label}</SelectItem>
                ))}
            </SelectGroup>
        </SelectContent>
    </Select>
}

export default React.memo(SelectSearch)