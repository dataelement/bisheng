import { Check, ChevronDown, ChevronRight, X } from "lucide-react"
import React, { useEffect, useRef, useState } from "react"
import { Select, SelectContent, SelectTrigger } from "."
import { Badge } from "../badge"
import { SearchInput } from "../input"
import { cname, useDebounce } from "../utils"

type OptionValue = string | number;

const MultiItem: React.FC<
    { active: boolean; children: React.ReactNode; value: OptionValue; onClick: (value: OptionValue, label: string) => void }
> = ({ active, children, value, onClick }) => {

    return <div
        key={value}
        className={`relative flex w-full cursor-default select-none items-center rounded-sm py-1.5 pl-2 pr-8 mb-1 text-sm outline-none hover:bg-[#EBF0FF] dark:hover:bg-gray-700 hover:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50 break-all 
    ${active && 'bg-[#EBF0FF] dark:bg-gray-700'}`}
        onClick={() => { onClick(value, children as string) }}
    >
        <span className="absolute right-2 flex h-3.5 w-3.5 items-center justify-center">
            {active && <Check className="h-4 w-4"></Check>}
        </span>
        {children}
    </div>
}
interface Option {
    label: string;
    value: OptionValue;
}

interface OptionGroup {
    label: string;
    value: string;
    options: Option[];
}

interface BaseProps<T> {
    /** 多选 */
    id?: string;
    multiple?: boolean;
    error?: boolean;
    errorKeys?: string[];
    /** 高度不变，内部滚动 */
    scroll?: boolean;
    disabled?: boolean;
    className?: string;
    contentClassName?: string;
    options: Option[];
    groupedOptions?: OptionGroup[];
    loading?: boolean;
    loadingText?: string;
    emptyText?: string;
    children?: React.ReactNode;
    placeholder?: string;
    searchPlaceholder?: string;
    tabs?: React.ReactNode;
    hideSearch?: boolean;
    /** 锁定不可修改的值 */
    lockedValues?: string[];
    close?: boolean;
    onLoad?: () => void;
    onSearch?: (name: string) => void;
    onChange?: (value: T) => void;
}

// onScrollLoad有值表示开启分页、异步检索
interface ScrollLoadProps extends BaseProps<Option[]> {
    onScrollLoad: (name: string) => void;
    value?: Option[];
    defaultValue?: Option[];
}

interface NonScrollLoadProps extends BaseProps<string[]> {
    onScrollLoad?: undefined;
    value?: string[];
    defaultValue?: string[];
}

type IProps = ScrollLoadProps | NonScrollLoadProps;

const MultiSelect = ({
    id = `${Date.now()}`,
    error = false,
    errorKeys = [],
    multiple = false,
    className,
    contentClassName,
    value = [],
    scroll = false,
    close = false,
    defaultValue = [],
    options = [],
    groupedOptions = [],
    loading = false,
    loadingText = '',
    emptyText = '',
    children = null,
    placeholder = '',
    searchPlaceholder = '',
    lockedValues = [],
    tabs = null,
    hideSearch = false,
    onSearch,
    onLoad,
    onScrollLoad,
    onChange, ...props
}: IProps) => {

    const [values, setValues] = React.useState(defaultValue)
    const [optionFilter, setOptionFilter] = React.useState(options)
    const [created, creatInput] = useState(false)
    const inputRef = useRef(null)

    useEffect(() => {
        setValues(value)
    }, [value])

    useEffect(() => {
        // if (onScrollLoad) {
        setOptionFilter(options);
        // }
    }, [options]);

    const [expandedGroups, setExpandedGroups] = React.useState<Record<string, boolean>>({})
    useEffect(() => {
        if (!groupedOptions.length) return;
        setExpandedGroups((prev) => groupedOptions.reduce((acc, group) => {
            acc[group.value] = prev[group.value] ?? true;
            return acc;
        }, {} as Record<string, boolean>))
    }, [groupedOptions]);

    // delete 
    const handleDelete = (value: OptionValue) => {
        const newValues = (values as any[]).filter((item) => {
            const _value = onScrollLoad ? (item as Option).value : item;
            return _value !== value
        })
        setValues(newValues)
        onChange?.(newValues)
    }
    // add
    const triggerRef = useRef(null)
    const handleSwitch = (value: OptionValue, label: string) => {
        if (lockedValues.includes(value as string)) {
            return
        }

        const updateValues = (newValues: any) => {
            setValues(newValues);
            onChange?.(newValues);
        };

        // 单选
        if (!multiple) {
            const newValues = onScrollLoad ? [{ label, value }] : [value]
            updateValues(newValues);
            // 关闭弹窗
            const element = triggerRef.current;
            if (element) {
                // 创建 PointerEvent
                const event = new PointerEvent('pointerdown', {
                    bubbles: true,
                    cancelable: true,
                    pointerId: 1,
                    pointerType: 'mouse'
                });
                element.dispatchEvent(event);
            }
            return
        }

        if (onScrollLoad) {
            const newValues = (values as Option[]).some(item => item.value === value)
                ? (values as Option[]).filter(item => item.value !== value)
                : [...(values as Option[]), { label, value }];
            updateValues(newValues);
        } else {
            const newValues = (values as string[]).includes(value)
                ? (values as string[]).filter(item => item !== value)
                : [...(values as string[]), value];
            updateValues(newValues);
        }
    }

    // search
    const handleSearch = useDebounce((e) => {
        if (onSearch) {
            return onSearch?.(inputRef.current?.value || '')
        }
        const newValues = options.filter((item) => {
            return item.label.toLowerCase().indexOf(e.target.value.trim().toLowerCase()) !== -1
        })
        setOptionFilter(newValues)
    }, 500, false)

    // scroll laod
    const footerRef = useRef(null)
    useEffect(function () {
        if (!created) return
        if (!footerRef.current) return
        if (!onScrollLoad) return // 不绑定滚动事件
        const footer = footerRef.current;

        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    // console.log('div is in the viewport!');
                    onScrollLoad?.(inputRef.current?.value || '')
                }
            });
        }, {
            // root: null, // 视口
            rootMargin: '0px', // 视口的边距
            threshold: 0.1 // 目标元素超过视口的10%即触发回调
        });

        // 开始观察目标元素
        observer.observe(footer);

        return () => observer.unobserve(footer);
    }, [created])

    const handleClearClick = () => {
        setValues([])
        onChange?.([])
    }

    return <Select
        {...props}
        required
        onOpenChange={(e) => {
            creatInput(e);
            if (e) {
                onLoad?.();
                setOptionFilter(options);
            }
        }}
    >
        <SelectTrigger className={cname(`group min-h-9 py-1 ${error && 'border-red-500'} ${scroll ? 'h-9 overflow-y-auto items-start pt-1.5' : 'h-auto'}`, className)} ref={triggerRef}>
            {
                !multiple && (values.length ? <span className="text-foreground">{onScrollLoad ? (values[0] as Option).label : options.find(op => op.value === values[0])?.label}</span> : placeholder)
            }
            {
                multiple && (values.length ? (
                    onScrollLoad ? <div className="flex flex-wrap w-full">
                        {
                            values.map(item =>
                                <Badge onPointerDown={(e) => e.stopPropagation()} key={item.value}
                                    className={`flex whitespace-normal items-center gap-1 select-none bg-primary/20 text-primary hover:bg-primary/15 m-[2px] break-all ${errorKeys.includes(item.value) && 'bg-red-100 border-red-600'}`}>
                                    {item.label}
                                    {lockedValues.includes(item.value as string) || <X className="h-3 w-3 min-w-3" onClick={() => handleDelete(item.value)}></X>}
                                </Badge>
                            )
                        }
                    </div> : <div className="flex flex-wrap w-full">
                        {
                            // 使用key反推label
                            options.filter(option => (values as string[]).includes(option.value)).map(option =>
                                <Badge onPointerDown={(e) => e.stopPropagation()} key={option.value} className="flex whitespace-normal items-center gap-1 select-none bg-primary/20 text-primary hover:bg-primary/15 m-[2px] break-all  11">
                                    {option.label}
                                    {lockedValues.includes(option.value as string) || <X className="h-3 w-3 min-w-3" onClick={() => handleDelete(option.value)}></X>}
                                </Badge>
                            )
                        }
                    </div>)
                    : placeholder)
            }
            {close && values.length !== 0 && <X
                className="group-hover:block hidden bg-border text-[#666] rounded-full p-0.5 min-w-[14px] mt-1"
                width={14}
                height={14}
                onPointerDown={(e) => e.stopPropagation()}
                onClick={handleClearClick}
            />}
        </SelectTrigger>
        <SelectContent
            className={contentClassName + ' overflow-visible'}
            headNode={
                <div className="p-2">
                    {tabs}
                    {!hideSearch && <SearchInput id={id} ref={inputRef} inputClassName="h-8 dark:border-gray-700" placeholder={searchPlaceholder} onChange={handleSearch} iconClassName="w-4 h-4" />}
                </div>
            }
            footerNode={children}
        >
            <div className="mt-2 w-full min-w-[var(--radix-select-trigger-width)]">
                {
                    groupedOptions.length ? groupedOptions.map((group) => (
                        <div key={group.value} className="mb-1">
                            <button
                                type="button"
                                className="flex w-full items-center gap-1 rounded-sm px-1 py-1 text-left text-xs font-medium text-muted-foreground hover:bg-muted/60"
                                onClick={() => setExpandedGroups((prev) => ({ ...prev, [group.value]: !prev[group.value] }))}
                            >
                                {expandedGroups[group.value] === false ? <ChevronRight className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                                <span>{group.label}</span>
                                <span className="text-[11px] text-muted-foreground/70">({group.options.length})</span>
                            </button>
                            {expandedGroups[group.value] !== false && group.options.map((item) => (
                                <div className="pl-4" key={item.value}>
                                    <MultiItem
                                        active={values.some(val => val === item.value || val.value === item.value)}
                                        value={item.value}
                                        onClick={handleSwitch}
                                    >{item.label}</MultiItem>
                                </div>
                            ))}
                        </div>
                    )) : optionFilter.map((item) => (
                        <MultiItem
                            key={item.value}
                            active={values.some(val => val === item.value || val.value === item.value)}
                            value={item.value}
                            onClick={handleSwitch}
                        >{item.label}</MultiItem>
                    ))
                }
                {
                    loading && <div className="py-2 text-center text-xs text-muted-foreground">{loadingText}</div>
                }
                {
                    emptyText && !loading && (groupedOptions.length ? !groupedOptions.some(group => group.options.length) : optionFilter.length === 0)
                    && <div className="py-2 text-center text-xs text-muted-foreground">{emptyText}</div>
                }
                <div ref={footerRef} style={{ height: 20 }}></div>
            </div>
        </SelectContent>
    </Select>
}

MultiSelect.displayName = 'MultiSelect'

export default MultiSelect
