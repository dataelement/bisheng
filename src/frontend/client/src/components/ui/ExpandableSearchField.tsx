import { Search, X } from "lucide-react";
import {
    forwardRef,
    useCallback,
    useEffect,
    useLayoutEffect,
    useRef,
    useState,
    type FocusEventHandler,
    type KeyboardEventHandler,
    type MutableRefObject,
} from "react";
import { cn } from "~/utils";

export interface ExpandableSearchFieldProps
    extends Omit<
        React.InputHTMLAttributes<HTMLInputElement>,
        "value" | "onChange" | "size" | "type"
    > {
    value: string;
    onChange: (value: string) => void;
    placeholder: string;
    /** Tooltip / title when collapsed */
    titleWhenCollapsed?: string;
    /** Tailwind width when expanded (default 220px，与消息提醒一致) */
    expandedWidthClassName?: string;
    showClearButton?: boolean;
    containerClassName?: string;
}

/**
 * 可展开搜索框：收起为 32×32 图标按钮，展开为蓝框 + 蓝色放大镜 + 输入区（消息提醒弹窗规范）。
 * width / border / 图标色使用 transition，避免“瞬时弹出”感。
 */
export const ExpandableSearchField = forwardRef<HTMLInputElement, ExpandableSearchFieldProps>(
    function ExpandableSearchField(
        {
            value,
            onChange,
            placeholder,
            titleWhenCollapsed,
            expandedWidthClassName = "w-[220px]",
            showClearButton = false,
            className,
            containerClassName,
            onKeyDown,
            onBlur,
            onFocus,
            disabled,
            ...inputProps
        },
        ref
    ) {
        const inputRef = useRef<HTMLInputElement | null>(null);
        const wasExpandedRef = useRef(false);
        const [inputFocused, setInputFocused] = useState(false);

        const setInputRef = useCallback(
            (el: HTMLInputElement | null) => {
                inputRef.current = el;
                if (typeof ref === "function") {
                    ref(el);
                } else if (ref) {
                    (ref as MutableRefObject<HTMLInputElement | null>).current = el;
                }
            },
            [ref]
        );

        const [showExpanded, setShowExpanded] = useState(() => !!value.trim());

        useEffect(() => {
            if (value.trim()) setShowExpanded(true);
        }, [value]);

        const expanded = showExpanded || !!value.trim();

        /** 展开且聚焦：蓝框（编辑态）；展开有失焦但有内容：灰框（仅展示关键词） */
        const showActiveChrome = expanded && inputFocused;

        /** 收起 → 展开后立刻聚焦（父组件常不传 ref，原先 ref.current 恒为 null 导致无法聚焦） */
        useLayoutEffect(() => {
            if (expanded && !wasExpandedRef.current) {
                inputRef.current?.focus({ preventScroll: true });
            }
            wasExpandedRef.current = expanded;
        }, [expanded]);

        const focusInput = useCallback(() => {
            requestAnimationFrame(() => {
                inputRef.current?.focus({ preventScroll: true });
            });
        }, []);

        const handleKeyDown: KeyboardEventHandler<HTMLInputElement> = (e) => {
            onKeyDown?.(e);
        };

        const handleFocus: FocusEventHandler<HTMLInputElement> = (e) => {
            onFocus?.(e);
            setInputFocused(true);
        };

        const handleBlur: FocusEventHandler<HTMLInputElement> = (e) => {
            onBlur?.(e);
            setInputFocused(false);
            const v = e.currentTarget.value.trim();
            if (!v) {
                setShowExpanded(false);
                onChange("");
            }
        };

        return (
            <div
                data-expandable-search="true"
                className={cn(
                    "flex items-center h-8 rounded-lg border bg-white overflow-hidden shrink-0 select-none",
                    "transition-[width,border-color,background-color] duration-300 ease-out motion-reduce:transition-none",
                    expanded
                        ? cn(
                              expandedWidthClassName,
                              showActiveChrome ? "border-[#024DE3]" : "border-[#E5E6EB]"
                          )
                        : "w-8 border-[#E5E6EB] cursor-pointer hover:bg-[#F7F8FA]",
                    disabled && "pointer-events-none opacity-50",
                    containerClassName
                )}
                onClick={() => {
                    if (!disabled && !expanded) {
                        setShowExpanded(true);
                        focusInput();
                    }
                }}
                title={expanded ? undefined : titleWhenCollapsed ?? placeholder}
            >
                <div
                    className={cn(
                        "flex items-center justify-center px-[7px] h-full shrink-0 transition-colors duration-300 ease-out",
                        showActiveChrome ? "text-[#024DE3]" : "text-[#86909C]"
                    )}
                >
                    <Search className="size-4 shrink-0" aria-hidden />
                </div>
                <input
                    ref={setInputRef}
                    type="search"
                    inputMode="search"
                    autoComplete="off"
                    disabled={disabled}
                    placeholder={placeholder}
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                    onKeyDown={handleKeyDown}
                    onFocus={handleFocus}
                    onBlur={handleBlur}
                    tabIndex={expanded ? 0 : -1}
                    className={cn(
                        "flex-1 min-w-0 h-full text-[14px] font-normal text-[#1d2129] bg-transparent outline-none placeholder:text-[#C9CDD4] placeholder:font-normal",
                        "transition-[opacity] duration-200 ease-out motion-reduce:transition-none",
                        showClearButton && value ? "pr-1" : "pr-3",
                        expanded ? "opacity-100" : "opacity-0 pointer-events-none",
                        className
                    )}
                    {...inputProps}
                />
                {showClearButton && expanded && value ? (
                    <button
                        type="button"
                        className="pr-2 text-[#86909C] hover:text-[#4E5969] shrink-0"
                        onClick={(e) => {
                            e.stopPropagation();
                            onChange("");
                            focusInput();
                        }}
                        aria-label="Clear search"
                    >
                        <X className="size-4" aria-hidden />
                    </button>
                ) : null}
            </div>
        );
    }
);

ExpandableSearchField.displayName = "ExpandableSearchField";
