import { useLocalize } from "~/hooks";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";
import * as React from "react";
import { ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import {
    Popover,
    PopoverContent,
    PopoverTrigger,
} from "@/components/ui/Popover";
import { Separator } from "@/components/ui/Separator";
import { cn } from "~/utils";

// 定义选项的类型
interface SourceOption {
    id: string;
    label: string;
}

interface MultiSourceSelectProps {
    options: SourceOption[];
    value: string[]; // 回显数据：当前选中的 ID 数组
    onChange: (value: string[]) => void; // 变更回调
    placeholder?: string;
    className?: string;
    /** Controlled open state — when provided, takes precedence over internal state. */
    open?: boolean;
    onOpenChange?: (open: boolean) => void;
    /** Visually hide the trigger button (still mounted so the popover can anchor). */
    hideTrigger?: boolean;
}

export function MultiSourceSelect({
    options,
    value = [],
    onChange,
    placeholder,
    className,
    open: openProp,
    onOpenChange,
    hideTrigger,
}: MultiSourceSelectProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const [internalOpen, setInternalOpen] = React.useState(false);
    const [hasEmptyError, setHasEmptyError] = React.useState(false);
    const open = openProp ?? internalOpen;
    // At least one source must stay selected. While the selection is empty the popover goes
    // modal, so clicks outside are consumed as a (blocked) close attempt instead of leaking
    // through to other controls.
    const requireSelection = options.length > 0 && value.length === 0;
    const setOpen = (next: boolean) => {
        // Closing with nothing selected is not allowed — warn the user and keep the popover open.
        if (!next && requireSelection) {
            setHasEmptyError(true);
            showToast?.({
                message: localize("com_subscription.select_at_least_one_source"),
                severity: NotificationSeverity.WARNING,
            });
            return;
        }
        setHasEmptyError(false);
        onOpenChange?.(next);
        if (openProp === undefined) setInternalOpen(next);
    };

    // Clear the error styling once the user picks at least one source.
    React.useEffect(() => {
        if (value.length > 0) setHasEmptyError(false);
    }, [value.length]);
    const [isMenuScrolling, setIsMenuScrolling] = React.useState(false);
    const menuScrollTimerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);

    // 处理单个项的点击
    const handleToggleItem = (id: string) => {
        const newValue = value.includes(id)
            ? value.filter((item) => item !== id) // 取消勾选
            : [...value, id]; // 勾选
        onChange(newValue);
    };

    // Standard select-all: "全部" reflects and controls the individual source checkboxes.
    const allSelected = options.length > 0 && options.every((opt) => value.includes(opt.id));
    const someSelected = value.length > 0 && !allSelected;
    const selectAllState: boolean | "indeterminate" = allSelected ? true : someSelected ? "indeterminate" : false;

    // 处理“全部信息源”的点击：已全选则取消全选，否则全选
    const handleSelectAll = () => {
        onChange(allSelected ? [] : options.map((opt) => opt.id));
    };

    // 渲染触发器内部的显示内容
    const renderValue = () => {
        // 无选中（无筛选）或已全选，回显“全部信息源”；部分选中回显“部分信息源”
        if (value.length === 0 || allSelected) {
            return <span className="text-gray-500">{placeholder ?? localize("com_subscription.all_sources")}</span>;
        }
        return <span className="text-gray-800">{localize("com_subscription.partial_sources")}</span>;
    };

    const handleMenuScroll = () => {
        setIsMenuScrolling(true);
        if (menuScrollTimerRef.current) clearTimeout(menuScrollTimerRef.current);
        menuScrollTimerRef.current = setTimeout(() => setIsMenuScrolling(false), 500);
    };

    return (
        <Popover open={open} onOpenChange={setOpen} modal={requireSelection}>
            <PopoverTrigger asChild>
                <Button
                    variant="outline"
                    className={cn(
                        "w-auto min-w-[160px] h-9 justify-between px-3 font-normal",
                        hasEmptyError && "border-[#F53F3F] bg-[#F53F3F]/10",
                        hideTrigger && "pointer-events-none inline-block size-0 min-w-0 overflow-hidden border-0 p-0 opacity-0",
                        className
                    )}
                    aria-hidden={hideTrigger || undefined}
                    tabIndex={hideTrigger ? -1 : undefined}
                >
                    {renderValue()}
                    <ChevronDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                </Button>
            </PopoverTrigger>
            <PopoverContent
                className="w-[180px] max-h-80 overflow-y-auto scroll-on-scroll p-0 bg-white rounded-[8px] border-none shadow-[0px_2px_8px_rgba(0,23,66,0.1)]"
                align="start"
                onScroll={handleMenuScroll}
                data-scrolling={isMenuScrolling ? "true" : "false"}
            >
                <div className="p-2">
                    {/* 全部信息源 选项 */}
                    <div
                        className="flex w-full min-w-0 cursor-pointer items-center space-x-2 rounded-[6px] px-2 py-[5px] transition-colors fine-pointer:hover:bg-[#F2F3F5]"
                        onClick={handleSelectAll}
                    >
                        <Checkbox
                            id="source-all"
                            className="border-[#D9D9D9] data-[state=checked]:border-primary data-[state=indeterminate]:border-primary"
                            checked={selectAllState}
                            onCheckedChange={handleSelectAll}
                            onClick={(e) => e.stopPropagation()}
                        />
                        <span className="flex-1 text-sm leading-[22px]">
                            {localize("com_subscription.all_sources")}
                        </span>
                    </div>

                    <Separator className="my-2" />

                    {/* 循环渲染数据源 */}
                    <div className="space-y-1">
                        {options.map((option) => (
                            <div
                                key={option.id}
                                className="flex w-full min-w-0 cursor-pointer items-center space-x-2 rounded-[6px] px-2 py-[5px] transition-colors fine-pointer:hover:bg-[#F2F3F5]"
                                onClick={() => handleToggleItem(option.id)}
                            >
                                <Checkbox
                                    id={`source-${option.id}`}
                                    className="border-[#D9D9D9] data-[state=checked]:border-primary data-[state=indeterminate]:border-primary"
                                    checked={value.includes(option.id)}
                                    onCheckedChange={() => handleToggleItem(option.id)}
                                    onClick={(e) => e.stopPropagation()}
                                />
                                <span className="min-w-0 flex-1 truncate text-sm leading-[22px]">
                                    {option.label}
                                </span>
                            </div>
                        ))}
                    </div>
                </div>
            </PopoverContent>
        </Popover>
    );
}