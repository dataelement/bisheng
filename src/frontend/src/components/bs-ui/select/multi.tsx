import { Check, X } from "lucide-react"
import React, { useEffect, useRef, useState } from "react"
import { Select, SelectContent, SelectTrigger } from "."
import { Badge } from "../badge"
import { SearchInput } from "../input"
import { cname, useDebounce } from "../utils"

const MultiItem: React.FC<
    { active: boolean; children: React.ReactNode; value: string; onClick: (value: string, label: string) => void }
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
    value: string;
}

interface BaseProps<T> {
    /** 多选 */
    id?: string;
    multiple?: boolean;
    error?: boolean;
    /** 高度不变，内部滚动 */
    scroll?: boolean;
    disabled?: boolean;
    className?: string;
    contentClassName?: string;
    options: Option[];
    children?: React.ReactNode;
    placeholder?: string;
    searchPlaceholder?: string;
    tabs?: React.ReactNode;
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
    multiple = false,
    className,
    contentClassName,
    value = [],
    scroll = false,
    close = false,
    defaultValue = [],
    options = [],
    children = null,
    placeholder = '',
    searchPlaceholder = '',
    lockedValues = [],
    tabs = null,
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

    // delete 
    const handleDelete = (value: string) => {
        const newValues = (values as any[]).filter((item) => {
            const _value = onScrollLoad ? (item as Option).value : item;
            return _value !== value
        })
        setValues(newValues)
        onChange?.(newValues)
    }
    // add
    const triggerRef = useRef(null)
    const handleSwitch = (value: string, label: string) => {
        if (lockedValues.includes(value)) {
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
        const newValues = options.filter((item) => {
            return item.label.toLowerCase().indexOf(e.target.value.toLowerCase()) !== -1
        })
        setOptionFilter(newValues)
        onSearch?.(inputRef.current?.value || '')
    }, 500, false)

    // scroll laod
    const footerRef = useRef(null)
    useEffect(function () {
        if (!created) return
        if (!footerRef.current) return
        if (!onScrollLoad) return // 不绑定滚动事件

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
        observer.observe(footerRef.current);

        return () => observer.unobserve(footerRef.current);
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
            if (!e) {
                onLoad?.();
                setOptionFilter(options);
            }
        }}
    >
        <SelectTrigger className={cname(`group min-h-9 py-1 ${error && 'border-red-500'} ${scroll ? 'h-9 overflow-y-auto items-start pt-1.5' : 'h-auto'}`, className)} ref={triggerRef}>
            {
                !multiple && (values.length ? <span>{onScrollLoad ? (values[0] as Option).label : options.find(op => op.value === values[0])?.label}</span> : placeholder)
            }
            {
                multiple && (values.length ? (
                    onScrollLoad ? <div className="flex flex-wrap w-full">
                        {
                            values.map(item =>
                                <Badge onPointerDown={(e) => e.stopPropagation()} key={item.value} className="flex whitespace-normal items-center gap-1 select-none bg-primary/20 text-primary hover:bg-primary/15 m-[2px]">
                                    {item.label}
                                    {lockedValues.includes(item.value) || <X className="h-3 w-3" onClick={() => handleDelete(item.value)}></X>}
                                </Badge>
                            )
                        }
                    </div> : <div className="flex flex-wrap w-full">
                        {
                            options.filter(option => (values as string[]).includes(option.value)).map(option =>
                                <Badge onPointerDown={(e) => e.stopPropagation()} key={option.value} className="flex whitespace-normal items-center gap-1 select-none bg-primary/20 text-primary hover:bg-primary/15 m-[2px] break-all">
                                    {option.label}
                                    {lockedValues.includes(option.value) || <X className="h-3 w-3" onClick={() => handleDelete(option.value)}></X>}
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
                    <SearchInput id={id} ref={inputRef} inputClassName="h-8 dark:border-gray-700" placeholder={searchPlaceholder} onChange={handleSearch} iconClassName="w-4 h-4" />
                </div>
            }
            footerNode={children}
        >
            <div className="mt-2">
                {
                    optionFilter.map((item) => (
                        <MultiItem
                            active={values.some(val => val === item.value || val.value === item.value)}
                            value={item.value}
                            onClick={handleSwitch}
                        >{item.label}</MultiItem>
                    ))
                }
                <div ref={footerRef} style={{ height: 20 }}></div>
            </div>
        </SelectContent>
    </Select>
}

MultiSelect.displayName = 'MultiSelect'

export default MultiSelect