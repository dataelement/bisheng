"use client"

import * as PopoverPrimitive from "@radix-ui/react-popover"
import { debounce } from "lodash-es"
import { Check, ChevronDown, Loader2, Search, X } from "lucide-react"
import * as React from "react"
import { useTranslation } from "react-i18next"
import { Badge } from "../badge"
import { Button } from "../button"
import { Input } from "../input"
import { cname } from "../utils"

// Types
export interface Option {
    label: string
    value: string
    disabled?: boolean
    loading?: boolean // Added loading state for individual options
    error?: boolean // Added error state for individual options
}

export interface MultiSelectProps {
    // Core functionality
    options: Option[]
    value?: string[]
    defaultValue?: string[]
    onValueChange?: (value: string[]) => void

    // UI Configuration
    placeholder?: string
    searchPlaceholder?: string
    emptyMessage?: string
    maxDisplayed?: number

    // Behavior
    multiple?: boolean
    searchable?: boolean
    clearable?: boolean
    disabled?: boolean
    loading?: boolean

    // Validation
    error?: boolean
    errorMessage?: string
    required?: boolean

    // Advanced features
    lockedValues?: string[]
    onSearch?: (query: string) => void
    onLoadMore?: () => void
    hasMore?: boolean
    onFetchByIds?: (ids: string[]) => Promise<Option[]>

    // Styling
    className?: string
    triggerClassName?: string
    contentClassName?: string

    // Accessibility
    id?: string
    name?: string
    "aria-label"?: string
    "aria-describedby"?: string
}

function useOptionCache({ options, onFetchByIds }: Pick<MultiSelectProps, "options" | "onFetchByIds">) {
    const [optionCache, setOptionCache] = React.useState<Map<string, Option>>(new Map())
    const [fetchingIds, setFetchingIds] = React.useState<Set<string>>(new Set())

    // Update cache when options change
    React.useEffect(() => {
        const newCache = new Map(optionCache)
        options.forEach((option) => {
            newCache.set(option.value, option)
        })
        setOptionCache(newCache)
    }, [options])

    // Function to fetch missing options by IDs
    const fetchMissingOptions = React.useCallback(
        async (ids: string[]) => {
            if (!onFetchByIds) return

            const missingIds = ids.filter((id) => !optionCache.has(id) && !fetchingIds.has(id))
            if (missingIds.length === 0) return

            // Mark IDs as being fetched
            setFetchingIds((prev) => new Set([...prev, ...missingIds]))

            // Add loading placeholders to cache
            setOptionCache((prev) => {
                const newCache = new Map(prev)
                missingIds.forEach((id) => {
                    newCache.set(id, {
                        value: id,
                        label: `Loading...`,
                        loading: true,
                    })
                })
                return newCache
            })

            try {
                const fetchedOptions = await onFetchByIds(missingIds)

                // Update cache with fetched options
                setOptionCache((prev) => {
                    const newCache = new Map(prev)
                    fetchedOptions.forEach((option) => {
                        newCache.set(option.value, option)
                    })
                    return newCache
                })
            } catch (error) {
                console.error("Failed to fetch options:", error)

                // Mark failed options with error state
                setOptionCache((prev) => {
                    const newCache = new Map(prev)
                    missingIds.forEach((id) => {
                        newCache.set(id, {
                            value: id,
                            label: `Unknown (${id})`,
                            error: true,
                        })
                    })
                    return newCache
                })
            } finally {
                // Remove IDs from fetching set
                setFetchingIds((prev) => {
                    const newSet = new Set(prev)
                    missingIds.forEach((id) => newSet.delete(id))
                    return newSet
                })
            }
        },
        [optionCache, fetchingIds, onFetchByIds],
    )

    // Get option by ID from cache
    const getOptionById = React.useCallback(
        (id: string): Option | undefined => {
            return optionCache.get(id)
        },
        [optionCache],
    )

    // Get all available options (from props + cache)
    const allOptions = React.useMemo(() => {
        const optionMap = new Map<string, Option>()

        // Add options from cache first
        optionCache.forEach((option, id) => {
            optionMap.set(id, option)
        })

        // Override with options from props (they are more up-to-date)
        options.forEach((option) => {
            optionMap.set(option.value, option)
        })

        return Array.from(optionMap.values())
    }, [options, optionCache])

    return {
        fetchMissingOptions,
        getOptionById,
        allOptions: options,
    }
}

// Custom hook for managing component state
function useMultiSelectState({
    value,
    defaultValue = [],
    onValueChange,
    multiple = true,
    lockedValues = [],
    onFetchByIds,
    fetchMissingOptions,
}: Pick<MultiSelectProps, "value" | "defaultValue" | "onValueChange" | "multiple" | "lockedValues" | "onFetchByIds"> & {
    fetchMissingOptions: (ids: string[]) => Promise<void>
}) {
    const [internalValue, setInternalValue] = React.useState<string[]>(defaultValue)
    const isControlled = value !== undefined
    const currentValue = isControlled ? value : internalValue

    React.useEffect(() => {
        if (onFetchByIds && currentValue.length > 0) {
            fetchMissingOptions(currentValue)
        }
    }, [currentValue, onFetchByIds, fetchMissingOptions])

    const updateValue = React.useCallback(
        (newValue: string[]) => {
            if (!isControlled) {
                setInternalValue(newValue)
            }
            onValueChange?.(newValue)
        },
        [isControlled, onValueChange],
    )

    const toggleOption = React.useCallback(
        (optionValue: string) => {
            if (lockedValues.includes(optionValue)) return

            if (multiple) {
                const newValue = currentValue.includes(optionValue)
                    ? currentValue.filter((v) => v !== optionValue)
                    : [...currentValue, optionValue]
                updateValue(newValue)
            } else {
                updateValue(currentValue.includes(optionValue) ? [] : [optionValue])
            }
        },
        [currentValue, multiple, lockedValues, updateValue],
    )

    const removeOption = React.useCallback(
        (optionValue: string) => {
            if (lockedValues.includes(optionValue)) return
            updateValue(currentValue.filter((v) => v !== optionValue))
        },
        [currentValue, lockedValues, updateValue],
    )

    const clearAll = React.useCallback(() => {
        const lockedOnly = currentValue.filter((v) => lockedValues.includes(v))
        updateValue(lockedOnly)
    }, [currentValue, lockedValues, updateValue])

    return {
        currentValue,
        toggleOption,
        removeOption,
        clearAll,
    }
}

// Custom hook for search functionality
function useSearch({
    options,
    onSearch,
    searchable = true,
}: Pick<MultiSelectProps, "options" | "onSearch" | "searchable">) {
    const [searchQuery, setSearchQuery] = React.useState("")

    const setDebounceValue = React.useCallback(debounce((value) => {
        setSearchQuery(value)
        onSearch(value)
    }, 500), [setSearchQuery])

    // Filter options based on search
    const filteredOptions = React.useMemo(() => {
        if (!searchable || !searchQuery) {
            return options
        }
        if (onSearch) {
            return options // External search handles filtering
        }

        const filtered = options.filter((option) => option.label.toLowerCase().includes(searchQuery.toLowerCase()))
        return filtered
    }, [options, searchQuery, searchable, onSearch])

    return {
        searchQuery,
        setSearchQuery: setDebounceValue,
        filteredOptions,
    }
}

const OptionItem = React.memo<{
    option: Option
    isSelected: boolean
    isLocked: boolean
    onToggle: (value: string) => void
}>(({ option, isSelected, isLocked, onToggle }) => {
    return (
        <div
            role="option"
            aria-selected={isSelected}
            className={cname(
                "relative flex cursor-pointer select-none items-center rounded-sm px-2 py-1.5 text-sm outline-none transition-colors",
                "hover:bg-[#EBF0FF] hover:text-accent-foreground",
                "focus:bg-[#EBF0FF] focus:text-accent-foreground",
                isSelected && "bg-[#EBF0FF] text-accent-foreground",
                (option.disabled || isLocked || option.loading) && "pointer-events-none opacity-50",
                option.error && "text-destructive",
            )}
            onClick={() => !option.disabled && !isLocked && !option.loading && onToggle(option.value)}
        >
            <span className="flex-1 truncate">{option.label}</span>
            <div className="ml-2 flex items-center gap-1">
                {option.loading && <Loader2 className="h-3 w-3 animate-spin" />}
                {isSelected && !option.loading && <Check className="size-3.5 shrink-0" />}
                {isLocked && <span className="text-xs text-muted-foreground">Locked</span>}
                {option.error && <span className="text-xs text-destructive">Error</span>}
            </div>
        </div>
    )
})
OptionItem.displayName = "OptionItem"

const SelectedValues = React.memo<{
    selectedOptions: Option[]
    lockedValues: string[]
    maxDisplayed: number
    onRemove: (value: string) => void
}>(({ selectedOptions, lockedValues, maxDisplayed, onRemove }) => {
    const { t } = useTranslation()
    const displayedOptions = selectedOptions.slice(0, maxDisplayed)
    const remainingCount = selectedOptions.length - maxDisplayed

    return (
        <div className="flex flex-wrap gap-1">
            {displayedOptions.map((option) => {
                const isLocked = lockedValues.includes(option.value)
                return (
                    <Badge
                        key={option.value}
                        variant={option.error ? "destructive" : "secondary"}
                        className="bg-primary/20 text-primary hover:bg-primary/15 gap-1"
                    >
                        <span className="">
                            {option.loading ? (
                                <span className="flex items-center gap-1">
                                    <Loader2 className="h-3 w-3 animate-spin" />
                                    Loading...
                                </span>
                            ) : (
                                option.label
                            )}
                        </span>
                        {!isLocked && !option.loading && (
                            <Button
                                variant="ghost"
                                size="sm"
                                className="h-auto p-0 text-primary"
                                onClick={(e) => {
                                    e.preventDefault()
                                    e.stopPropagation()
                                    onRemove(option.value)
                                }}
                            >
                                <X className="h-3 w-3" />
                            </Button>
                        )}
                    </Badge>
                )
            })}
            {remainingCount > 0 && (
                <Badge variant="outline" className="pointer-events-none text-primary">
                    +{remainingCount} {t('more')}
                </Badge>
            )}
        </div>
    )
})
SelectedValues.displayName = "SelectedValues"

// Main component
export const MultiSelect = React.forwardRef<React.ElementRef<typeof PopoverPrimitive.Trigger>, MultiSelectProps>(
    (
        {
            options = [],
            value,
            defaultValue,
            onValueChange,
            placeholder = "",
            searchPlaceholder = "",
            emptyMessage = "",
            maxDisplayed = 3,
            multiple = false,
            searchable = true,
            clearable = true,
            disabled = false,
            loading = false,
            error = false,
            errorMessage,
            required = false,
            lockedValues = [],
            onSearch,
            onLoadMore,
            hasMore = false,
            onFetchByIds, // Added onFetchByIds prop
            className,
            triggerClassName,
            contentClassName,
            id,
            name,
            "aria-label": ariaLabel,
            "aria-describedby": ariaDescribedBy,
            ...props
        },
        ref,
    ) => {
        const [open, setOpen] = React.useState(false)
        const searchInputRef = React.useRef<HTMLInputElement>(null)
        const footerRef = useScrollLoad(searchInputRef, onLoadMore)

        const { fetchMissingOptions, getOptionById, allOptions } = useOptionCache({
            options,
            onFetchByIds,
        })

        const { currentValue, toggleOption, removeOption, clearAll } = useMultiSelectState({
            value,
            defaultValue,
            onValueChange,
            multiple,
            lockedValues,
            onFetchByIds,
            fetchMissingOptions,
        })

        const { searchQuery, setSearchQuery, filteredOptions } = useSearch({
            options: allOptions,
            onSearch,
            searchable,
        })

        const selectedOptions = React.useMemo(() => {
            const result = currentValue.map((value) => {
                const cachedOption = getOptionById(value)
                if (cachedOption) {
                    return cachedOption
                }
                // Create placeholder option if not found in cache
                const placeholder = {
                    value,
                    label: `Loading...`,
                    loading: true,
                }
                return placeholder
            })
            return result
        }, [currentValue, getOptionById])

        // Focus search input when popover opens
        React.useEffect(() => {
            if (open && searchable && searchInputRef.current) {
                searchInputRef.current.focus()
            }
        }, [open, searchable])

        // Clear search when popover closes
        React.useEffect(() => {
            if (!open) {
                setSearchQuery("")
            }
        }, [open, setSearchQuery])

        const handleKeyDown = (event: React.KeyboardEvent) => {
            if (event.key === "Escape") {
                setOpen(false)
            }
        }

        const canClear = clearable && currentValue.length > 0 && !disabled
        const hasSelection = currentValue.length > 0

        return (
            <PopoverPrimitive.Root open={open} onOpenChange={setOpen}>
                <PopoverPrimitive.Trigger
                    ref={ref}
                    className={cname(
                        "flex h-auto min-h-9 w-full items-center justify-between rounded-md border border-input  bg-search-input px-3 py-2 text-sm ring-offset-background transition-colors",
                        "placeholder:text-muted-foreground",
                        "focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
                        "disabled:cursor-not-allowed disabled:opacity-50",
                        error && "border-destructive focus:ring-destructive",
                        triggerClassName,
                    )}
                    disabled={disabled}
                    aria-label={ariaLabel}
                    aria-describedby={ariaDescribedBy}
                    aria-expanded={open}
                    aria-haspopup="listbox"
                    role="combobox"
                    onKeyDown={handleKeyDown}
                    {...props}
                >
                    <div className="flex-1 overflow-hidden text-left">
                        {hasSelection ? (
                            multiple ? (
                                <SelectedValues
                                    selectedOptions={selectedOptions}
                                    lockedValues={lockedValues}
                                    maxDisplayed={maxDisplayed}
                                    onRemove={removeOption}
                                />
                            ) : (
                                <span className="truncate">{selectedOptions[0]?.label}</span>
                            )
                        ) : (
                            <span className="text-muted-foreground">{placeholder}</span>
                        )}
                    </div>

                    <div className="flex items-center gap-1">
                        {loading && <Loader2 className="h-4 w-4 animate-spin" />}
                        {canClear && (
                            <Button
                                variant="ghost"
                                size="sm"
                                className="h-auto p-1 text-muted-foreground hover:text-foreground"
                                onClick={(e) => {
                                    e.preventDefault()
                                    e.stopPropagation()
                                    clearAll()
                                }}
                            >
                                <X className="h-3 w-3" />
                                <span className="sr-only">Clear selection</span>
                            </Button>
                        )}
                        <ChevronDown className="size-5 opacity-50" />
                    </div>
                </PopoverPrimitive.Trigger>

                <PopoverPrimitive.Portal>
                    <PopoverPrimitive.Content
                        className={cname(
                            "z-50 w-full min-w-[var(--radix-popover-trigger-width)] rounded-md border bg-popover p-0 text-popover-foreground shadow-md outline-none",
                            "data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2",
                            contentClassName,
                        )}
                        align="start"
                        sideOffset={4}
                    >
                        {searchable && (
                            <div className="border-b p-2">
                                <div className="relative">
                                    <Search className="absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-gray-950 dark:text-gray-500  z-10" />
                                    <Input
                                        ref={searchInputRef}
                                        placeholder={searchPlaceholder}
                                        value={searchQuery}
                                        onChange={(e) => setSearchQuery(e.target.value)}
                                        className="pl-8 bg-search-input h-8"
                                    />
                                </div>
                            </div>
                        )}

                        <div role="listbox" aria-multiselectable={multiple} className="max-h-60 overflow-auto p-1">
                            {filteredOptions.length === 0 ? (
                                <div className="py-6 text-center text-sm text-muted-foreground">{emptyMessage}</div>
                            ) : (
                                filteredOptions.map((option) => (
                                    <OptionItem
                                        key={option.value}
                                        option={option}
                                        isSelected={currentValue.includes(option.value)}
                                        isLocked={lockedValues.includes(option.value)}
                                        onToggle={toggleOption}
                                    />
                                ))
                            )}

                            {hasMore && onLoadMore && (
                                <div className="p-2">
                                    <Button variant="ghost" size="sm" className="w-full" disabled={loading}>
                                        {loading ? (
                                            <>
                                                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                                                Loading...
                                            </>
                                        ) :
                                            <div ref={footerRef} className="h-6"></div>
                                        }
                                    </Button>
                                </div>
                            )}
                        </div>
                    </PopoverPrimitive.Content>
                </PopoverPrimitive.Portal>

                {/* Hidden input for form integration */}
                {name && (
                    <input
                        type="hidden"
                        name={name}
                        value={currentValue.join(",")}
                        required={required && currentValue.length === 0}
                    />
                )}
            </PopoverPrimitive.Root>
        )
    },
)

MultiSelect.displayName = "MultiSelect"



const useScrollLoad = (inputRef, onLoadMore) => {
    const [footerElement, setFooterElement] = React.useState(null)

    const footerRef = React.useCallback((node) => {
        if (node !== null) {
            setFooterElement(node)
        }
    }, [])

    React.useLayoutEffect(function () {
        if (!footerElement) return

        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    // console.log('div is in the viewport!');
                    onLoadMore?.(inputRef.current?.value || '')
                }
            });
        }, {
            rootMargin: '0px',
            threshold: 0.1
        });

        // 开始观察目标元素
        observer.observe(footerElement);

        return () => observer.unobserve(footerElement);
    }, [footerElement])

    return footerRef
}