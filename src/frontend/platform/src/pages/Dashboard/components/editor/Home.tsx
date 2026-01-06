import { useEditorDashboardStore } from "@/store/dashboardStore"
import { ChartItems } from "./ComponentPicker"
import { cn } from "@/utils"
import { ChartType } from "../../types/dataConfig"

export default function Home() {
    const { addComponentToLayout } = useEditorDashboardStore()

    const handleItemClick = (item) => {
        addComponentToLayout({
            title: item.label,
            type: item.type
        })
    }

    return (
        <div className="h-full bg-background flex items-center justify-center p-8">
            <div className="w-full max-w-[720px]">
                {/* Header */}
                <div className="text-center mb-10">
                    <h1 className="text-lg text-foreground font-medium">请选择一个组件，开始搭建你的数据看板</h1>
                </div>

                {/* Chart Grid */}
                <div className="flex justify-center flex-wrap gap-4">
                    {ChartItems.flatMap(e => e.data).map((item) => (
                        <div
                            key={item.type}
                            onClick={() => handleItemClick(item)}
                            className={cn('w-[88px] h-[86px] flex flex-col items-center justify-center border rounded-md shadow-sm hover:shadow-lg transition-colors cursor-pointer',
                                item.type === ChartType.GroupedHorizontalBar && 'mr-10',
                                item.type === ChartType.Bar && 'ml-10',
                            )}>
                            <img src={`${__APP_ENV__.BASE_URL}/assets/dashboard/${item.type}.png`} className="w-8 h-8 mb-2" />
                            <span className="text-[12px] text-gray-600 whitespace-nowrap">{item.label}</span>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    )
}
