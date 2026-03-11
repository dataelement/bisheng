import * as React from "react";
import { ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
    Popover,
    PopoverContent,
    PopoverTrigger,
} from "@/components/ui/popover";
import { Separator } from "@/components/ui/separator";
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
}

export function MultiSourceSelect({
    options,
    value = [],
    onChange,
    placeholder = "全部信息源",
    className,
}: MultiSourceSelectProps) {
    const [open, setOpen] = React.useState(false);

    // 处理单个项的点击
    const handleToggleItem = (id: string) => {
        const newValue = value.includes(id)
            ? value.filter((item) => item !== id) // 取消勾选
            : [...value, id]; // 勾选
        onChange(newValue);
    };

    // 处理“全部信息源”的点击
    const handleSelectAll = () => {
        // 逻辑：点击“全部”时，清空具体的选中数组
        onChange([]);
    };

    // 渲染触发器内部的显示内容
    const renderValue = () => {
        // 如果数组为空，回显“全部信息源”
        if (value.length === 0) {
            return <span className="text-gray-500">{placeholder}</span>;
        }

        // 找到第一个选中项的 Label
        const firstSelected = options.find((opt) => opt.id === value[0]);

        return (
            <div className="flex items-center gap-1.5 overflow-hidden">
                <span className="inline-flex items-center bg-gray-100 px-2 py-0.5 rounded text-sm text-gray-800 whitespace-nowrap">
                    {firstSelected?.label}
                </span>
                {value.length > 1 && (
                    <span className="inline-flex items-center bg-gray-100 px-2 py-0.5 rounded text-sm text-gray-800">
                        +{value.length - 1}...
                    </span>
                )}
            </div>
        );
    };

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger asChild>
                <Button
                    variant="outline"
                    className={cn(
                        "w-auto min-w-[160px] h-9 justify-between px-3",
                        className
                    )}
                >
                    {renderValue()}
                    <ChevronDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                </Button>
            </PopoverTrigger>
            <PopoverContent className="w-[180px] max-h-80 overflow-y-auto p-0 bg-white rounded-lg" align="start">
                <div className="p-3">
                    {/* 全部信息源 选项 */}
                    <div
                        className="flex items-center py-[5px] space-x-2 hover:bg-slate-100 rounded-sm cursor-pointer transition-colors"
                        onClick={handleSelectAll}
                    >
                        <Checkbox
                            id="source-all"
                            checked={value.length === 0}
                            onCheckedChange={handleSelectAll}
                        />
                        <label
                            htmlFor="source-all"
                            className="text-sm leading-[22px] cursor-pointer flex-1"
                        >
                            全部信息源
                        </label>
                    </div>

                    <Separator className="my-2" />

                    {/* 循环渲染数据源 */}
                    <div className="space-y-1">
                        {options.map((option) => (
                            <div
                                key={option.id}
                                className="flex items-center space-x-2 py-[5px] hover:bg-slate-100 rounded-sm cursor-pointer transition-colors"
                                onClick={() => handleToggleItem(option.id)}
                            >
                                <Checkbox
                                    id={`source-${option.id}`}
                                    checked={value.includes(option.id)}
                                    onCheckedChange={() => handleToggleItem(option.id)}
                                />
                                <label
                                    htmlFor={`source-${option.id}`}
                                    className="text-sm leading-[22px] cursor-pointer flex-1"
                                >
                                    {option.label}
                                </label>
                            </div>
                        ))}
                    </div>
                </div>
            </PopoverContent>
        </Popover>
    );
}