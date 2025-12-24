import { Popover, PopoverContent, PopoverTrigger } from '@/components/bs-ui/popover';
import { cn } from '@/utils';
import { AreaChart, BarChart3, Filter, LayoutGrid, LineChart, PieChart, Ratio, Type } from "lucide-react";
import React, { useState } from 'react';

export const items = [
    // 图表类
    { id: 'indicator', label: '指标卡', category: 'chart', icon: <span className="font-bold text-blue-500 text-sm">123</span> },
    { id: 'bar', label: '柱状图', category: 'chart', icon: <BarChart3 className="w-5 h-5 text-blue-500" /> },
    { id: 'bar-h', label: '条形图', category: 'chart', icon: <div className="flex flex-col gap-1 w-5"><div className="h-1.5 bg-blue-500 w-full rounded-sm" /><div className="h-1.5 bg-blue-300 w-2/3 rounded-sm" /></div> },
    { id: 'line', label: '折线图', category: 'chart', icon: <LineChart className="w-5 h-5 text-blue-500" /> },
    { id: 'pie', label: '饼状图', category: 'chart', icon: <PieChart className="w-5 h-5 text-blue-500" /> },
    { id: 'ring', label: '环形图', category: 'chart', icon: <Ratio className="w-5 h-5 text-blue-500" /> },

    // 其他类
    { id: 'query', label: '查询组件', category: 'other', icon: <Filter className="w-5 h-5 text-slate-500" /> },
    // { id: 'text', label: '文本', category: 'other', icon: <Type className="w-5 h-5 text-slate-500" /> },
    // { id: 'layout', label: '组合布局', category: 'other', icon: <LayoutGrid className="w-5 h-5 text-slate-500" /> },
];

// 定义数据项结构
export interface PickerItem {
    id: string;
    label: string;
    icon: React.ReactNode;
    category: 'chart' | 'other';
}

interface ComponentPickerProps {
    items: PickerItem[];
    onSelect: (id: string) => void;
    children: React.ReactNode;
    className?: string;
}

const ComponentPicker = ({ onSelect, children, className }: ComponentPickerProps) => {
    const [open, setOpen] = useState(false);
    const charts = items.filter(i => i.category === 'chart');
    const others = items.filter(i => i.category === 'other');

    const handleItemClick = (id: string) => {
        onSelect(id);
        setOpen(false);
    };

    const ItemGrid = ({ list }: { list: PickerItem[] }) => (
        <div className="grid grid-cols-5 gap-y-4 gap-x-2">
            {list.map((item) => (
                <button
                    key={item.id}
                    onClick={() => handleItemClick(item.id)}
                    className="flex flex-col items-center group gap-2 outline-none"
                >
                    {/* 图标容器 */}
                    <div className="w-12 h-12 flex items-center justify-center rounded-lg bg-slate-50 group-hover:bg-blue-50 group-hover:text-blue-600 transition-colors border border-transparent group-hover:border-blue-100">
                        {item.icon}
                    </div>
                    {/* 文字说明 */}
                    <span className="text-[12px] text-gray-600 group-hover:text-blue-600 whitespace-nowrap">
                        {item.label}
                    </span>
                </button>
            ))}
        </div>
    );

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger asChild>
                {children}
            </PopoverTrigger>
            <PopoverContent align="start" className={cn("w-[320px] p-4 shadow-xl", className)}>
                <div className="space-y-6">
                    {/* 图表区域 */}
                    <div>
                        <h4 className="text-sm font-medium text-gray-400 mb-4 px-1">图表</h4>
                        <ItemGrid list={charts} />
                    </div>

                    {/* 其他区域 */}
                    <div>
                        <h4 className="text-sm font-medium text-gray-400 mb-4 px-1">其他</h4>
                        <ItemGrid list={others} />
                    </div>
                </div>
            </PopoverContent>
        </Popover>
    );
};

export default ComponentPicker;