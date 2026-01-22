import { Popover, PopoverContent, PopoverTrigger } from '@/components/bs-ui/popover';
import { cn } from '@/utils';
import React, { memo, useState } from 'react';
import { ChartType } from '../../types/dataConfig';
import { useTranslation } from 'react-i18next';

export const ChartGroupItems = [
    {
        label: 'barChart',
        data: [
            { type: ChartType.Bar, label: 'basicBarChart' },
            { type: ChartType.StackedBar, label: 'stackedBarChart' },
            { type: ChartType.GroupedBar, label: 'groupedBarChart' }
        ]
    },
    {
        label: 'horizontalBarChart',
        data: [
            { type: ChartType.HorizontalBar, label: 'basicHorizontalBarChart' },
            { type: ChartType.StackedHorizontalBar, label: 'stackedHorizontalBarChart' },
            { type: ChartType.GroupedHorizontalBar, label: 'groupedHorizontalBarChart' }
        ]
    },
    {
        label: 'lineChart',
        data: [
            { type: ChartType.Line, label: 'basicLineChart' },
            { type: ChartType.StackedLine, label: 'stackedLineChart' },
            { type: ChartType.Area, label: 'areaChart' },
            { type: ChartType.StackedArea, label: 'stackedAreaChart' }
        ]
    },
    {
        label: 'pieChart',
        data: [
            { type: ChartType.Pie, label: 'pieChart' },
            { type: ChartType.Donut, label: 'donutChart' }
        ]
    },
    {
        label: 'others',
        data: [
            { type: ChartType.Metric, label: 'metricCard' }
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
    const { t } = useTranslation("dashboard")
    const [open, setOpen] = useState(false);

    const handleItemClick = (item) => {
        onSelect({ ...item, title: t(`chart.${item.label}`) });
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
                    <div className="w-[88px] min-h-[86px] flex flex-col items-center justify-center border rounded-md group-hover:bg-blue-50 transition-colors group-hover:border-primary">
                        <img src={`${__APP_ENV__.BASE_URL}/assets/dashboard/${item.type}.png`} className="w-8 h-8 mb-2" />
                        <span className="text-[12px] text-gray-600 text-center">
                            {t(`chart.${item.label}`)}
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
                                <h4 className="text-sm font-medium mb-2 px-1">{t(`chart.${item.label}`)}</h4>
                                <ItemGrid list={item.data} />
                            </div>
                        ))
                    }
                </div>
            </PopoverContent>
        </Popover>
    );
};

export default memo(ComponentPicker);