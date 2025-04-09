import { Button } from "@/components/bs-ui/button"
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem } from "@/components/bs-ui/command"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/bs-ui/popover"
import { Check, ChevronsUpDown } from "lucide-react"
import { useState } from "react"
import { cn } from "../../../utils"

interface IProps {
    options: any[],
    value?: string
    labelKey?: string,
    valueKey?: string,
    defaultValue?: string,
    placeholder?: string,
    onChange?: (val: string) => void
}

export default function Combobox({
    value, onChange, defaultValue = '', options, placeholder = '', labelKey = 'label', valueKey = 'value'
}: IProps) {
    const [open, setOpen] = useState(false)
    const [localValue, setLocalValue] = useState(defaultValue)
    value = value || localValue
    // console.log('options :>> ', options);

    return <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
            <Button
                variant="outline"
                role="combobox"
                aria-expanded={open}
                className="w-[280px] justify-between"
            >
                {
                    value
                        ? options.find((option) => option[valueKey] + '' === value)?.[labelKey]
                        : <span>{placeholder}</span>
                }
                <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
            </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[200px] p-0">
            <Command filter={(value, search) => {
                // TODO cmdk0.2.2使用 keywords 过滤
                const name = options.find((option) => option[valueKey] + '' === value)?.[labelKey]
                if (!name) return 0
                if (name.toLocaleUpperCase().includes(search.toLocaleUpperCase())) return 1
                return 0
            }}>
                <CommandInput placeholder="" className="h-9" />
                <CommandEmpty></CommandEmpty>
                <CommandGroup className="max-h-[400px] overflow-y-auto">
                    {options.map((option) => (
                        <CommandItem
                            key={option[valueKey]}
                            value={option[valueKey] + ''}
                            onSelect={(currentValue) => {
                                setLocalValue(currentValue)
                                onChange?.(currentValue)
                                setOpen(false)
                            }}
                        >
                            {option[labelKey]}
                            <Check
                                className={cn(
                                    "ml-auto h-4 w-4",
                                    value === option[valueKey] + '' ? "opacity-100" : "opacity-0"
                                )}
                            />
                        </CommandItem>
                    ))}
                </CommandGroup>
            </Command>
        </PopoverContent>
    </Popover>
};
