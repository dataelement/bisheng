import { Button } from '@/components/bs-ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/bs-ui/popover';
import { cn } from '@/utils';
import { Moon, Palette, Sun } from "lucide-react";
import { useState } from 'react';

const ThemePicker = ({ onSelect }: { onSelect?: (id: string) => void }) => {
    const [open, setOpen] = useState(false);

    // 硬编码的主题选项
    const themes = [
        {
            id: 'palette',
            label: '调色',
            icon: <Palette className="w-5 h-5 text-indigo-500" />
        },
        {
            id: 'gradient',
            label: '渐变色',
            // 使用 CSS 渐变模拟图标效果
            icon: <div className="w-5 h-5 rounded-full bg-gradient-to-br from-blue-400 via-purple-400 to-pink-400" />
        },
        {
            id: 'dark',
            label: '深色',
            icon: <Moon className="w-5 h-5 text-slate-700" fill="currentColor" />
        },
        {
            id: 'light',
            label: '浅色',
            icon: <Sun className="w-5 h-5 text-amber-500" />
        },
    ];

    const handleSelect = (id: string) => {
        onSelect?.(id);
        setOpen(false); // 点击后关闭
    };

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger asChild>
                <Button variant="outline" size="sm" className="gap-1.5 text-gray-600">
                    <Palette className="h-4 w-4" />
                    <span>主题</span>
                </Button>
            </PopoverTrigger>

            {/* 调整宽度以适配每行两个的布局 */}
            <PopoverContent align="start" className="w-48 p-3 shadow-xl">
                <div className="grid grid-cols-2 gap-2">
                    {themes.map((theme) => (
                        <button
                            key={theme.id}
                            onClick={() => handleSelect(theme.id)}
                            className={cn(
                                "flex flex-col items-center justify-center py-3 px-2 rounded-lg transition-all",
                                "bg-slate-50 hover:bg-blue-50 border border-transparent hover:border-blue-100 group"
                            )}
                        >
                            {/* 图标容器 */}
                            <div className="mb-2 flex items-center justify-center">
                                {theme.icon}
                            </div>
                            {/* 标签文本 */}
                            <span className="text-[12px] text-gray-600 group-hover:text-blue-600">
                                {theme.label}
                            </span>
                        </button>
                    ))}
                </div>
            </PopoverContent>
        </Popover>
    );
};

export default ThemePicker;