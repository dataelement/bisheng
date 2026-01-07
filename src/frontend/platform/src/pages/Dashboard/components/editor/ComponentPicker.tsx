import { Popover, PopoverContent, PopoverTrigger } from '@/components/bs-ui/popover';
import { cn } from '@/utils';
import React, { useState } from 'react';
import { ChartType } from '../../types/dataConfig';

export const ChartGroupItems = [
    {
        label: '柱状图',
        data: [
            { type: ChartType.Bar, label: '基础柱状图' },
            { type: ChartType.StackedBar, label: '堆叠柱状图' },
            { type: ChartType.GroupedBar, label: '分组柱状图' }
        ]
    },
    {
        label: '条形图',
        data: [
            { type: ChartType.HorizontalBar, label: '基础条形图' },
            { type: ChartType.StackedHorizontalBar, label: '堆叠条形图' },
            { type: ChartType.GroupedHorizontalBar, label: '分组条形图' }
        ]
    },
    {
        label: '折线图',
        data: [
            { type: ChartType.Line, label: '基础折线图' },
            { type: ChartType.StackedLine, label: '堆叠折线图' },
            { type: ChartType.Area, label: '面积图' },
            { type: ChartType.StackedArea, label: '堆叠面积图' }
        ]
    },
    {
        label: '饼图',
        data: [
            { type: ChartType.Pie, label: '饼图' },
            { type: ChartType.Donut, label: '环形图' }
        ]
    },
    {
        label: '其他',
        data: [
            { type: ChartType.Metric, label: '指标卡' }
        ]
    }
];
export const ChartItems = ChartGroupItems.flatMap(item => item.data);

// 定义数据项结构
export interface PickerItem {
    type: string;
    label: string;
}

interface ComponentPickerProps {
    onSelect: (data: { title: string, type: ChartType }) => void;
    children: React.ReactNode;
    maxHeight?: number;
    className?: string;
}

const ComponentPicker = ({ children, className, onSelect, maxHeight = 500 }: ComponentPickerProps) => {
    const [open, setOpen] = useState(false);

    const handleItemClick = (item) => {
        onSelect({ ...item, title: item.label });
        setOpen(false);
    };

    const ItemGrid = ({ list }: { list: PickerItem[] }) => (
        <div className="flex flex-wrap gap-4">
            {list.map((item) => (
                <div
                    key={item.type}
                    onClick={() => handleItemClick(item)}
                    className={`flex flex-col items-center group gap-2 outline-none cursor-pointer ${item.type === ChartType.StackedLine && 'mr-2'}`}
                >
                    <div className="w-[88px] h-[86px] flex flex-col items-center justify-center border rounded-md group-hover:bg-blue-50 transition-colors group-hover:border-primary">
                        <img src={`${__APP_ENV__.BASE_URL}/assets/dashboard/${item.type}.png`} className="w-8 h-8 mb-2" />
                        <span className="text-[12px] text-gray-600 whitespace-nowrap">
                            {item.label}
                        </span>
                    </div>
                </div>
            ))}
        </div>
    );

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger asChild>
                {children}
            </PopoverTrigger>
            <PopoverContent
                align="start"
                className={cn("w-[342px] p-4 shadow-xl", className)}
                style={{ maxHeight: `${maxHeight}px`, overflowY: 'auto' }}
            >
                <div className="space-y-2">
                    {
                        ChartGroupItems.map((item, index) => (
                            <div key={index}>
                                <h4 className="text-sm font-medium mb-2 px-1">{item.label}</h4>
                                <ItemGrid list={item.data} />
                            </div>
                        ))
                    }
                </div>
            </PopoverContent>
        </Popover>
    );
};

export default ComponentPicker;