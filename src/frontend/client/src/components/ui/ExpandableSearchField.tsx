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
import cn from "~/utils/cn";

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
    /** Always show the full input (no icon-only collapsed state); better for mobile / app center */
    alwaysExpanded?: boolean;
    showClearButton?: boolean;
    clearButtonLabel?: string;
    containerClassName?: string;
}

/**
 * 可展开搜索框：收起为 32×32 图标按钮，展开为输入区（消息提醒弹窗规范）。
 * 聚焦态走输入框规范 §5.1 的灰链：描边加深（border-deep）+ 2px 灰阴影环（shadow-focus）。
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
            alwaysExpanded = false,
            showClearButton = false,
            clearButtonLabel = "Clear search",
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

        const [showExpanded, setShowExpanded] = useState(() => alwaysExpanded || !!value.trim());

        useEffect(() => {
            if (value.trim()) setShowExpanded(true);
        }, [value]);

        /** Collapse to icon when alwaysExpanded turns off (e.g. viewport crosses mobile breakpoint); avoid collapsing while focused */
        useEffect(() => {
            if (alwaysExpanded) return;
            if (!value.trim() && !inputFocused) {
                setShowExpanded(false);
            }
        }, [alwaysExpanded, value, inputFocused]);

        const expanded = alwaysExpanded || showExpanded || !!value.trim();

        /** 展开且聚焦：深描边 + 灰阴影环（编辑态）；展开但失焦有内容：常态灰框（仅展示关键词） */
        const showActiveChrome = expanded && inputFocused;

        /** 收起 → 展开后立刻聚焦（父组件常不传 ref，原先 ref.current 恒为 null 导致无法聚焦） */
        useLayoutEffect(() => {
            if (alwaysExpanded) {
                wasExpandedRef.current = true;
                return;
            }
            if (expanded && !wasExpandedRef.current) {
                inputRef.current?.focus({ preventScroll: true });
            }
            wasExpandedRef.current = expanded;
        }, [expanded, alwaysExpanded]);

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
            if (alwaysExpanded) {
                return;
            }
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
                    "relative flex items-center h-8 rounded-md border bg-white overflow-hidden shrink-0 select-none",
                    "transition-[width,border-color,background-color] duration-300 ease-out motion-reduce:transition-none",
                    expanded
                        ? cn(
                            expandedWidthClassName,
                            showActiveChrome ? "border-border-deep shadow-focus" : "border-border-base"
                        )
                        : "w-8 border-border-base cursor-pointer hover:bg-fill-1",
                    disabled && "pointer-events-none opacity-50",
                    containerClassName
                )}
                title={expanded ? undefined : titleWhenCollapsed ?? placeholder}
            >
                <div
                    className={cn(
                        "flex items-center justify-center px-[7px] h-full shrink-0 transition-colors duration-300 ease-out",
                        showActiveChrome ? "text-text-2" : "text-text-3"
                    )}
                >
                    <Search className="size-4 shrink-0" aria-hidden />
                </div>
                <input
                    ref={setInputRef}
                    type="text"
                    inputMode="search"
                    autoComplete="off"
                    disabled={disabled}
                    placeholder={placeholder}
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                    onKeyDown={handleKeyDown}
                    onFocus={handleFocus}
                    onBlur={handleBlur}
                    className={cn(
                        "flex-1 min-w-0 h-full text-[14px] font-normal text-text-1 bg-transparent outline-none placeholder:text-text-4 placeholder:font-normal",
                        "transition-[opacity] duration-200 ease-out motion-reduce:transition-none",
                        showClearButton && value ? "pr-1" : "pr-3",
                        expanded ? "opacity-100" : "opacity-0 pointer-events-none",
                        className
                    )}
                    {...inputProps}
                    aria-hidden={!expanded || inputProps["aria-hidden"]}
                    tabIndex={expanded ? inputProps.tabIndex ?? 0 : -1}
                />
                {!expanded && (
                    <button
                        type="button"
                        className="absolute inset-0 cursor-pointer rounded-[inherit] focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-border-deep"
                        aria-label={titleWhenCollapsed ?? placeholder}
                        aria-expanded={false}
                        disabled={disabled}
                        onClick={() => setShowExpanded(true)}
                    />
                )}
                {showClearButton && expanded && value ? (
                    <button
                        type="button"
                        className="pr-2 text-text-3 hover:text-text-2 shrink-0"
                        disabled={disabled}
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={(e) => {
                            e.stopPropagation();
                            inputRef.current?.focus({ preventScroll: true });
                            onChange("");
                        }}
                        aria-label={clearButtonLabel}
                    >
                        <X className="size-4" aria-hidden />
                    </button>
                ) : null}
            </div>
        );
    }
);

ExpandableSearchField.displayName = "ExpandableSearchField";
