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
            // { type: ChartType.StackedLineOld, label: 'stackedLineChart' },
            { type: ChartType.StackedLine, label: 'multipleLineChart' },
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
            { type: ChartType.Metric, label: 'metricCard' },
            { type: ChartType.PivotTable, label: 'pivotTable' }
        ]
    }
];
const pivotTableItem = { type: ChartType.PivotTable, label: 'pivotTable' };
export const ChartItems = ChartGroupItems
    .flatMap(item => item.data)
    .filter(item => item.type !== ChartType.PivotTable)
    .flatMap(item => item.type === ChartType.GroupedHorizontalBar
        ? [item, pivotTableItem]
        : [item]);

export const PivotTableIcon = ({ className = "mb-2 h-8 w-8" }: { className?: string }) => (
    <svg
        aria-hidden="true"
        className={className}
        viewBox="0 0 32 32"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
    >
        <rect x="3.5" y="4.5" width="25" height="23" rx="2.5" fill="#EFF6FF" stroke="#3B82F6" />
        <path d="M3.5 11.5H28.5" stroke="#3B82F6" />
        <path d="M11.5 4.5V27.5" stroke="#3B82F6" />
        <path d="M20 11.5V27.5" stroke="#93C5FD" />
        <path d="M3.5 19.5H28.5" stroke="#93C5FD" />
        <rect x="4" y="5" width="7" height="6" rx="1.5" fill="#3B82F6" />
        <path d="M6.5 8H8.5" stroke="white" strokeLinecap="round" />
        <path d="M14 8H25.5" stroke="#60A5FA" strokeLinecap="round" />
        <path d="M6.5 15.5H8.5" stroke="#60A5FA" strokeLinecap="round" />
        <path d="M6.5 23.5H8.5" stroke="#60A5FA" strokeLinecap="round" />
    </svg>
);

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
        onSelect({ ...item, title: item.type === ChartType.Metric ? '' : t(`chart.${item.label}`) });
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
                        {item.type === ChartType.PivotTable ? (
                            <PivotTableIcon />
                        ) : (
                            <img src={`${__APP_ENV__.BASE_URL}/assets/dashboard/${item.type}.png`} className="w-8 h-8 mb-2" />
                        )}
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
