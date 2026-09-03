import { Select, SelectContent, SelectTrigger } from "@/components/bs-ui/select"
import { Check } from "lucide-react"
import { useState, type ReactNode } from "react"

export function toggleFilterValue(current: string, clicked: string): string {
    return String(current) === String(clicked) ? "" : clicked
}

interface FilterOption {
    value: string
    label: ReactNode
}

interface ClearableFilterSelectProps {
    value: string
    placeholder: string
    options: FilterOption[]
    triggerClassName?: string
    contentClassName?: string
    onValueChange: (value: string) => void
    onOpenChange?: (open: boolean) => void
}

/**
 * Filter dropdown that clears when the current option is clicked again.
 * Custom rows are required: Radix SelectItem never fires onValueChange for the
 * already-selected value, and intercepting its pointer events still lets it
 * write the same value back.
 */
export function ClearableFilterSelect({
    value,
    placeholder,
    options,
    triggerClassName,
    contentClassName,
    onValueChange,
    onOpenChange,
}: ClearableFilterSelectProps) {
    const [open, setOpen] = useState(false)
    const selected = String(value || "")
    const selectedLabel = options.find((option) => option.value === selected)?.label

    const handleOpenChange = (next: boolean) => {
        setOpen(next)
        onOpenChange?.(next)
    }

    const handlePick = (itemValue: string) => {
        onValueChange(toggleFilterValue(selected, itemValue))
        handleOpenChange(false)
    }

    return (
        <Select open={open} onOpenChange={handleOpenChange}>
            <SelectTrigger className={triggerClassName}>
                {selectedLabel ? (
                    <span className="line-clamp-1 text-left">{selectedLabel}</span>
                ) : (
                    <span className="line-clamp-1 text-left text-gray-500">{placeholder}</span>
                )}
            </SelectTrigger>
            <SelectContent className={contentClassName}>
                <div className="w-full min-w-[var(--radix-select-trigger-width)]">
                    {options.map((option) => {
                        const active = selected === option.value
                        return (
                            <div
                                key={option.value}
                                role="option"
                                aria-selected={active}
                                className={`relative mb-1 flex w-full cursor-pointer select-none items-center rounded-sm py-1.5 pl-2 pr-8 text-sm outline-none hover:bg-[#EBF0FF] hover:text-accent-foreground dark:hover:bg-gray-700 ${
                                    active ? "bg-[#EBF0FF] dark:bg-gray-700" : ""
                                }`}
                                onPointerDown={(event) => {
                                    event.preventDefault()
                                    event.stopPropagation()
                                    handlePick(option.value)
                                }}
                            >
                                <span className="absolute right-2 flex h-3.5 w-3.5 items-center justify-center">
                                    {active && <Check className="h-4 w-4" />}
                                </span>
                                {option.label}
                            </div>
                        )
                    })}
                </div>
            </SelectContent>
        </Select>
    )
}
